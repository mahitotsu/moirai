from __future__ import annotations

from typing import Any

import registry
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from strands import Agent
from strands.models import BedrockModel, CacheConfig
from strands.vended_plugins.skills.agent_skills import AgentSkills


class _Settings(BaseSettings):
    model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    system_prompt_arn: str = ""


_settings = _Settings()
if not _settings.system_prompt_arn:
    raise RuntimeError("SYSTEM_PROMPT_ARN must be set")
_SYSTEM_PROMPT = registry.fetch_system_prompt(_settings.system_prompt_arn)
_SKILLS = registry.discover_skills(["incident-severity-classification"])

app = BedrockAgentCoreApp()


class TriageResult(BaseModel):
    severity: str
    category: str
    summary: str
    affected_components: list[str]
    suggested_search_terms: list[str]


@app.entrypoint
def invoke(payload: dict[str, Any], context: Any) -> dict[str, str]:
    message = payload.get("message", payload.get("prompt", ""))

    plugins = [AgentSkills(skills=_SKILLS)] if _SKILLS else []
    agent = Agent(
        model=BedrockModel(
            model_id=_settings.model_id,
            cache_config=CacheConfig(strategy="auto"),
        ),
        system_prompt=_SYSTEM_PROMPT,
        plugins=plugins,
    )
    result = agent.structured_output(TriageResult, message)
    return {"response": result.model_dump_json()}


if __name__ == "__main__":
    app.run()
