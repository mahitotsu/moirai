from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
import aws_cdk.aws_cloudwatch as cloudwatch
import aws_cdk.aws_ecr_assets as ecr_assets
import aws_cdk.aws_events as events
import aws_cdk.aws_fis as fis
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_lambda_event_sources as event_sources
import aws_cdk.aws_scheduler as scheduler
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_ssm as ssm
from constructs import Construct

_SERVICES_DIR = Path(__file__).parent.parent.parent / "services"

# ── Lambda ────────────────────────────────────────────────────────────────
_MEMORY_MB = 256

# ADOT auto-instrumentation via Lambda Extension (layer.zip in Dockerfile)
_ADOT_ENV = {
    "AWS_LAMBDA_EXEC_WRAPPER": "/opt/otel-instrument",
    "OTEL_PROPAGATORS": "xray",
    "OTEL_AWS_APPLICATION_SIGNALS_ENABLED": "false",
}
_TIMEOUT_STANDARD = cdk.Duration.seconds(30)
_TIMEOUT_BRIDGE = cdk.Duration.seconds(120)
_TIMEOUT_VISIBILITY = cdk.Duration.seconds(180)

# ── SQS ───────────────────────────────────────────────────────────────────
_DLQ_RETENTION = cdk.Duration.days(14)
_ALARM_QUEUE_RETENTION = cdk.Duration.days(1)
_DLQ_MAX_RECEIVE = 3

# ── CloudWatch Alarm ───────────────────────────────────────────────────────
_ALARM_THRESHOLD = 1
_ALARM_EVALUATION_PERIODS = 2
_ALARM_DATAPOINTS = 2


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
        _xray_write = iam.ManagedPolicy.from_aws_managed_policy_name("AWSXRayDaemonWriteAccess")
        self.fake_api_role = iam.Role(
            self,
            "FakeApiRole",
            role_name="agora-fake-api-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
                _xray_write,
            ],
        )
        self.fake_api_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ec2:DescribeInstances"],
                resources=["*"],
            )
        )

        self.fake_api_fn = lambda_.DockerImageFunction(
            self,
            "FakeApiServerFn",
            function_name="agora-fake-api-server",
            description=(
                "Simulates a backend API health-check by calling EC2 DescribeInstances. "
                "Scheduled every minute. FIS ThrottlingException injection target."
            ),
            code=lambda_.DockerImageCode.from_image_asset(
                str(_SERVICES_DIR / "fake-api-server"),
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=_MEMORY_MB,
            timeout=_TIMEOUT_STANDARD,
            tracing=lambda_.Tracing.ACTIVE,
            role=self.fake_api_role,
            environment=_ADOT_ENV,
        )
        cdk.Tags.of(self.fake_api_fn).add(
            "agora:role",
            "monitored-target",
        )
        cdk.Tags.of(self.fake_api_fn).add(
            "agora:fis-target",
            "ec2:DescribeInstances ThrottlingException injection",
        )

        # EventBridge Scheduler — デフォルト DISABLED。make demo-start で有効化
        _scheduler_role = iam.Role(
            self,
            "SchedulerRole",
            role_name="agora-scheduler-role",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )
        _scheduler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[self.fake_api_fn.function_arn],
            )
        )

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
                dimensions_map={"FunctionName": self.fake_api_fn.function_name},
                period=cdk.Duration.minutes(1),
                statistic="Sum",
            ),
            threshold=_ALARM_THRESHOLD,
            evaluation_periods=_ALARM_EVALUATION_PERIODS,
            datapoints_to_alarm=_ALARM_DATAPOINTS,
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
            retention_period=_DLQ_RETENTION,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        self.alarm_queue = sqs.Queue(
            self,
            "AlarmQueue",
            queue_name="agora-alarm-queue",
            visibility_timeout=_TIMEOUT_VISIBILITY,
            retention_period=_ALARM_QUEUE_RETENTION,
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=_DLQ_MAX_RECEIVE, queue=_alarm_dlq
            ),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # =====================================================================
        # EventBridge Rule — ALARM 状態変化のみ SQS へ転送
        # =====================================================================
        alarm_rule = events.CfnRule(
            self,
            "AlarmStateChangeRule",
            name="agora-alarm-to-queue",
            event_pattern={
                "source": ["aws.cloudwatch"],
                "detail-type": ["CloudWatch Alarm State Change"],
                "detail": {
                    "alarmName": [self.alarm.alarm_name],
                    "state": {"value": ["ALARM"]},
                },
            },
            targets=[
                events.CfnRule.TargetProperty(
                    id="AlarmQueue",
                    arn=self.alarm_queue.queue_arn,
                )
            ],
        )

        # EventBridge が SQS へ送信できるよう SQS リソースポリシーを明示設定
        sqs.CfnQueuePolicy(
            self,
            "AlarmQueuePolicy",
            queues=[self.alarm_queue.queue_url],
            policy_document={
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "events.amazonaws.com"},
                        "Action": "sqs:SendMessage",
                        "Resource": self.alarm_queue.queue_arn,
                        "Condition": {
                            "ArnEquals": {"aws:SourceArn": alarm_rule.attr_arn},
                        },
                    }
                ],
            },
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
                _xray_write,
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

        _bridge_fn = lambda_.DockerImageFunction(
            self,
            "BridgeFn",
            function_name="agora-bridge",
            code=lambda_.DockerImageCode.from_image_asset(
                str(_SERVICES_DIR / "bridge"),
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=_MEMORY_MB,
            timeout=_TIMEOUT_BRIDGE,
            tracing=lambda_.Tracing.ACTIVE,
            role=_bridge_role,
            environment={
                **_ADOT_ENV,
                # チケットサービス URL は SSM 経由 (AgoraStack に依存しない)
                "TICKET_SERVICE_URL": ssm.StringParameter.value_for_string_parameter(
                    self, "/agora/ticket-service-url"
                ),
                "API_KEY_SECRET_NAME": ssm.StringParameter.value_for_string_parameter(
                    self, "/agora/services-api-key-name"
                ),
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
