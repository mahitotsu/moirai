from __future__ import annotations

from pathlib import Path
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp.client.streamable_http import streamablehttp_client
from pydantic_settings import BaseSettings
from strands import Agent
from strands.models import BedrockModel, CacheConfig
from strands.tools.mcp import MCPClient


class _Settings(BaseSettings):
    model_id: str = "us.anthropic.claude-sonnet-4-6"
    gateway_url: str = ""
    guardrail_id: str = ""
    guardrail_version: str = "DRAFT"


_settings = _Settings()
_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict[str, Any], context: Any) -> dict[str, str]:
    prompt = payload.get("prompt", payload.get("message", ""))

    mcp = MCPClient(
        lambda: streamablehttp_client(_settings.gateway_url),
        startup_timeout=60,
    )

    model_kwargs: dict = {
        "model_id": _settings.model_id,
        "cache_config": CacheConfig(strategy="auto"),
    }
    if _settings.guardrail_id:
        model_kwargs["guardrail_id"] = _settings.guardrail_id
        model_kwargs["guardrail_version"] = _settings.guardrail_version

    agent = Agent(
        model=BedrockModel(**model_kwargs),
        system_prompt=_SYSTEM_PROMPT,
        tools=[mcp],
    )
    result = agent(prompt)
    return {"response": str(result)}


if __name__ == "__main__":
    app.run()
