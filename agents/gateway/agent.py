from __future__ import annotations

from pathlib import Path
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic_settings import BaseSettings
from strands import Agent
from strands.models import BedrockModel, CacheConfig
from tools import run_analysis, run_diagnosis, run_resolution, run_triage


class _Settings(BaseSettings):
    model_id: str = "us.anthropic.claude-sonnet-4-6"
    guardrail_id: str = ""
    guardrail_version: str = "DRAFT"


_s = _Settings()
MODEL_ID = _s.model_id

_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict[str, Any], context: Any) -> dict[str, str]:
    prompt = payload.get("prompt", payload.get("message", ""))

    model_kwargs: dict = {
        "model_id": MODEL_ID,
        "cache_config": CacheConfig(strategy="auto"),
    }
    if _s.guardrail_id:
        model_kwargs["guardrail_id"] = _s.guardrail_id
        model_kwargs["guardrail_version"] = _s.guardrail_version
    agent = Agent(
        model=BedrockModel(**model_kwargs),
        system_prompt=_SYSTEM_PROMPT,
        tools=[run_triage, run_diagnosis, run_resolution, run_analysis],
    )
    result = agent(prompt)
    return {"response": str(result)}


if __name__ == "__main__":
    app.run()
