from __future__ import annotations

import importlib.util
import os
import sys

_TEST_GATEWAY_URL = "https://example.com/mcp"

# Save original env values, set test values, then restore after module load
# to avoid polluting env for other test modules loaded in the same process.
_orig_gateway_url = os.environ.get("GATEWAY_URL")
_orig_guardrail_id = os.environ.get("GUARDRAIL_ID")
os.environ["GATEWAY_URL"] = _TEST_GATEWAY_URL
os.environ.setdefault("GUARDRAIL_ID", "")

_spec = importlib.util.spec_from_file_location(
    "gateway_agent", os.path.join(os.path.dirname(__file__), "..", "agent.py")
)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
sys.modules["gateway_agent"] = _mod

# Restore
if _orig_gateway_url is None:
    os.environ.pop("GATEWAY_URL", None)
else:
    os.environ["GATEWAY_URL"] = _orig_gateway_url
if _orig_guardrail_id is None:
    os.environ.pop("GUARDRAIL_ID", None)


def test_settings_gateway_url_loaded() -> None:
    assert _mod._settings.gateway_url == _TEST_GATEWAY_URL


def test_system_prompt_is_non_empty() -> None:
    assert len(_mod._SYSTEM_PROMPT) > 100


def test_system_prompt_describes_pipeline() -> None:
    prompt = _mod._SYSTEM_PROMPT
    assert "Triage" in prompt
    assert "Diagnosis" in prompt
    assert "Resolution" in prompt
