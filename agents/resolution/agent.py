from __future__ import annotations

from typing import Any

import registry
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from strands import Agent
from strands.models import BedrockModel, CacheConfig
from strands.tools.mcp import MCPClient
from strands.vended_plugins.skills.agent_skills import AgentSkills


class _Settings(BaseSettings):
    model_id: str = "us.anthropic.claude-sonnet-4-6"
    system_prompt_arn: str = ""


_settings = _Settings()
if not _settings.system_prompt_arn:
    raise RuntimeError("SYSTEM_PROMPT_ARN must be set")
_SYSTEM_PROMPT = registry.fetch_system_prompt(_settings.system_prompt_arn)
_SKILLS = registry.discover_skills([
    "resolution-documentation-standard",
    "incident-severity-classification",
])

app = BedrockAgentCoreApp()


class ResolutionResult(BaseModel):
    root_cause_summary: str
    resolution_steps: list[str]
    preventive_measures: list[str]
    lesson_learned: str
    estimated_time_minutes: int
    ticket_id: str | None


@app.entrypoint
def invoke(payload: dict[str, Any], context: Any) -> dict[str, str]:
    message = payload.get("message", payload.get("prompt", ""))

    mcp_url = registry.get_mcp_gateway_url()
    mcp = MCPClient(
        lambda: streamablehttp_client(mcp_url),
        startup_timeout=60,
    )

    plugins = [AgentSkills(skills=_SKILLS)] if _SKILLS else []
    agent = Agent(
        model=BedrockModel(
            model_id=_settings.model_id,
            cache_config=CacheConfig(strategy="auto"),
        ),
        system_prompt=_SYSTEM_PROMPT,
        tools=[mcp],
        plugins=plugins,  # type: ignore[arg-type]
    )
    result = agent(message, structured_output_model=ResolutionResult)
    output: ResolutionResult = result.structured_output  # type: ignore[assignment]
    return {"response": output.model_dump_json()}


if __name__ == "__main__":
    app.run()
