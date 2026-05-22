from __future__ import annotations

from pathlib import Path

from bedrock_agentcore.runtime import serve_a2a
from pydantic_settings import BaseSettings
from strands import Agent
from strands.models import BedrockModel, CacheConfig
from strands.multiagent.a2a.executor import StrandsA2AExecutor
from tools import get_bedrock_costs, get_lambda_error_metrics, get_ticket_stats, save_report


class _Settings(BaseSettings):
    model_id: str = "us.anthropic.claude-sonnet-4-6"


_settings = _Settings()
_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()


def _create_agent() -> Agent:
    return Agent(
        model=BedrockModel(
            model_id=_settings.model_id,
            cache_config=CacheConfig(strategy="auto"),
        ),
        system_prompt=_SYSTEM_PROMPT,
        tools=[get_ticket_stats, get_lambda_error_metrics, get_bedrock_costs, save_report],
    )


if __name__ == "__main__":
    serve_a2a(StrandsA2AExecutor(_create_agent()))
