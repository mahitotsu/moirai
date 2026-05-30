from __future__ import annotations

import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("SYSTEM_PROMPT_ARN", "arn:aws:bedrock:us-east-1:123456789012:prompt/dummy")

_registry_mock = MagicMock()
_registry_mock.fetch_system_prompt.return_value = (
    "You are the Pipeline Orchestrator. Execute Triage, Diagnosis, and Resolution in sequence."
)
sys.modules["registry"] = _registry_mock

_spec = importlib.util.spec_from_file_location(
    "orchestrator_agent", os.path.join(os.path.dirname(__file__), "..", "agent.py")
)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
with patch("boto3.client", return_value=MagicMock()):
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
sys.modules["orchestrator_agent"] = _mod


def test_system_prompt_is_non_empty() -> None:
    assert len(_mod._SYSTEM_PROMPT) > 50


def test_system_prompt_describes_pipeline() -> None:
    prompt = _mod._SYSTEM_PROMPT
    assert "Triage" in prompt
    assert "Diagnosis" in prompt
    assert "Resolution" in prompt


def test_invoke_triage_tool_is_defined() -> None:
    assert callable(_mod.invoke_triage)


def test_invoke_diagnosis_tool_is_defined() -> None:
    assert callable(_mod.invoke_diagnosis)


def test_invoke_resolution_tool_is_defined() -> None:
    assert callable(_mod.invoke_resolution)


def test_entrypoint_returns_immediately() -> None:
    """invoke() は add_async_task を呼び出してすぐに返す（ブロックしない）。"""
    mock_app = _mod.app
    original_add = mock_app.add_async_task
    called: list[str] = []

    def fake_add(name: str) -> str:
        called.append(name)
        return "fake-task-id"

    mock_app.add_async_task = fake_add
    try:
        result = _mod.invoke({"prompt": "test incident"}, None)
        assert "response" in result
        assert len(called) == 1
        assert called[0] == "pipeline"
    finally:
        mock_app.add_async_task = original_add
