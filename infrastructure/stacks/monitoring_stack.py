from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
import aws_cdk.aws_cloudwatch as cloudwatch
import aws_cdk.aws_dynamodb as dynamodb
import aws_cdk.aws_events as events
import aws_cdk.aws_events_targets as targets
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
        → DynamoDB GetItem (agora-monitored-api-data) ← FIS injection target
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
        # DynamoDB テーブル — fake-api-server 専用 (FIS injection target)
        # agora-assets / agora-tickets とは完全分離し FIS のブラストラジアスを限定
        # -------------------------------------------------------------------------
        self.monitored_api_table = dynamodb.Table(
            self,
            "MonitoredApiDataTable",
            table_name="agora-monitored-api-data",
            partition_key=dynamodb.Attribute(
                name="item_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # -------------------------------------------------------------------------
        # fake-api-server Lambda — 監視対象システム
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
                actions=["dynamodb:GetItem"],
                resources=[self.monitored_api_table.table_arn],
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
            environment={
                "TABLE_NAME": self.monitored_api_table.table_name,
                "ITEM_ID": "config-001",
            },
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
        # Bridge Lambda — SQS → Ticket Service REST API + Gateway Agent
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
        # Outputs
        # -------------------------------------------------------------------------
        cdk.CfnOutput(
            self, "MonitoredApiTableArn", value=self.monitored_api_table.table_arn
        )
        cdk.CfnOutput(self, "FakeApiServerFnArn", value=self.fake_api_fn.function_arn)
        cdk.CfnOutput(self, "SchedulerRoleArn", value=self.scheduler_role.role_arn)
        cdk.CfnOutput(self, "AlarmQueueUrl", value=self.alarm_queue.queue_url)
        cdk.CfnOutput(self, "AlarmDlqUrl", value=alarm_dlq.queue_url)
        cdk.CfnOutput(self, "BridgeFnArn", value=bridge_fn.function_arn)
