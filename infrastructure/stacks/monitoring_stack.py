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


class MonitoringStack(cdk.Stack):
    """監視対象システム — fake-api-server とアラーム自動化レイヤーをまとめたスタック。

    Agora プラットフォーム本体（DataStack / ComputeStack）とは独立して
    デプロイ・削除できる。

    アーキテクチャ:
      fake-api-server Lambda (EventBridge Scheduler で定期実行)
        → ec2:DescribeInstances (ヘルスチェック模擬) ← FIS injection target
        → Lambda/Errors メトリクス
      CloudWatch Alarm
        → EventBridge Default Bus (自動、SNS 不要)
      EventBridge Rule (state=ALARM のみ通過)
        → SQS Queue (agora-alarm-queue)
            DLQ (agora-alarm-dlq): maxReceiveCount=3
      Bridge Lambda (SQS トリガー)
        → POST /tickets  Ticket Service REST API (チケット起票のみ)
    エージェント起動は Agora 側 ticket-dispatcher Lambda (ComputeStack) が担う。
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # -------------------------------------------------------------------------
        # fake-api-server Lambda — 監視対象システム
        # EC2 DescribeInstances を定期呼び出しし稼働状況を確認する軽量ヘルスチェック。
        # 追加リソース不要・常時コストゼロ。FIS のブラストラジアスはこの IAM ロールのみ。
        # -------------------------------------------------------------------------
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

        # EventBridge Scheduler — デフォルト DISABLED。demo-start で有効化
        self.scheduler_role = iam.Role(
            self,
            "SchedulerRole",
            role_name="agora-scheduler-role",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )
        self.fake_api_fn.grant_invoke(self.scheduler_role)

        scheduler.CfnSchedule(
            self,
            "FakeApiSchedule",
            name="agora-fake-api-server-schedule",
            schedule_expression="rate(1 minute)",
            state="DISABLED",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="OFF"
            ),
            target=scheduler.CfnSchedule.TargetProperty(
                arn=self.fake_api_fn.function_arn,
                role_arn=self.scheduler_role.role_arn,
            ),
        )

        # -------------------------------------------------------------------------
        # CloudWatch Alarm — fake-api-server の Lambda/Errors を監視
        # 2分連続でエラーが発生したら ALARM → EventBridge へ自動発行
        # -------------------------------------------------------------------------
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

        # -------------------------------------------------------------------------
        # SQS — アラームイベントのバッファ + 信頼性保証
        #
        # Visibility Timeout (180s) > Bridge Lambda timeout (120s):
        #   Lambda が処理中に同一メッセージが再配信されないよう保証
        # DLQ + maxReceiveCount=3:
        #   3 回失敗したメッセージを DLQ に退避し、消失を防ぎ後から調査・再処理可能にする
        # -------------------------------------------------------------------------
        alarm_dlq = sqs.Queue(
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
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=alarm_dlq,
            ),
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # -------------------------------------------------------------------------
        # EventBridge Rule — CloudWatch Alarm ALARM 状態変化のみ SQS へ転送
        # CloudWatch Alarm は state change を Default Bus へ自動発行する (SNS 不要)
        # -------------------------------------------------------------------------
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

        # -------------------------------------------------------------------------
        # Bridge Lambda — SQS → Ticket Service REST API
        # -------------------------------------------------------------------------
        bridge_role = iam.Role(
            self,
            "BridgeRole",
            role_name="agora-bridge-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
                # SQS ポーリング (ReceiveMessage / DeleteMessage / GetQueueAttributes)
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaSQSQueueExecutionRole"
                ),
            ],
        )
        bridge_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}"
                    ":secret:agora/services-api-key*"
                ],
            )
        )

        bridge_fn = lambda_.Function(
            self,
            "BridgeFn",
            function_name="agora-bridge",
            code=lambda_.Code.from_asset(str(_SERVICES_DIR / "bridge")),
            handler="lambda_function.handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            memory_size=256,
            timeout=cdk.Duration.seconds(120),
            role=bridge_role,
            environment={
                # Ticket Service URL を SSM から動的解決 (cross-stack 依存なし)
                "TICKET_SERVICE_URL": ssm.StringParameter.value_for_string_parameter(
                    self, "/agora/ticket-service-url"
                ),
                "API_KEY_SECRET_NAME": "agora/services-api-key",
            },
        )

        bridge_fn.add_event_source(
            event_sources.SqsEventSource(
                self.alarm_queue,
                batch_size=1,
            )
        )

        # -------------------------------------------------------------------------
        # FIS — EC2 DescribeInstances スロットリング注入実験テンプレート
        #
        # aws:fis:inject-api-throttle-error で agora-fake-api-role への
        # ec2:DescribeInstances 呼び出しをスロットリング。追加リソース不要・常時コストゼロ。
        #
        # デモシナリオ:
        #   make demo-inject → fake-api-server の ec2:DescribeInstances が ThrottlingException
        #   → Lambda/Errors 増加 → CloudWatch Alarm ALARM → EventBridge → SQS
        #   → Bridge → チケット起票 → ticket-dispatcher → Gateway Agent → 診断・解決
        # -------------------------------------------------------------------------
        fis_role = iam.Role(
            self,
            "FisRole",
            role_name="agora-fis-role",
            assumed_by=iam.ServicePrincipal("fis.amazonaws.com"),
        )
        fis_role.add_to_policy(
            iam.PolicyStatement(
                actions=["fis:InjectApiThrottleError"],
                resources=[self.fake_api_role.role_arn],
            )
        )

        fis_template = fis.CfnExperimentTemplate(
            self,
            "ThrottleExperimentTemplate",
            description="EC2 API スロットリング注入 — fake-api-server 障害シナリオ",
            role_arn=fis_role.role_arn,
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
                fis.CfnExperimentTemplate.ExperimentTemplateStopConditionProperty(
                    source="none",
                )
            ],
        )

        # -------------------------------------------------------------------------
        # Outputs
        # -------------------------------------------------------------------------
        cdk.CfnOutput(self, "FakeApiServerFnArn", value=self.fake_api_fn.function_arn)
        cdk.CfnOutput(self, "SchedulerRoleArn", value=self.scheduler_role.role_arn)
        cdk.CfnOutput(self, "AlarmQueueUrl", value=self.alarm_queue.queue_url)
        cdk.CfnOutput(self, "AlarmDlqUrl", value=alarm_dlq.queue_url)
        cdk.CfnOutput(self, "BridgeFnArn", value=bridge_fn.function_arn)
        cdk.CfnOutput(self, "FisTemplateId", value=fis_template.attr_id)
