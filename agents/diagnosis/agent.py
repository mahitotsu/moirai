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
from tools import search_past_tickets


class _Settings(BaseSettings):
    model_id: str = "us.anthropic.claude-sonnet-4-6"
    system_prompt_arn: str = ""


_settings = _Settings()
if not _settings.system_prompt_arn:
    raise RuntimeError("SYSTEM_PROMPT_ARN must be set")
_SYSTEM_PROMPT = registry.fetch_system_prompt(_settings.system_prompt_arn)

app = BedrockAgentCoreApp()


class _RootCause(BaseModel):
    description: str
    evidence: str
    confidence: str


class _SimilarIncident(BaseModel):
    ticket_id: str
    description: str
    resolution: str


class DiagnosisResult(BaseModel):
    root_causes: list[_RootCause]
    search_results_summary: str
    similar_past_incidents: list[_SimilarIncident]
    recommended_actions: list[str]
    overall_confidence: str


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
    result = agent.structured_output(DiagnosisResult, message)
    return {"response": result.model_dump_json()}


if __name__ == "__main__":
    app.run()
