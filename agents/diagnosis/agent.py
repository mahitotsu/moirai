from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

import boto3
import botocore.auth
import botocore.awsrequest
import httpx
import registry
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from strands import Agent
from strands.models import BedrockModel, CacheConfig
from strands.multiagent import GraphBuilder
from strands.tools.mcp import MCPClient
from strands.vended_plugins.skills.agent_skills import AgentSkills


class _Settings(BaseSettings):
    model_id: str = "us.anthropic.claude-sonnet-4-6"
    system_prompt_arn: str = ""
    judgment_prompt_arn: str = ""


_settings = _Settings()
if not _settings.system_prompt_arn:
    raise RuntimeError("SYSTEM_PROMPT_ARN must be set")
if not _settings.judgment_prompt_arn:
    raise RuntimeError("JUDGMENT_PROMPT_ARN must be set")

_DIAGNOSIS_PROMPT = registry.fetch_system_prompt(_settings.system_prompt_arn)
_JUDGMENT_PROMPT = registry.fetch_system_prompt(_settings.judgment_prompt_arn)

app = BedrockAgentCoreApp()


class _AwsSigV4Auth(httpx.Auth):
    """httpx.Auth の SigV4 実装。Registry MCP エンドポイントの IAM 認証に使用。"""

    def __init__(self, service: str, region: str) -> None:
        self._service = service
        self._region = region
        credentials = boto3.Session().get_credentials()
        if credentials is None:
            raise RuntimeError("AWS credentials not found")
        self._credentials = credentials

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        frozen = self._credentials.get_frozen_credentials()
        aws_request = botocore.awsrequest.AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers={k: v for k, v in request.headers.items()},
        )
        botocore.auth.SigV4Auth(frozen, self._service, self._region).add_auth(aws_request)
        for key, value in aws_request.headers.items():
            request.headers[key] = value
        yield request


_region = boto3.Session().region_name or "us-east-1"
_registry_mcp_url = registry.get_registry_mcp_url()
_registry_sigv4 = _AwsSigV4Auth("bedrock-agentcore", _region)


class _RunbookSelection(BaseModel):
    runbook_names: list[str]
    reason: str


class _RootCause(BaseModel):
    description: str
    evidence: str
    confidence: str


class _SimilarIncident(BaseModel):
    ticket_id: str
    description: str
    resolution: str


class DiagnosisResult(BaseModel):
    runbook: str
    root_causes: list[_RootCause]
    search_results_summary: str
    similar_past_incidents: list[_SimilarIncident]
    recommended_actions: list[str]
    overall_confidence: str


def _make_diagnosis_agent(skill: object, mcp_url: str) -> Agent:
    mcp = MCPClient(
        lambda: streamablehttp_client(mcp_url),
        startup_timeout=60,
    )
    return Agent(
        model=BedrockModel(
            model_id=_settings.model_id,
            cache_config=CacheConfig(strategy="auto"),
        ),
        system_prompt=_DIAGNOSIS_PROMPT,
        tools=[mcp],
        plugins=[AgentSkills(skills=[skill])],  # type: ignore[list-item]
        structured_output_model=DiagnosisResult,
    )


@app.entrypoint
def invoke(payload: dict[str, Any], context: Any) -> dict[str, str]:
    message = payload.get("message", payload.get("prompt", ""))

    # Agent 1: ランブック判定（Registry MCP で search_registry_records を呼ぶ）
    registry_mcp = MCPClient(
        lambda: streamablehttp_client(_registry_mcp_url, auth=_registry_sigv4),
        startup_timeout=60,
    )
    judgment_agent = Agent(
        model=BedrockModel(model_id=_settings.model_id),
        system_prompt=_JUDGMENT_PROMPT,
        tools=[registry_mcp],
        structured_output_model=_RunbookSelection,
    )
    judgment_result = judgment_agent(message)
    selection: _RunbookSelection = judgment_result.structured_output  # type: ignore[assignment]

    # 選択されたランブックの本文を Registry から取得
    skills = [
        s for name in selection.runbook_names
        if (s := registry.fetch_skill_by_name(name.removeprefix("agora-")))
    ]

    # Agent 2+: ランブック毎に Graph で並列診断
    mcp_url = registry.get_mcp_gateway_url()
    builder = GraphBuilder()
    node_ids = [f"diagnosis_{i}" for i in range(len(skills))]
    for node_id, skill in zip(node_ids, skills):
        builder.add_node(_make_diagnosis_agent(skill, mcp_url), node_id)

    graph = builder.build()
    graph_result = graph(message)

    results: list[DiagnosisResult] = []
    for nid in node_ids:
        if nid not in graph_result.results:
            continue
        node_result = graph_result.results[nid].result
        if isinstance(node_result, Exception):
            continue
        output = node_result.structured_output  # type: ignore[union-attr]
        if isinstance(output, DiagnosisResult):
            results.append(output)

    return {"response": json.dumps([r.model_dump() for r in results])}


if __name__ == "__main__":
    app.run()
