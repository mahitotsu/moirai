from __future__ import annotations

import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

_spec = importlib.util.spec_from_file_location(
    "triage_agent", os.path.join(os.path.dirname(__file__), "..", "agent.py")
)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
with patch("boto3.client", return_value=MagicMock()):
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
sys.modules["triage_agent"] = _mod
agent = _mod


def test_settings_load_defaults() -> None:
    assert "haiku" in agent.MODEL_ID or "claude" in agent.MODEL_ID


def test_system_prompt_is_non_empty() -> None:
    assert len(agent._SYSTEM_PROMPT) > 0
