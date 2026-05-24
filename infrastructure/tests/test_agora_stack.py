from __future__ import annotations

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template
from stacks.agora_stack import AgoraStack


@pytest.fixture(scope="module")
def template() -> Template:
    app = cdk.App()
    stack = AgoraStack(
        app, "TestAgoraStack", env=cdk.Environment(account="123456789012", region="us-east-1")
    )
    return Template.from_stack(stack)


# ---------------------------------------------------------------------------
# DynamoDB
# ---------------------------------------------------------------------------

def test_dynamodb_tables_exist(template: Template) -> None:
    for table_name in ("agora-tickets", "agora-knowledge"):
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {"TableName": table_name, "BillingMode": "PAY_PER_REQUEST"},
        )


# ---------------------------------------------------------------------------
# Lambda — アーキテクチャ・ハンドラ
# ---------------------------------------------------------------------------

def test_service_lambdas_are_arm64(template: Template) -> None:
    for fn_name in (
        "agora-ticket-service", "agora-chat-proxy"
    ):
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {"FunctionName": fn_name, "Architectures": ["arm64"]},
        )


def test_ticket_dispatcher_config(template: Template) -> None:
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "agora-ticket-dispatcher",
            "Architectures": ["arm64"],
            "Handler": "lambda_function.handler",
            "Runtime": "python3.12",
            "Environment": {
                "Variables": {
                    "AGENT_RUNTIME_ARN": Match.any_value(),
                }
            },
        },
    )


def test_knowledge_consumer_config(template: Template) -> None:
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "agora-knowledge-consumer",
            "Architectures": ["arm64"],
            "Handler": "lambda_function.handler",
            "Runtime": "python3.12",
            "Environment": {
                "Variables": {
                    "KNOWLEDGE_TABLE_NAME": Match.any_value(),
                }
            },
        },
    )


def test_service_lambdas_have_table_name_env(template: Template) -> None:
    """各サービス Lambda に TABLE_NAME が注入されていることを確認する。"""
    for fn_name in ("agora-ticket-service",):
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {
                "FunctionName": fn_name,
                "Environment": {"Variables": {"TABLE_NAME": Match.any_value()}},
            },
        )


def test_chat_proxy_has_agent_runtime_arn(template: Template) -> None:
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "agora-chat-proxy",
            "Environment": {"Variables": {"AGENT_RUNTIME_ARN": Match.any_value()}},
        },
    )


# ---------------------------------------------------------------------------
# Lambda — 個数
# ---------------------------------------------------------------------------

def test_lambda_function_count(template: Template) -> None:
    """期待するLambda関数数を確認する（新規追加時に意図的な変更であることを強制する）。"""
    resources = template.find_resources(
        "AWS::Lambda::Function",
        props=Match.object_like({}),
    )
    # ticket + chat-proxy + ticket-dispatcher + knowledge-consumer
    # + registry-catalog + gateway-targets
    # (BucketDeployment 内部 Lambda 群を除いた数)
    named_fns = [
        r for r in resources.values()
        if r.get("Properties", {}).get("FunctionName", "").startswith("agora-")
    ]
    assert len(named_fns) == 6, f"agora- Lambda 数が変わっています: {len(named_fns)}"
