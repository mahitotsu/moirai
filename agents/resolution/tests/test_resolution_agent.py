from __future__ import annotations

import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("MODEL_ID", "us.anthropic.claude-sonnet-4-6")
os.environ.setdefault("GATEWAY_URL", "http://localhost:8080")

_spec = importlib.util.spec_from_file_location(
    "resolution_agent", os.path.join(os.path.dirname(__file__), "..", "agent.py")
)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
with patch("boto3.client", return_value=MagicMock()):
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
sys.modules["resolution_agent"] = _mod
agent = _mod


def test_settings_gateway_url_loaded() -> None:
    assert agent._settings.gateway_url == "http://localhost:8080"


def test_system_prompt_is_non_empty() -> None:
    assert len(agent._SYSTEM_PROMPT) > 0
