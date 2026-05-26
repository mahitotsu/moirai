"""
AgentCore Registry discovery utility.

Agents use this module to find the MCP Gateway URL and A2A agent runtime ARNs
by querying the AgentCore Registry ('agora_registry').

All lookups are cached at the module level so Registry API calls happen only
once per container lifetime.

Example:
    from registry import get_mcp_gateway_url, get_agent_runtime_arn
    from registry import TRIAGE_AGENT_RECORD, DIAGNOSIS_AGENT_RECORD, RESOLUTION_AGENT_RECORD

    url = get_mcp_gateway_url()
    arn = get_agent_runtime_arn(TRIAGE_AGENT_RECORD)
"""

from __future__ import annotations

import json
import logging

import boto3

_bedrock_agent = boto3.client("bedrock-agent")

logger = logging.getLogger(__name__)

REGISTRY_NAME = "agora_registry"
_ACTIVE_STATUSES = {"DRAFT", "APPROVED"}

# Registry record names — must match registry_catalog_handler.py
MCP_GATEWAY_RECORD = "agora-mcp-gateway"
TRIAGE_AGENT_RECORD = "agora-triage-agent"
DIAGNOSIS_AGENT_RECORD = "agora-diagnosis-agent"
RESOLUTION_AGENT_RECORD = "agora-resolution-agent"

_control = boto3.client("bedrock-agentcore-control")

# Module-level cache: persists across invocations in the same container.
_cache: dict[str, object] = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _registry_id() -> str:
    if "_registry_id" not in _cache:
        resp = _control.list_registries()
        for reg in resp.get("registries", []):
            if reg["name"] == REGISTRY_NAME and reg["status"] == "READY":
                _cache["_registry_id"] = reg["registryId"]
                return _cache["_registry_id"]  # type: ignore[return-value]
        raise RuntimeError(f"Registry '{REGISTRY_NAME}' not found or not READY")
    return _cache["_registry_id"]  # type: ignore[return-value]


def _list_all_records(descriptor_type: str) -> list[dict]:
    registry_id = _registry_id()
    records: list[dict] = []
    kwargs: dict = {"registryId": registry_id, "descriptorType": descriptor_type}
    while True:
        resp = _control.list_registry_records(**kwargs)
        records.extend(resp.get("registryRecords", []))
        token = resp.get("nextToken")
        if not token:
            break
        kwargs["nextToken"] = token
    return records


def _get_mcp_inline(record: dict) -> dict | None:
    try:
        detail = _control.get_registry_record(
            registryId=_registry_id(), recordId=record["recordId"]
        )
        descriptors = detail.get("descriptors", {})
        raw = descriptors.get("mcp", {}).get("server", {}).get("inlineContent", "{}")
        return json.loads(raw)
    except Exception:
        return None


def _get_a2a_inline(record: dict) -> dict | None:
    try:
        detail = _control.get_registry_record(
            registryId=_registry_id(), recordId=record["recordId"]
        )
        descriptors = detail.get("descriptors", {})
        raw = descriptors.get("a2a", {}).get("agentCard", {}).get("inlineContent", "{}")
        return json.loads(raw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_mcp_gateway_url() -> str:
    """Return the MCP Gateway URL. Fetches from Registry on first call, then cached."""
    cache_key = "mcp_gateway_url"
    if cache_key not in _cache:
        for rec in _list_all_records("MCP"):
            if rec["name"] == MCP_GATEWAY_RECORD:
                content = _get_mcp_inline(rec)
                if content:
                    url = content.get("url", "")
                    if url:
                        _cache[cache_key] = url
                        logger.info("Discovered MCP Gateway URL from Registry")
                        return url  # type: ignore[return-value]
        raise RuntimeError(f"Registry record '{MCP_GATEWAY_RECORD}' not found or URL missing")
    return _cache[cache_key]  # type: ignore[return-value]


def get_agent_runtime_arn(record_name: str) -> str:
    """Return the runtimeArn for a registered agent. Fetches from Registry on first call."""
    cache_key = f"arn:{record_name}"
    if cache_key not in _cache:
        for rec in _list_all_records("A2A"):
            if rec["name"] == record_name:
                content = _get_a2a_inline(rec)
                if content:
                    arn = content.get("runtimeArn", "")
                    if arn:
                        _cache[cache_key] = arn
                        logger.info("Discovered runtime ARN for '%s' from Registry", record_name)
                        return arn  # type: ignore[return-value]
        raise RuntimeError(f"Registry record '{record_name}' not found or runtimeArn missing")
    return _cache[cache_key]  # type: ignore[return-value]


def discover_by_capability(capability: str) -> list[dict]:
    """Return all MCP servers tagged with the given capability.

    Each entry has: name, runtime_arn, runtime_id, endpoint_id.
    """
    results: list[dict] = []
    for rec in _list_all_records("MCP"):
        if rec.get("status") not in _ACTIVE_STATUSES:
            continue
        content = _get_mcp_inline(rec)
        if not content or content.get("capability") != capability:
            continue
        runtime_arn = content.get("runtimeArn", "")
        results.append({
            "name": content.get("runtimeName", rec["name"]),
            "runtime_arn": runtime_arn,
            "runtime_id": runtime_arn.split("/")[-1] if runtime_arn else "",
            "endpoint_id": content.get("endpointId", ""),
        })
    return results


def fetch_system_prompt(arn: str) -> str:
    """Fetch prompt text from Bedrock Prompt Management by ARN.

    Fetches the default variant's text template. Raises RuntimeError on failure.
    Module-level cache ensures at most one API call per container lifetime.
    """
    cache_key = f"prompt:{arn}"
    if cache_key not in _cache:
        resp = _bedrock_agent.get_prompt(promptIdentifier=arn)
        variants = resp.get("variants", [])
        if not variants:
            raise RuntimeError(f"No variants found for prompt ARN: {arn}")
        text = variants[0]["templateConfiguration"]["text"]["text"]
        _cache[cache_key] = text
        logger.info("Fetched system prompt from Bedrock Prompt Management: %s", arn)
    return _cache[cache_key]  # type: ignore[return-value]


def discover_a2a_agents() -> list[dict]:
    """Return all A2A agents with capability='a2a-agent'.

    Each entry has: name, agent_type, runtime_arn, runtime_id, endpoint_id.
    """
    results: list[dict] = []
    for rec in _list_all_records("A2A"):
        if rec.get("status") not in _ACTIVE_STATUSES:
            continue
        content = _get_a2a_inline(rec)
        if not content or content.get("capability") != "a2a-agent":
            continue
        runtime_arn = content.get("runtimeArn", "")
        results.append({
            "name": content.get("name", rec["name"]),
            "agent_type": content.get("agentType", "unknown"),
            "runtime_arn": runtime_arn,
            "runtime_id": runtime_arn.split("/")[-1] if runtime_arn else "",
            "endpoint_id": content.get("endpointId", ""),
        })
    return results
