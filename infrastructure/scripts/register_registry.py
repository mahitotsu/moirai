"""
AgentCore Registry registration script for Community Knowledge MCP servers.

Creates (or idempotently updates) four AgentCore Runtimes tagged with
capability="community-knowledge". Each runtime also gets a single endpoint.

Run AFTER:
  1. `make cdk-deploy` — creates ECR repos and the MCP runtime IAM role
  2. `make build img=<name> && make deploy img=<name>` — for each MCP server

Usage:
    uv run python infrastructure/scripts/register_registry.py

Environment variables:
    GITHUB_TOKEN  (optional) — injected into github-issues runtime for higher rate limits
"""

from __future__ import annotations

import os
import sys
import time

import boto3

REGION = "us-east-1"
CAPABILITY = "community-knowledge"
ENDPOINT_NAME_SUFFIX = "ep"

MCP_SERVERS: list[dict] = [
    {
        "name": "stackoverflow",
        "runtime_name": "agora-stackoverflow",
        "description": "Stack Overflow search MCP — queries Stack Exchange API for Q&A",
        "env": {},
    },
    {
        "name": "github-issues",
        "runtime_name": "agora-github-issues",
        "description": "GitHub Issues search MCP — searches GitHub for bug reports and discussions",
        "env": {"GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", "")},
    },
    {
        "name": "wikipedia",
        "runtime_name": "agora-wikipedia",
        "description": "Wikipedia MCP — searches Wikipedia for technology concepts and articles",
        "env": {},
    },
    {
        "name": "aws-docs",
        "runtime_name": "agora-aws-docs",
        "description": "AWS Docs MCP — searches AWS documentation (awslabs/mcp)",
        "env": {"AWS_DOCUMENTATION_PARTITION": "aws", "FASTMCP_LOG_LEVEL": "WARNING"},
    },
]


def _resolve_cfn_outputs(cf) -> dict[str, str]:
    """Fetch all outputs from AgoraComputeStack."""
    stacks = cf.describe_stacks(StackName="AgoraComputeStack")["Stacks"]
    return {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}


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


def _list_all_endpoints(control, runtime_id: str) -> list[dict]:
    endpoints = []
    kwargs: dict = {"agentRuntimeId": runtime_id}
    while True:
        resp = control.list_agent_runtime_endpoints(**kwargs)
        endpoints.extend(resp.get("runtimeEndpoints", []))
        token = resp.get("nextToken")
        if not token:
            break
        kwargs = {"agentRuntimeId": runtime_id, "nextToken": token}
    return endpoints


def _wait_for_runtime(control, runtime_id: str, desired: str = "READY") -> None:
    for _ in range(40):
        resp = control.get_agent_runtime(agentRuntimeId=runtime_id)
        status = resp["status"]
        print(f"    status: {status}")
        if status == desired:
            return
        if "FAILED" in status:
            raise RuntimeError(f"Runtime entered failed state: {status}")
        time.sleep(10)
    raise TimeoutError(f"Runtime {runtime_id} did not reach {desired} within ~7 min")


def _wait_for_endpoint(control, runtime_id: str, endpoint_id: str, desired: str = "READY") -> None:
    for _ in range(40):
        resp = control.get_agent_runtime_endpoint(
            agentRuntimeId=runtime_id, endpointName=endpoint_id
        )
        status = resp["status"]
        print(f"    endpoint status: {status}")
        if status == desired:
            return
        if "FAILED" in status:
            raise RuntimeError(f"Endpoint entered failed state: {status}")
        time.sleep(10)
    raise TimeoutError(f"Endpoint {endpoint_id} did not reach {desired} within ~7 min")


