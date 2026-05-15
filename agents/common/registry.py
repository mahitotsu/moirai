"""
AgentCore Registry discovery utility.

Agents use this module to find MCP servers and other AgentCore Runtimes
by capability tag, instead of hardcoding endpoint identifiers.

Example:
    from common.registry import discover_by_capability

    runtimes = discover_by_capability("community-knowledge")
    # [{"name": "agora-stackoverflow", "runtime_id": "...", "runtime_arn": "...",
    #   "endpoint_id": "...", "endpoint_arn": "..."}, ...]
"""

from __future__ import annotations

import boto3

REGION = "us-east-1"


def _list_all_runtimes(control) -> list[dict]:
    runtimes = []
    kwargs: dict = {}
    while True:
        resp = control.list_agent_runtimes(**kwargs)
        runtimes.extend(resp.get("agentRuntimes", []))
        token = resp.get("nextToken")
        if not token:
            break
        kwargs = {"nextToken": token}
    return runtimes


def _get_tags(control, arn: str) -> dict[str, str]:
    try:
        resp = control.list_tags_for_resource(resourceArn=arn)
        return resp.get("tags", {})
    except Exception:
        return {}


def _get_first_ready_endpoint(control, runtime_id: str) -> dict | None:
    """Return the first READY endpoint as {"id": ..., "arn": ...}."""
    kwargs: dict = {"agentRuntimeId": runtime_id}
    while True:
        resp = control.list_agent_runtime_endpoints(**kwargs)
        for ep in resp.get("runtimeEndpoints", []):
            if ep.get("status") == "READY":
                return {"id": ep["id"], "arn": ep.get("agentRuntimeEndpointArn", "")}
        token = resp.get("nextToken")
        if not token:
            break
        kwargs = {"agentRuntimeId": runtime_id, "nextToken": token}
    return None


def discover_by_capability(
    capability: str,
    region: str = REGION,
) -> list[dict]:
    """Return all READY AgentCore Runtimes tagged with the given capability.

    Each entry:
        name          : str — agentRuntimeName
        runtime_id    : str — agentRuntimeId
        runtime_arn   : str — agentRuntimeArn (used for invoke_agent_runtime)
        endpoint_id   : str | None — first READY endpoint name/id
        endpoint_arn  : str | None — first READY endpoint ARN
    """
    control = boto3.client("bedrock-agentcore-control", region_name=region)
    all_runtimes = _list_all_runtimes(control)

    results = []
    for rt in all_runtimes:
        if rt.get("status") != "READY":
            continue
        tags = _get_tags(control, rt["agentRuntimeArn"])
        if tags.get("capability") != capability:
            continue
        ep = _get_first_ready_endpoint(control, rt["agentRuntimeId"])
        results.append(
            {
                "name": rt["agentRuntimeName"],
                "runtime_id": rt["agentRuntimeId"],
                "runtime_arn": rt["agentRuntimeArn"],
                "endpoint_id": ep["id"] if ep else None,
                "endpoint_arn": ep["arn"] if ep else None,
            }
        )
    return results


def discover_a2a_agents(
    region: str = REGION,
) -> list[dict]:
    """Return all READY A2A agents (tagged capability="a2a-agent").

    Each entry has the same shape as discover_by_capability results,
    plus "agent_type" from the "agent-type" tag.
    """
    control = boto3.client("bedrock-agentcore-control", region_name=region)
    all_runtimes = _list_all_runtimes(control)

    results = []
    for rt in all_runtimes:
        if rt.get("status") != "READY":
            continue
        tags = _get_tags(control, rt["agentRuntimeArn"])
        if tags.get("capability") != "a2a-agent":
            continue
        ep = _get_first_ready_endpoint(control, rt["agentRuntimeId"])
        results.append(
            {
                "name": rt["agentRuntimeName"],
                "agent_type": tags.get("agent-type", "unknown"),
                "runtime_id": rt["agentRuntimeId"],
                "runtime_arn": rt["agentRuntimeArn"],
                "endpoint_id": ep["id"] if ep else None,
                "endpoint_arn": ep["arn"] if ep else None,
            }
        )
    return results
