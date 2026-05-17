from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
import aws_cdk.aws_dynamodb as dynamodb
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_scheduler as scheduler
from constructs import Construct

_SERVICES_DIR = Path(__file__).parent.parent.parent / "services"


class MonitoringStack(cdk.Stack):
    """監視対象システム — fake-api-server とその周辺リソースをまとめたスタック。

    Agora プラットフォーム本体（DataStack / ComputeStack）とは独立して
    デプロイ・削除できる。FIS 障害注入はこのスタック内のテーブルのみを
    ターゲットにするため、agora-tickets / agora-assets への影響がない。
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # -------------------------------------------------------------------------
        # DynamoDB テーブル — fake-api-server 専用 (FIS injection target)
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
        # IAM 実行ロール — fake-api-server Lambda 専用 (最小権限)
        # GetItem on agora-monitored-api-data のみ許可
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

        # -------------------------------------------------------------------------
        # fake-api-server Lambda
        # -------------------------------------------------------------------------
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
                "TABLE_NAME": "agora-monitored-api-data",
                "ITEM_ID": "config-001",
            },
        )

        # -------------------------------------------------------------------------
        # EventBridge Scheduler — デフォルト DISABLED。demo-start で有効化
        # -------------------------------------------------------------------------
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
        # Outputs
        # -------------------------------------------------------------------------
        cdk.CfnOutput(
            self, "MonitoredApiTableArn", value=self.monitored_api_table.table_arn
        )
        cdk.CfnOutput(self, "FakeApiServerFnArn", value=self.fake_api_fn.function_arn)
        cdk.CfnOutput(self, "SchedulerRoleArn", value=self.scheduler_role.role_arn)
