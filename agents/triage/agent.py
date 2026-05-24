from __future__ import annotations

from pathlib import Path
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic_settings import BaseSettings
from strands import Agent
from strands.models import BedrockModel, CacheConfig


class _Settings(BaseSettings):
    model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


_settings = _Settings()
_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict[str, Any], context: Any) -> dict[str, str]:
    message = payload.get("message", payload.get("prompt", ""))

    agent = Agent(
        model=BedrockModel(
            model_id=_settings.model_id,
            cache_config=CacheConfig(strategy="auto"),
        ),
        system_prompt=_SYSTEM_PROMPT,
    )
    result = agent(message)
    return {"response": str(result)}


if __name__ == "__main__":
    app.run()
