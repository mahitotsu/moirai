from __future__ import annotations

from pathlib import Path

from bedrock_agentcore.runtime import serve_a2a
from mcp.client.streamable_http import streamablehttp_client
from pydantic_settings import BaseSettings
from strands import Agent
from strands.models import BedrockModel, CacheConfig
from strands.multiagent.a2a.executor import StrandsA2AExecutor
from strands.tools.mcp import MCPClient
from tools import search_past_tickets


class _Settings(BaseSettings):
    model_id: str = "us.anthropic.claude-sonnet-4-6"
    gateway_url: str = ""


_settings = _Settings()
_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()


def _create_agent() -> Agent:
    mcp = MCPClient(
        lambda: streamablehttp_client(_settings.gateway_url),
        startup_timeout=60,
    )
    return Agent(
        model=BedrockModel(
            model_id=_settings.model_id,
            cache_config=CacheConfig(strategy="auto"),
        ),
        system_prompt=_SYSTEM_PROMPT,
        tools=[mcp, search_past_tickets],
    )


if __name__ == "__main__":
    serve_a2a(StrandsA2AExecutor(_create_agent()))
