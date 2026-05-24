from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.modules.pop("server", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_mock_lambda = MagicMock()
_mock_fis = MagicMock()
_mock_cfn = MagicMock()


def _make_boto3(service: str, **_: object) -> MagicMock:
    return {"lambda": _mock_lambda, "fis": _mock_fis, "cloudformation": _mock_cfn}[service]


with patch("boto3.client", side_effect=_make_boto3):
    import server as _infra_server  # noqa: E402

server = _infra_server
# Pre-populate the lazy client cache so mocks are returned on every call
server._clients["lambda"] = _mock_lambda
server._clients["fis"] = _mock_fis
server._clients["cfn"] = _mock_cfn


# ---------------------------------------------------------------------------
# inspect_lambda
# ---------------------------------------------------------------------------

def test_inspect_lambda_returns_config() -> None:
    _mock_lambda.get_function.return_value = {
        "Configuration": {
            "FunctionName": "agora-fake-api-server",
            "Description": "Fake API server for demo",
            "Runtime": "python3.12",
            "Handler": "lambda_function.handler",
            "Timeout": 30,
            "MemorySize": 256,
            "LastModified": "2025-01-01T00:00:00.000+0000",
            "Environment": {"Variables": {"AWS_REGION": "us-east-1"}},
        }
    }
    _mock_lambda.list_event_source_mappings.return_value = {"EventSourceMappings": []}

    result = server.inspect_lambda("agora-fake-api-server")

    assert "agora-fake-api-server" in result
    assert "python3.12" in result
    assert "30s" in result
    assert "AWS_REGION" in result


def test_inspect_lambda_shows_event_source_mappings() -> None:
    _mock_lambda.get_function.return_value = {
        "Configuration": {
            "FunctionName": "fn",
            "Runtime": "python3.12",
            "Timeout": 10,
            "MemorySize": 128,
        }
    }
    _mock_lambda.list_event_source_mappings.return_value = {
        "EventSourceMappings": [
            {"EventSourceArn": "arn:aws:sqs:us-east-1:123:queue", "State": "Enabled"}
        ]
    }

    result = server.inspect_lambda("fn")
    assert "sqs" in result


def test_inspect_lambda_returns_error_message_on_exception() -> None:
    _mock_lambda.get_function.side_effect = Exception("ResourceNotFoundException")

    result = server.inspect_lambda("nonexistent")
    assert "Failed" in result
    assert "nonexistent" in result
    _mock_lambda.get_function.side_effect = None


# ---------------------------------------------------------------------------
# list_active_fis_experiments
# ---------------------------------------------------------------------------

def test_list_active_fis_experiments_returns_none_running() -> None:
    _mock_fis.list_experiments.return_value = {"experiments": []}

    result = server.list_active_fis_experiments()
    assert "No FIS experiments" in result


def test_list_active_fis_experiments_returns_details() -> None:
    _mock_fis.list_experiments.return_value = {
        "experiments": [{"id": "exp-abc123", "experimentTemplateId": "EXTabc", "state": {"status": "running"}}]
    }
    _mock_fis.get_experiment.return_value = {
        "experiment": {
            "id": "exp-abc123",
            "experimentTemplateId": "EXTabc",
            "state": {"status": "running"},
            "startTime": "2025-01-01T10:00:00Z",
            "actions": {
                "inject-throttle": {
                    "actionId": "aws:ec2:api-insufficient-data-error",
                    "parameters": {"errorCode": "ThrottlingException", "percentage": "100"},
                }
            },
            "targets": {
                "ec2-api": {
                    "resourceType": "aws:ec2:instances",
                    "resourceArns": [],
                }
            },
        }
    }

    result = server.list_active_fis_experiments()
    assert "exp-abc123" in result
    assert "ThrottlingException" in result
    assert "running" in result


# ---------------------------------------------------------------------------
# describe_cfn_stack
# ---------------------------------------------------------------------------

def test_describe_cfn_stack_returns_resources() -> None:
    _mock_cfn.describe_stacks.return_value = {
        "Stacks": [{
            "StackName": "FaultInjectionStack",
            "StackStatus": "UPDATE_COMPLETE",
            "CreationTime": "2025-01-01T00:00:00Z",
            "Description": "FIS demo stack",
        }]
    }
    _mock_cfn.describe_stack_resources.return_value = {
        "StackResources": [
            {
                "ResourceType": "AWS::Lambda::Function",
                "LogicalResourceId": "FakeApiServerFn",
                "PhysicalResourceId": "agora-fake-api-server",
                "ResourceStatus": "UPDATE_COMPLETE",
            }
        ]
    }

    result = server.describe_cfn_stack("FaultInjectionStack")
    assert "FaultInjectionStack" in result
    assert "FakeApiServerFn" in result
    assert "AWS::Lambda::Function" in result


def test_describe_cfn_stack_returns_error_message_on_exception() -> None:
    _mock_cfn.describe_stacks.side_effect = Exception("Stack does not exist")

    result = server.describe_cfn_stack("NonExistentStack")
    assert "Failed" in result
    _mock_cfn.describe_stacks.side_effect = None
