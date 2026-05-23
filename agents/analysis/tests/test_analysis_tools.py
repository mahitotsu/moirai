from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

os.environ.setdefault("TICKETS_TABLE", "agora-test-tickets")
os.environ.setdefault("REPORTS_TABLE", "agora-test-reports")
os.environ.setdefault("AWS_REGION", "us-east-1")

_spec = importlib.util.spec_from_file_location(
    "analysis_tools", os.path.join(os.path.dirname(__file__), "..", "tools.py")
)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
with patch("boto3.client", return_value=MagicMock()):
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
sys.modules["analysis_tools"] = _mod
tools = _mod


def _dynamo_item(**fields: str) -> dict:
    return {k: {"S": v} for k, v in fields.items()}


def test_get_ticket_stats_returns_counts() -> None:
    now = datetime.now(UTC)
    recent = (now - timedelta(days=1)).isoformat()
    mock_resp = {
        "Items": [
            _dynamo_item(ticket_id="t-1", status="open", category="network",
                         severity="high", created_at=recent),
            _dynamo_item(ticket_id="t-2", status="resolved", category="database",
                         severity="low", created_at=recent, resolved_at=recent, title="DB issue"),
        ]
    }
    with patch.object(tools, "_dynamodb") as m:
        m.scan.return_value = mock_resp
        data = json.loads(tools.get_ticket_stats())
    assert data["total_tickets_last_30d"] == 2
    assert data["by_status"]["open"] == 1
    assert data["by_category"]["database"] == 1


def test_get_ticket_stats_excludes_old_tickets() -> None:
    old = (datetime.now(UTC) - timedelta(days=45)).isoformat()
    with patch.object(tools, "_dynamodb") as m:
        m.scan.return_value = {"Items": [
            _dynamo_item(ticket_id="t-old", status="open", category="network",
                         severity="low", created_at=old),
        ]}
        data = json.loads(tools.get_ticket_stats())
    assert data["total_tickets_last_30d"] == 0


def test_get_ticket_stats_on_error() -> None:
    with patch.object(tools, "_dynamodb") as m:
        m.scan.side_effect = Exception("Connection refused")
        assert "failed" in tools.get_ticket_stats().lower()


def test_get_lambda_error_metrics_returns_rates() -> None:
    mock_resp = {"MetricDataResults": [
        {"Id": "errors", "Values": [5.0]},
        {"Id": "invocations", "Values": [100.0]},
    ]}
    with patch.object(tools, "_cloudwatch") as m:
        m.get_metric_data.return_value = mock_resp
        data = json.loads(tools.get_lambda_error_metrics(["my-fn"], hours=24))
    assert data["my-fn"]["error_rate_pct"] == 5.0


def test_get_lambda_error_metrics_zero_invocations() -> None:
    mock_resp = {"MetricDataResults": [
        {"Id": "errors", "Values": [0.0]},
        {"Id": "invocations", "Values": [0.0]},
    ]}
    with patch.object(tools, "_cloudwatch") as m:
        m.get_metric_data.return_value = mock_resp
        data = json.loads(tools.get_lambda_error_metrics(["idle-fn"]))
    assert data["idle-fn"]["error_rate_pct"] == 0.0


def test_get_lambda_error_metrics_on_error() -> None:
    with patch.object(tools, "_cloudwatch") as m:
        m.get_metric_data.side_effect = Exception("Throttled")
        assert "failed" in tools.get_lambda_error_metrics(["fn"]).lower()


def test_get_bedrock_costs_returns_total() -> None:
    mock_resp = {"ResultsByTime": [{"TimePeriod": {"Start": "2026-05-01"}, "Groups": [{
        "Keys": ["USE1-Bedrock:ModelInvocation"],
        "Metrics": {"UnblendedCost": {"Amount": "0.05"}},
    }]}]}
    with patch.object(tools, "_ce") as m:
        m.get_cost_and_usage.return_value = mock_resp
        data = json.loads(tools.get_bedrock_costs(days=7))
    assert data["total_usd"] == 0.05


def test_get_bedrock_costs_clamps_days() -> None:
    with patch.object(tools, "_ce") as m:
        m.get_cost_and_usage.return_value = {"ResultsByTime": []}
        tools.get_bedrock_costs(days=999)
    args = m.get_cost_and_usage.call_args[1]
    start, end = args["TimePeriod"]["Start"], args["TimePeriod"]["End"]
    assert (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days <= 30


def test_get_bedrock_costs_on_error() -> None:
    with patch.object(tools, "_ce") as m:
        m.get_cost_and_usage.side_effect = Exception("AccessDenied")
        assert "failed" in tools.get_bedrock_costs().lower()


def test_save_report_returns_report_id() -> None:
    with patch.object(tools, "_dynamodb") as m:
        m.put_item.return_value = {}
        data = json.loads(tools.save_report("T", "incident-summary", "S", "D"))
    assert "report_id" in data
    m.put_item.assert_called_once()


def test_save_report_normalizes_invalid_type() -> None:
    with patch.object(tools, "_dynamodb") as m:
        m.put_item.return_value = {}
        tools.save_report("T", "invalid-type", "S", "D")
    assert m.put_item.call_args[1]["Item"]["type"]["S"] == "custom"


def test_save_report_on_error() -> None:
    with patch.object(tools, "_dynamodb") as m:
        m.put_item.side_effect = Exception("unavailable")
        assert "failed" in tools.save_report("T", "cost", "S", "D").lower()
