from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
import aws_cdk.aws_cloudwatch as cloudwatch
import aws_cdk.aws_events as events
import aws_cdk.aws_events_targets as targets
import aws_cdk.aws_fis as fis
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_lambda_event_sources as event_sources
import aws_cdk.aws_scheduler as scheduler
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_ssm as ssm
from constructs import Construct

_SERVICES_DIR = Path(__file__).parent.parent.parent / "services"


class FaultInjectionStack(cdk.Stack):
    """監視対象システム (fake-api) と障害注入シナリオ。

    Agora プラットフォーム本体 (AgoraStack) とは独立して削除できる。
    チケットサービス URL は SSM (/agora/ticket-service-url) 経由で参照する。

    アーキテクチャ:
      fake-api-server Lambda (EventBridge Scheduler で定期実行)
        → ec2:DescribeInstances ← FIS ThrottlingException 注入ターゲット
      CloudWatch Alarm → EventBridge Rule → SQS → Bridge Lambda
        → POST /tickets (Ticket Service REST API でチケット起票)
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # =====================================================================
        # fake-api-server — 監視対象 Lambda
        # =====================================================================
        self.fake_api_role = iam.Role(
            self,
            "FakeApiRole",
            role_name="agora-fake-api-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )
        self.fake_api_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ec2:DescribeInstances"],
                resources=["*"],
            )
        )

        self.fake_api_fn = lambda_.Function(
            self,
            "FakeApiServerFn",
            function_name="agora-fake-api-server",
            code=lambda_.Code.from_asset(str(_SERVICES_DIR / "fake-api-server")),
            handler="lambda_function.handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            memory_size=256,
            timeout=cdk.Duration.seconds(30),
            role=self.fake_api_role,
        )

        # EventBridge Scheduler — デフォルト DISABLED。make demo-start で有効化
        _scheduler_role = iam.Role(
            self,
            "SchedulerRole",
            role_name="agora-scheduler-role",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )
        self.fake_api_fn.grant_invoke(_scheduler_role)

        scheduler.CfnSchedule(
            self,
            "FakeApiSchedule",
            name="agora-fake-api-server-schedule",
            schedule_expression="rate(1 minute)",
            state="DISABLED",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
            target=scheduler.CfnSchedule.TargetProperty(
                arn=self.fake_api_fn.function_arn,
                role_arn=_scheduler_role.role_arn,
            ),
        )

        # =====================================================================
        # CloudWatch Alarm — fake-api-server Lambda/Errors を監視
        # =====================================================================
        self.alarm = cloudwatch.Alarm(
            self,
            "FakeApiErrorAlarm",
            alarm_name="agora-fake-api-error-rate",
            alarm_description="fake-api-server Lambda が連続エラー (FIS 障害注入の検知)",
            metric=cloudwatch.Metric(
                namespace="AWS/Lambda",
                metric_name="Errors",
                dimensions_map={"FunctionName": "agora-fake-api-server"},
                period=cdk.Duration.minutes(1),
                statistic="Sum",
            ),
            threshold=1,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # =====================================================================
        # SQS — アラームイベントのバッファ
        # =====================================================================
        _alarm_dlq = sqs.Queue(
            self,
            "AlarmDlq",
            queue_name="agora-alarm-dlq",
            retention_period=cdk.Duration.days(14),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        self.alarm_queue = sqs.Queue(
            self,
            "AlarmQueue",
            queue_name="agora-alarm-queue",
            visibility_timeout=cdk.Duration.seconds(180),
            retention_period=cdk.Duration.days(1),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=_alarm_dlq),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # =====================================================================
        # EventBridge Rule — ALARM 状態変化のみ SQS へ転送
        # =====================================================================
        events.Rule(
            self,
            "AlarmStateChangeRule",
            rule_name="agora-alarm-to-queue",
            event_pattern=events.EventPattern(
                source=["aws.cloudwatch"],
                detail_type=["CloudWatch Alarm State Change"],
                detail={
                    "alarmName": ["agora-fake-api-error-rate"],
                    "state": {"value": ["ALARM"]},
                },
            ),
            targets=[targets.SqsQueue(self.alarm_queue)],
        )

        # =====================================================================
        # Bridge Lambda — SQS → Ticket Service REST API
        # =====================================================================
        _bridge_role = iam.Role(
            self,
            "BridgeRole",
            role_name="agora-bridge-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaSQSQueueExecutionRole"
                ),
            ],
        )
        _bridge_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}"
                    ":secret:agora/services-api-key*"
                ],
            )
        )

        _bridge_fn = lambda_.Function(
            self,
            "BridgeFn",
            function_name="agora-bridge",
            code=lambda_.Code.from_asset(
                str(_SERVICES_DIR / "bridge"),
                bundling=cdk.BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    platform="linux/arm64",
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output"
                        " && cp lambda_function.py /asset-output/",
                    ],
                ),
            ),
            handler="lambda_function.handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            memory_size=256,
            timeout=cdk.Duration.seconds(120),
            role=_bridge_role,
            environment={
                # チケットサービス URL は SSM 経由 (AgoraStack に依存しない)
                "TICKET_SERVICE_URL": ssm.StringParameter.value_for_string_parameter(
                    self, "/agora/ticket-service-url"
                ),
                "API_KEY_SECRET_NAME": "agora/services-api-key",
            },
        )

        _bridge_fn.add_event_source(
            event_sources.SqsEventSource(self.alarm_queue, batch_size=1)
        )

        # =====================================================================
        # FIS — EC2 DescribeInstances スロットリング注入実験テンプレート
        # =====================================================================
        _fis_role = iam.Role(
            self,
            "FisRole",
            role_name="agora-fis-role",
            assumed_by=iam.ServicePrincipal("fis.amazonaws.com"),
        )
        _fis_role.add_to_policy(
            iam.PolicyStatement(
                actions=["fis:InjectApiThrottleError"],
                resources=[f"arn:aws:fis:{self.region}:{self.account}:experiment/*"],
            )
        )

        _fis_template = fis.CfnExperimentTemplate(
            self,
            "ThrottleExperimentTemplate",
            description="EC2 API スロットリング注入 — fake-api-server 障害シナリオ",
            role_arn=_fis_role.role_arn,
            tags={"Project": "agora", "Scenario": "inject-api-throttle-error"},
            targets={
                "FakeApiRole": fis.CfnExperimentTemplate.ExperimentTemplateTargetProperty(
                    resource_type="aws:iam:role",
                    selection_mode="ALL",
                    resource_arns=[self.fake_api_role.role_arn],
                )
            },
            actions={
                "InjectEC2Throttle": fis.CfnExperimentTemplate.ExperimentTemplateActionProperty(
                    action_id="aws:fis:inject-api-throttle-error",
                    parameters={
                        "service": "ec2",
                        "operations": "DescribeInstances",
                        "percentage": "100",
                        "duration": "PT5M",
                    },
                    targets={"Roles": "FakeApiRole"},
                )
            },
            stop_conditions=[
                fis.CfnExperimentTemplate.ExperimentTemplateStopConditionProperty(source="none")
            ],
        )

        # =====================================================================
        # OUTPUTS
        # =====================================================================
        cdk.CfnOutput(self, "FakeApiServerFnArn", value=self.fake_api_fn.function_arn)
        cdk.CfnOutput(self, "AlarmQueueUrl", value=self.alarm_queue.queue_url)
        cdk.CfnOutput(self, "FisTemplateId", value=_fis_template.attr_id)
