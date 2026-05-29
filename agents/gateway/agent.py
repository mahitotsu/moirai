from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import boto3
import registry
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp.client.streamable_http import streamablehttp_client
from pydantic_settings import BaseSettings
from strands import Agent, tool
from strands.models import BedrockModel, CacheConfig
from strands.tools.mcp import MCPClient

logger = logging.getLogger(__name__)


class _Settings(BaseSettings):
    model_id: str = "us.anthropic.claude-sonnet-4-6"
    guardrail_id: str = ""
    guardrail_version: str = "DRAFT"
    system_prompt_arn: str = ""


_settings = _Settings()
if not _settings.system_prompt_arn:
    raise RuntimeError("SYSTEM_PROMPT_ARN must be set")
_SYSTEM_PROMPT = registry.fetch_system_prompt(_settings.system_prompt_arn)

_agentcore = boto3.client("bedrock-agentcore")
app = BedrockAgentCoreApp()


# ---------------------------------------------------------------------------
# サブエージェント呼び出しヘルパー — Strandsツールとして呼び出される
# ---------------------------------------------------------------------------


def _invoke_sub_agent(runtime_arn: str, message: str) -> str:
    """InvokeAgentRuntime経由でHTTPプロトコルのサブエージェントを呼び出し、レスポンスを返す。"""
    payload = json.dumps({"message": message}).encode()
    resp = _agentcore.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        qualifier="DEFAULT",
        payload=payload,
        runtimeSessionId=str(uuid.uuid4()),
    )
    body: bytes = resp["response"].read()
    try:
        data = json.loads(body)
        return data.get("response", body.decode())
    except Exception:
        return body.decode()


@tool
def invoke_triage(incident_description: str) -> str:
    """ITインシデントを重要度とカテゴリで分類し、診断用の検索キーワードを生成する。

    Args:
        incident_description: 分類対象のITインシデントの完全な説明。

    Returns:
        重要度、カテゴリ、推奨検索キーワードを含むトリアージ結果。
    """
    arn = registry.get_agent_runtime_arn(registry.TRIAGE_AGENT_RECORD)
    return _invoke_sub_agent(arn, incident_description)


@tool
def invoke_diagnosis(triage_result: str) -> str:
    """コミュニティナレッジ、CloudWatchアラーム、過去チケットを検索してインシデントを診断する。

    Args:
        triage_result: トリアージ分類アウトプット（重要度、カテゴリ、検索キーワード）。

    Returns:
        推定根本原因と関連ナレッジソースを含む診断結果。
    """
    arn = registry.get_agent_runtime_arn(registry.DIAGNOSIS_AGENT_RECORD)
    return _invoke_sub_agent(arn, triage_result)


@tool
def invoke_resolution(diagnosis_result: str, ticket_id: str = "") -> str:
    """解決策を立案し、インシデントチケットを更新（または作成）する。

    Args:
        diagnosis_result: 解決策立案の根拠となる診断結果。
        ticket_id: 更新する既存チケットID。省略すると新規チケットを作成する。

    Returns:
        解決策とチケットの更新または作成の確認。
    """
    arn = registry.get_agent_runtime_arn(registry.RESOLUTION_AGENT_RECORD)
    message = diagnosis_result
    if ticket_id:
        message = f"{diagnosis_result}\n\nExisting ticket ID to update: {ticket_id}"
    return _invoke_sub_agent(arn, message)


@app.entrypoint
def invoke(payload: dict[str, Any], context: Any) -> dict[str, str]:
    prompt = payload.get("prompt", payload.get("message", ""))

    mcp_url = registry.get_mcp_gateway_url()
    mcp = MCPClient(
        lambda: streamablehttp_client(mcp_url),
        startup_timeout=60,
    )

    model_kwargs: dict = {
        "model_id": _settings.model_id,
        "cache_config": CacheConfig(strategy="auto"),
    }
    if _settings.guardrail_id:
        model_kwargs["guardrail_id"] = _settings.guardrail_id
        model_kwargs["guardrail_version"] = _settings.guardrail_version

    agent = Agent(
        model=BedrockModel(**model_kwargs),
        system_prompt=_SYSTEM_PROMPT,
        tools=[mcp, invoke_triage, invoke_diagnosis, invoke_resolution],
    )
    result = agent(prompt)
    return {"response": str(result)}


if __name__ == "__main__":
    app.run()