def _register_one(control, server: dict, ecr_uri: str, role_arn: str) -> dict:
    """Create or reuse an AgentCore Runtime + Endpoint for one MCP server."""
    runtime_name = server["runtime_name"]
    endpoint_name = f"{runtime_name}-{ENDPOINT_NAME_SUFFIX}"

    # Filter environment variables: skip empty values
    env_vars = {k: v for k, v in server["env"].items() if v}

    # ------------------------------------------------------------------
    # 1. Runtime: create or reuse
    # ------------------------------------------------------------------
    all_runtimes = _list_all_runtimes(control)
    existing = next((r for r in all_runtimes if r["agentRuntimeName"] == runtime_name), None)

    if existing:
        runtime_id = existing["agentRuntimeId"]
        print(f"  [{server['name']}] Reusing Runtime: {runtime_id}")
    else:
        print(f"  [{server['name']}] Creating Runtime '{runtime_name}' ...")
        kwargs: dict = {
            "agentRuntimeName": runtime_name,
            "description": server["description"],
            "agentRuntimeArtifact": {
                "containerConfiguration": {"containerUri": ecr_uri},
            },
            "roleArn": role_arn,
            "networkConfiguration": {"networkMode": "PUBLIC"},
            "protocolConfiguration": {"serverProtocol": "MCP"},
            "tags": {
                "capability": CAPABILITY,
                "project": "agora",
                "mcp-server": server["name"],
            },
        }
        if env_vars:
            kwargs["environmentVariables"] = env_vars

        resp = control.create_agent_runtime(**kwargs)
        runtime_id = resp["agentRuntimeId"]
        print(f"    Runtime ID: {runtime_id} — waiting for READY ...")
        _wait_for_runtime(control, runtime_id)

    # ------------------------------------------------------------------
    # 2. Endpoint: create or reuse
    # ------------------------------------------------------------------
    all_endpoints = _list_all_endpoints(control, runtime_id)
    existing_ep = next((e for e in all_endpoints if e["name"] == endpoint_name), None)

    if existing_ep:
        endpoint_id = existing_ep["id"]
        print(f"  [{server['name']}] Reusing Endpoint: {endpoint_id}")
    else:
        print(f"  [{server['name']}] Creating Endpoint '{endpoint_name}' ...")
        resp = control.create_agent_runtime_endpoint(
            agentRuntimeId=runtime_id,
            name=endpoint_name,
            description=f"Default endpoint for {runtime_name}",
        )
        endpoint_id = resp.get("id", endpoint_name)
        print(f"    Endpoint ID: {endpoint_id} — waiting for READY ...")
        _wait_for_endpoint(control, runtime_id, endpoint_name)

    return {
        "name": server["name"],
        "runtime_name": runtime_name,
        "runtime_id": runtime_id,
        "endpoint_id": endpoint_id,
        "capability": CAPABILITY,
    }


def main() -> None:
    cf = boto3.client("cloudformation", region_name=REGION)
    control = boto3.client("bedrock-agentcore-control", region_name=REGION)

    # ------------------------------------------------------------------
    # Resolve ECR URIs and role ARN from CloudFormation outputs
    # ------------------------------------------------------------------
    print("Resolving CloudFormation outputs from AgoraComputeStack ...")
    try:
        outputs = _resolve_cfn_outputs(cf)
    except Exception as e:
        print(f"ERROR: Failed to read AgoraComputeStack outputs: {e}")
        print("  Make sure `make cdk-deploy` has completed.")
        sys.exit(1)

    role_arn = outputs.get("McpRuntimeRoleArn")
    if not role_arn:
        print("ERROR: McpRuntimeRoleArn not found in AgoraComputeStack outputs.")
        sys.exit(1)

    # ECR account / region from first repo output
    account = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    ecr_base = f"{account}.dkr.ecr.{REGION}.amazonaws.com"

    # ------------------------------------------------------------------
    # Register each MCP server
    # ------------------------------------------------------------------
    results = []
    for server in MCP_SERVERS:
        ecr_uri = f"{ecr_base}/agora-{server['name']}:latest"
        print(f"\nRegistering {server['name']} ({ecr_uri}) ...")
        try:
            result = _register_one(control, server, ecr_uri, role_arn)
            results.append(result)
        except Exception as e:
            print(f"  ERROR: {e}")
            sys.exit(1)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n=== Registry registration complete ===")
    print(f"  Capability tag: {CAPABILITY}")
    print()
    for r in results:
        print(f"  {r['name']}")
        print(f"    Runtime ID : {r['runtime_id']}")
        print(f"    Endpoint ID: {r['endpoint_id']}")
    print()
    print("Agents can discover these runtimes via:")
    print("  from agents.common.registry import discover_by_capability")
    print(f"  runtimes = discover_by_capability('{CAPABILITY}')")


if __name__ == "__main__":
    main()
