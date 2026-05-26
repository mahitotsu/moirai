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
# Sub-agent invocation helpers — called as Strands tools
# ---------------------------------------------------------------------------


def _invoke_sub_agent(runtime_arn: str, message: str) -> str:
    """Call an HTTP-protocol sub-agent via InvokeAgentRuntime and return its response."""
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
    """Classify an IT incident by severity and category, and generate search terms for diagnosis.

    Args:
        incident_description: Full description of the IT incident to be classified.

    Returns:
        Triage result including severity, category, and suggested search terms.
    """
    arn = registry.get_agent_runtime_arn(registry.TRIAGE_AGENT_RECORD)
    return _invoke_sub_agent(arn, incident_description)


@tool
def invoke_diagnosis(triage_result: str) -> str:
    """Search community knowledge, CloudWatch alarms, and past tickets to diagnose an incident.

    Args:
        triage_result: The triage classification output (severity, category, search terms).

    Returns:
        Diagnosis findings including probable root causes and relevant knowledge sources.
    """
    arn = registry.get_agent_runtime_arn(registry.DIAGNOSIS_AGENT_RECORD)
    return _invoke_sub_agent(arn, triage_result)


@tool
def invoke_resolution(diagnosis_result: str, ticket_id: str = "") -> str:
    """Generate a resolution plan and update (or create) the incident ticket.

    Args:
        diagnosis_result: The diagnosis findings to base the resolution plan on.
        ticket_id: Existing ticket ID to update. Omit to create a new ticket.

    Returns:
        Resolution plan and confirmation of the ticket update or creation.
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
