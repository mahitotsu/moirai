from __future__ import annotations

from pathlib import Path

from bedrock_agentcore.runtime import serve_a2a
from strands import Agent
from strands.models import BedrockModel
from strands.multiagent.a2a.executor import StrandsA2AExecutor

MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001"
_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()


def _create_agent() -> Agent:
    return Agent(
        model=BedrockModel(model_id=MODEL_ID, region_name="us-east-1"),
        system_prompt=_SYSTEM_PROMPT,
    )


if __name__ == "__main__":
    serve_a2a(StrandsA2AExecutor(_create_agent()))
