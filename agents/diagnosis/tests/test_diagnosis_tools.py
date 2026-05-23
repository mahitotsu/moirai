from __future__ import annotations

import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("TICKETS_TABLE", "agora-test-tickets")
os.environ.setdefault("AWS_REGION", "us-east-1")

_spec = importlib.util.spec_from_file_location(
    "diagnosis_tools", os.path.join(os.path.dirname(__file__), "..", "tools.py")
)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
with patch("boto3.client", return_value=MagicMock()):
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
sys.modules["diagnosis_tools"] = _mod
tools = _mod


def _dynamo_item(**fields: str) -> dict:
    return {k: {"S": v} for k, v in fields.items()}


def test_check_cloudwatch_alarms_returns_alarm_details() -> None:
    mock_resp = {"MetricAlarms": [{
        "AlarmName": "agora-fake-api-error-rate",
        "AlarmDescription": "Error rate too high",
        "StateValue": "ALARM",
        "StateUpdatedTimestamp": "2026-05-23T00:00:00Z",
        "Namespace": "AWS/Lambda",
        "MetricName": "Errors",
        "StateReason": "Threshold crossed",
    }]}
    with patch.object(tools, "_cloudwatch") as m:
        m.describe_alarms.return_value = mock_resp
        result = tools.check_cloudwatch_alarms()
    assert "agora-fake-api-error-rate" in result
    assert "ALARM" in result


def test_check_cloudwatch_alarms_no_active_alarms() -> None:
    with patch.object(tools, "_cloudwatch") as m:
        m.describe_alarms.return_value = {"MetricAlarms": []}
        assert "No active alarms" in tools.check_cloudwatch_alarms()


def test_check_cloudwatch_alarms_on_error() -> None:
    with patch.object(tools, "_cloudwatch") as m:
        m.describe_alarms.side_effect = Exception("AccessDenied")
        assert "failed" in tools.check_cloudwatch_alarms().lower()


def test_search_past_tickets_returns_resolved_tickets() -> None:
    mock_resp = {"Items": [_dynamo_item(
        ticket_id="t-1", title="DB timeout", category="database",
        severity="high", status="resolved", resolution="Increased pool size",
    )]}
    with patch.object(tools, "_dynamodb") as m:
        m.query.return_value = mock_resp
        result = tools.search_past_tickets("database timeout")
    assert "t-1" in result
    assert "Increased pool size" in result


def test_search_past_tickets_no_results() -> None:
    with patch.object(tools, "_dynamodb") as m:
        m.query.return_value = {"Items": []}
        assert "No past resolved tickets" in tools.search_past_tickets("rare")


def test_search_past_tickets_on_error() -> None:
    with patch.object(tools, "_dynamodb") as m:
        m.query.side_effect = Exception("DynamoDB unreachable")
        assert "failed" in tools.search_past_tickets("query").lower()


def test_search_community_knowledge_handles_http_error() -> None:
    with patch("httpx.get", side_effect=Exception("Connection refused")):
        result = tools.search_community_knowledge("lambda throttling")
    assert isinstance(result, str) and len(result) > 0
