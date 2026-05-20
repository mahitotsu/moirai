from __future__ import annotations

from pathlib import Path

from bedrock_agentcore.runtime import serve_a2a
from pydantic_settings import BaseSettings
from strands import Agent
from strands.models import BedrockModel, CacheConfig
from strands.multiagent.a2a.executor import StrandsA2AExecutor
from tools import check_cloudwatch_alarms, search_community_knowledge, search_past_tickets


class _Settings(BaseSettings):
    model_id: str = "us.anthropic.claude-sonnet-4-6"


MODEL_ID = _Settings().model_id
_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()


def _create_agent() -> Agent:
    return Agent(
        model=BedrockModel(
            model_id=MODEL_ID,
            cache_config=CacheConfig(strategy="auto"),
        ),
        system_prompt=_SYSTEM_PROMPT,
        tools=[search_community_knowledge, search_past_tickets, check_cloudwatch_alarms],
    )


if __name__ == "__main__":
    serve_a2a(StrandsA2AExecutor(_create_agent()))
