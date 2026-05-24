from __future__ import annotations

from pathlib import Path
from typing import Any

import registry
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp.client.streamable_http import streamablehttp_client
from pydantic_settings import BaseSettings
from strands import Agent
from strands.models import BedrockModel, CacheConfig
from strands.tools.mcp import MCPClient
from tools import search_past_tickets


class _Settings(BaseSettings):
    model_id: str = "us.anthropic.claude-sonnet-4-6"


_settings = _Settings()
_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict[str, Any], context: Any) -> dict[str, str]:
    message = payload.get("message", payload.get("prompt", ""))

    mcp_url = registry.get_mcp_gateway_url()
    mcp = MCPClient(
        lambda: streamablehttp_client(mcp_url),
        startup_timeout=60,
    )

    agent = Agent(
        model=BedrockModel(
            model_id=_settings.model_id,
            cache_config=CacheConfig(strategy="auto"),
        ),
        system_prompt=_SYSTEM_PROMPT,
        tools=[mcp, search_past_tickets],
    )
    result = agent(message)
    return {"response": str(result)}


if __name__ == "__main__":
    app.run()
