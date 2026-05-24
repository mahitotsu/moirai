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


# ---------------------------------------------------------------------------
# search_past_tickets
# ---------------------------------------------------------------------------

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
