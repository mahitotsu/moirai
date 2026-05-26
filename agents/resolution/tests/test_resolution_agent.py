from __future__ import annotations

import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("MODEL_ID", "us.anthropic.claude-sonnet-4-6")
os.environ.setdefault("SYSTEM_PROMPT_ARN", "arn:aws:bedrock:us-east-1:123456789012:prompt/dummy")

# registry モジュールは Registry API が必要なため、テストではスタブ化する
_registry_mock = MagicMock()
_registry_mock.fetch_system_prompt.return_value = (
    "You are the Resolution Agent. Generate resolution steps."
)
sys.modules["registry"] = _registry_mock

_spec = importlib.util.spec_from_file_location(
    "resolution_agent", os.path.join(os.path.dirname(__file__), "..", "agent.py")
)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
with patch("boto3.client", return_value=MagicMock()):
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
sys.modules["resolution_agent"] = _mod
agent = _mod


def test_settings_load_defaults() -> None:
    assert "sonnet" in agent._settings.model_id or "claude" in agent._settings.model_id


def test_system_prompt_is_non_empty() -> None:
    assert len(agent._SYSTEM_PROMPT) > 0
