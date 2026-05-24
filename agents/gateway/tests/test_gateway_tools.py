from __future__ import annotations

import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock, patch

_spec = importlib.util.spec_from_file_location(
    "gateway_tools", os.path.join(os.path.dirname(__file__), "..", "tools.py")
)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
with patch("boto3.client", return_value=MagicMock()):
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
sys.modules["gateway_tools"] = _mod
tools = _mod


def _sse(task: dict) -> bytes:
    return f"data: {json.dumps({'result': task})}\n".encode()


def test_parse_a2a_response_extracts_artifact_text() -> None:
    task = {"artifacts": [{"parts": [{"kind": "text", "text": "Resolution plan."}]}]}
    assert tools._parse_a2a_response(_sse(task)) == "Resolution plan."


def test_parse_a2a_response_falls_back_to_history() -> None:
    task = {"artifacts": [], "history": [
        {"role": "user", "parts": [{"kind": "text", "text": "q"}]},
        {"role": "agent", "parts": [{"kind": "text", "text": "agent answer"}]},
    ]}
    assert tools._parse_a2a_response(_sse(task)) == "agent answer"


def test_parse_a2a_response_returns_last_sse_event() -> None:
    def _wrap(t: str) -> str:
        return json.dumps({"result": {"artifacts": [{"parts": [{"kind": "text", "text": t}]}]}})
    body = f"data: {_wrap('first')}\ndata: {_wrap('second')}\n".encode()
    assert tools._parse_a2a_response(body) == "second"


def test_parse_a2a_response_handles_plain_json() -> None:
    assert tools._parse_a2a_response(json.dumps({"response": "plain"}).encode()) == "plain"


def test_parse_a2a_response_handles_empty_body() -> None:
    assert tools._parse_a2a_response(b"") == "No response from agent."


def test_run_triage_returns_fallback_json_when_agent_not_found() -> None:
    with patch.object(tools, "_find_agent_arn", return_value=None):
        data = json.loads(tools.run_triage("DB error"))
    assert data["severity"] == "medium"
    assert data["category"] == "other"


def test_run_diagnosis_returns_error_when_agent_not_found() -> None:
    with patch.object(tools, "_find_agent_arn", return_value=None):
        assert "not available" in tools.run_diagnosis("timeout", ["dynamo"])


def test_run_resolution_instructs_update_existing_ticket() -> None:
    captured: list[str] = []

    def _fake_invoke(arn: str, message: str) -> str:
        captured.append(message)
        return "ok"

    arn = "arn:aws:bedrock-agentcore:::runtime/r"
    with (
        patch.object(tools, "_find_agent_arn", return_value=arn),
        patch.object(tools, "_invoke_a2a_agent", side_effect=_fake_invoke),
    ):
        tools.run_resolution("DB down", '{"severity":"high"}', "Findings.", "t-99")
    assert "t-99" in captured[0]
    assert "Do NOT create a new ticket" in captured[0]


def test_run_resolution_instructs_create_when_no_ticket_id() -> None:
    captured: list[str] = []

    def _fake_invoke(arn: str, message: str) -> str:
        captured.append(message)
        return "ok"

    arn = "arn:aws:bedrock-agentcore:::runtime/r"
    with (
        patch.object(tools, "_find_agent_arn", return_value=arn),
        patch.object(tools, "_invoke_a2a_agent", side_effect=_fake_invoke),
    ):
        tools.run_resolution("DB down", '{"severity":"high"}', "Findings.", "")
    assert "create_ticket" in captured[0]
