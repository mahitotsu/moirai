"""
AgentCore Registry discovery utility.

Agents use this module to find MCP servers and A2A agents by querying the
AgentCore Registry ('agora_registry').  Records are stored with proper
protocol types (MCP / A2A) and carry runtime discovery metadata as
additional fields in their inline content.

Example:
    from common.registry import discover_by_capability, discover_a2a_agents

    runtimes = discover_by_capability("community-knowledge")
    # [{"name": "agora_stackoverflow", "runtime_arn": "...",
    #   "runtime_id": "...", "endpoint_id": "...", "endpoint_arn": ""}, ...]

    agents = discover_a2a_agents()
    # [{"name": "Triage Agent", "agent_type": "triage", "runtime_arn": "...",
    #   "runtime_id": "...", "endpoint_id": "...", "endpoint_arn": ""}, ...]
"""

from __future__ import annotations

import json

import boto3

REGION = "us-east-1"
REGISTRY_NAME = "agora_registry"
_ACTIVE_STATUSES = {"DRAFT", "APPROVED"}


def _find_registry_id(control) -> str | None:
    resp = control.list_registries()
    for reg in resp.get("registries", []):
        if reg["name"] == REGISTRY_NAME and reg["status"] == "READY":
            return reg["registryId"]
    return None


def _list_all_records(control, registry_id: str, descriptor_type: str) -> list[dict]:
    records: list[dict] = []
    kwargs: dict = {"registryId": registry_id, "descriptorType": descriptor_type}
    while True:
        resp = control.list_registry_records(**kwargs)
        records.extend(resp.get("registryRecords", []))
        token = resp.get("nextToken")
        if not token:
            break
        kwargs = {"registryId": registry_id, "descriptorType": descriptor_type, "nextToken": token}
    return records


def _parse_mcp_server_content(control, registry_id: str, record: dict) -> dict | None:
    """Fetch full MCP record and parse server inlineContent."""
    try:
        detail = control.get_registry_record(
            registryId=registry_id, recordId=record["recordId"]
        )
        raw = (
            detail.get("descriptors", {})
            .get("mcp", {})
            .get("server", {})
            .get("inlineContent", "{}")
        )
        return json.loads(raw)
    except Exception:
        return None


def _parse_a2a_card_content(control, registry_id: str, record: dict) -> dict | None:
    """Fetch full A2A record and parse agentCard inlineContent."""
    try:
        detail = control.get_registry_record(
            registryId=registry_id, recordId=record["recordId"]
        )
        raw = (
            detail.get("descriptors", {})
            .get("a2a", {})
            .get("agentCard", {})
            .get("inlineContent", "{}")
        )
        return json.loads(raw)
    except Exception:
        return None


def discover_by_capability(
    capability: str,
    region: str = REGION,
) -> list[dict]:
    """Return all MCP servers in the Registry tagged with the given capability.

    Each entry:
        name          : str — agentRuntimeName (key for _MCP_TOOL_MAP in tools.py)
        runtime_arn   : str — used for invoke_agent_runtime
        runtime_id    : str — runtime ID parsed from ARN
        endpoint_id   : str — endpoint name
        endpoint_arn  : str — empty (not stored; endpoint is addressed by name)
    """
    control = boto3.client("bedrock-agentcore-control", region_name=region)

    registry_id = _find_registry_id(control)
    if not registry_id:
        return []

    records = _list_all_records(control, registry_id, "MCP")
    results: list[dict] = []

    for rec in records:
        if rec.get("status") not in _ACTIVE_STATUSES:
            continue
        content = _parse_mcp_server_content(control, registry_id, rec)
        if not content:
            continue
        if content.get("capability") != capability:
            continue
        runtime_arn = content.get("runtimeArn", "")
        results.append(
            {
                "name": content.get("runtimeName", rec["name"]),
                "runtime_arn": runtime_arn,
                "runtime_id": runtime_arn.split("/")[-1] if runtime_arn else "",
                "endpoint_id": content.get("endpointId", ""),
                "endpoint_arn": "",
            }
        )

    return results


def discover_a2a_agents(
    region: str = REGION,
) -> list[dict]:
    """Return all A2A agents in the Registry with capability='a2a-agent'.

    Each entry:
        name          : str — agent display name
        agent_type    : str — 'triage' | 'diagnosis' | 'resolution'
        runtime_arn   : str
        runtime_id    : str
        endpoint_id   : str
        endpoint_arn  : str
    """
    control = boto3.client("bedrock-agentcore-control", region_name=region)

    registry_id = _find_registry_id(control)
    if not registry_id:
        return []

    records = _list_all_records(control, registry_id, "A2A")
    results: list[dict] = []

    for rec in records:
        if rec.get("status") not in _ACTIVE_STATUSES:
            continue
        content = _parse_a2a_card_content(control, registry_id, rec)
        if not content:
            continue
        if content.get("capability") != "a2a-agent":
            continue
        runtime_arn = content.get("runtimeArn", "")
        results.append(
            {
                "name": content.get("name", rec["name"]),
                "agent_type": content.get("agentType", "unknown"),
                "runtime_arn": runtime_arn,
                "runtime_id": runtime_arn.split("/")[-1] if runtime_arn else "",
                "endpoint_id": content.get("endpointId", ""),
                "endpoint_arn": "",
            }
        )

    return results
