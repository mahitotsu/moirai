from __future__ import annotations

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template
from stacks.fault_injection_stack import FaultInjectionStack


@pytest.fixture(scope="module")
def template() -> Template:
    app = cdk.App()
    stack = FaultInjectionStack(
        app, "TestFaultInjectionStack",
        env=cdk.Environment(account="123456789012", region="us-east-1")
    )
    return Template.from_stack(stack)


# ---------------------------------------------------------------------------
# Lambda — アーキテクチャ・ハンドラ
# ---------------------------------------------------------------------------

def test_bridge_lambda_config(template: Template) -> None:
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "agora-bridge",
            "Architectures": ["arm64"],
            "Handler": "lambda_function.handler",
            "Runtime": "python3.12",
        },
    )


def test_bridge_lambda_has_required_env_vars(template: Template) -> None:
    """Bridge Lambda に TICKET_SERVICE_URL と API_KEY_SECRET_NAME が注入されていることを確認する。"""  # noqa: E501
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "agora-bridge",
            "Environment": {
                "Variables": {
                    "TICKET_SERVICE_URL": Match.any_value(),
                    "API_KEY_SECRET_NAME": Match.any_value(),
                }
            },
        },
    )


def test_fake_api_server_config(template: Template) -> None:
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "agora-fake-api-server",
            "Architectures": ["arm64"],
            "Handler": "lambda_function.handler",
            "Runtime": "python3.12",
        },
    )


# ---------------------------------------------------------------------------
# SQS / DLQ
# ---------------------------------------------------------------------------

def test_bridge_dlq_exists(template: Template) -> None:
    template.has_resource_properties(
        "AWS::SQS::Queue",
        {"QueueName": Match.string_like_regexp(".*dlq.*")},
    )
