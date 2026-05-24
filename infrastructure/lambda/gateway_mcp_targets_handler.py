"""
CloudFormation Custom Resource handler — AgentCore Gateway MCP Runtime targets.

Creates Gateway targets for all MCP AgentCore Runtimes using the
http.agentcoreRuntime target type, which is not supported in CDK L1.

Lifecycle:
  Create / Update : delete existing MCP targets then recreate with current runtime ARNs.
  Delete          : delete all MCP targets created by this handler.
"""
from __future__ import annotations

import logging

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_TARGETS: list[dict] = [
    # MCP servers
    {
        "runtime_name": "agora_stackoverflow",
        "target_name": "agora-stackoverflow",
        "description": "Stack Overflow search MCP — queries Stack Exchange API for Q&A",
    },
    {
        "runtime_name": "agora_github_issues",
        "target_name": "agora-github-issues",
        "description": "GitHub Issues search MCP — searches GitHub for bug reports and discussions",
    },
    {
        "runtime_name": "agora_aws_docs",
        "target_name": "agora-aws-docs",
        "description": "AWS Docs MCP — searches AWS documentation",
    },
    {
        "runtime_name": "agora_cloudwatch",
        "target_name": "agora-cloudwatch",
        "description": "CloudWatch MCP — metrics, alarms, and Logs Insights for AWS observability",
    },
    {
        "runtime_name": "agora_infrastructure_inspector",
        "target_name": "agora-infrastructure-inspector",
        "description": "Infrastructure Inspector MCP — inspects Lambda, FIS, and CloudFormation",
    },
    # A2A agents — registered in Registry and exposed via Gateway for transparent access
    {
        "runtime_name": "agora_triage",
        "target_name": "agora-triage",
        "description": "Triage Agent — classifies IT incidents by severity and category",
    },
    {
        "runtime_name": "agora_diagnosis",
        "target_name": "agora-diagnosis",
        "description": "Diagnosis Agent — searches community knowledge, CloudWatch, and past tickets for root causes",
    },
    {
        "runtime_name": "agora_resolution",
        "target_name": "agora-resolution",
        "description": "Resolution Agent — generates resolution plans and records incidents as tickets",
    },
]

_TARGET_NAMES = {t["target_name"] for t in _TARGETS}


def _discover_runtime_arns(control) -> dict[str, str]:
    """Return {runtime_name: runtime_arn} for all known runtimes."""
    arns: dict[str, str] = {}
    kwargs: dict = {}
    while True:
        resp = control.list_agent_runtimes(**kwargs)
        for rt in resp.get("agentRuntimes", []):
            arns[rt["agentRuntimeName"]] = rt["agentRuntimeArn"]
        token = resp.get("nextToken")
        if not token:
            break
        kwargs = {"nextToken": token}
    return arns


def _list_targets(control, gateway_id: str) -> dict[str, str]:
    """Return {target_name: target_id} for all targets on the gateway."""
    targets: dict[str, str] = {}
    kwargs: dict = {"gatewayIdentifier": gateway_id}
    while True:
        resp = control.list_gateway_targets(**kwargs)
        for t in resp.get("items", []):
            targets[t["name"]] = t["targetId"]
        token = resp.get("nextToken")
        if not token:
            break
        kwargs = {"gatewayIdentifier": gateway_id, "nextToken": token}
    return targets


def _delete_mcp_targets(control, gateway_id: str) -> None:
    """Delete only the MCP runtime targets managed by this handler."""
    existing = _list_targets(control, gateway_id)
    for name, target_id in existing.items():
        if name in _TARGET_NAMES:
            logger.info(f"Deleting target: {name} ({target_id})")
            control.delete_gateway_target(
                gatewayIdentifier=gateway_id,
                targetId=target_id,
            )


def handler(event: dict, context: object) -> dict:
    request_type = event["RequestType"]
    props = event.get("ResourceProperties", {})
    gateway_id = props["GatewayId"]
    logger.info(f"Gateway MCP targets handler: {request_type}, gateway={gateway_id}")

    control = boto3.client("bedrock-agentcore-control")

    if request_type == "Delete":
        try:
            _delete_mcp_targets(control, gateway_id)
        except Exception as exc:
            logger.warning(f"Cleanup failed (non-fatal): {exc}")
        return {"PhysicalResourceId": f"agora-gateway-mcp-targets-{gateway_id}"}

    # Create / Update: delete then recreate all MCP runtime targets
    runtime_arns = _discover_runtime_arns(control)
    logger.info(f"Discovered runtimes: {list(runtime_arns.keys())}")

    _delete_mcp_targets(control, gateway_id)

    for target in _TARGETS:
        arn = runtime_arns.get(target["runtime_name"])
        if not arn:
            logger.warning(f"Runtime {target['runtime_name']} not found — skipping")
            continue
        resp = control.create_gateway_target(
            gatewayIdentifier=gateway_id,
            name=target["target_name"],
            description=target["description"],
            targetConfiguration={
                "http": {
                    "agentcoreRuntime": {
                        "arn": arn,
                        "qualifier": "DEFAULT",
                    }
                }
            },
        )
        target_id = resp["targetId"]
        logger.info(f"Created target {target['target_name']}: {target_id}")

    return {"PhysicalResourceId": f"agora-gateway-mcp-targets-{gateway_id}"}
