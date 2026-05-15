"""
AgentCore Runtime registration script for A2A agents (Triage / Diagnosis / Resolution).

Creates (or idempotently reuses) three AgentCore Runtimes with A2A protocol,
each tagged with capability="a2a-agent" and agent-type=<name>.

Run AFTER:
  1. `make cdk-deploy`  — creates ECR repos and agent IAM role
  2. `make build img=triage && make deploy img=triage`  — for each agent
     (same for diagnosis and resolution)

Usage:
    uv run python infrastructure/scripts/register_agents.py

Environment variables (all optional — resolved from CloudFormation if absent):
    TICKET_SERVICE_URL  — Lambda Function URL for Ticket Service
    AGENT_RUNTIME_ROLE_ARN  — IAM role ARN for agent runtimes
"""

from __future__ import annotations

import os
import sys
import time

import boto3

REGION = "us-east-1"
CAPABILITY = "a2a-agent"

AGENTS: list[dict] = [
    {
        "name": "triage",
        "runtime_name": "agora-triage",
        "description": "Triage Agent — classifies IT incidents by severity and category",
        "env": {},
    },
    {
        "name": "diagnosis",
        "runtime_name": "agora-diagnosis",
        "description": "Diagnosis Agent — searches community knowledge and past tickets",
        "env": {},  # TICKET_SERVICE_URL injected below
    },
    {
        "name": "resolution",
        "runtime_name": "agora-resolution",
        "description": "Resolution Agent — generates resolution plans and creates incident tickets",
        "env": {},  # TICKET_SERVICE_URL injected below
    },
]


def _resolve_cfn_outputs(cf) -> dict[str, str]:
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


def _wait_for_endpoint(
    control, runtime_id: str, endpoint_name: str, desired: str = "READY"
) -> None:
    for _ in range(40):
        resp = control.get_agent_runtime_endpoint(
            agentRuntimeId=runtime_id, endpointName=endpoint_name
        )
        status = resp["status"]
        print(f"    endpoint status: {status}")
        if status == desired:
            return
        if "FAILED" in status:
            raise RuntimeError(f"Endpoint entered failed state: {status}")
        time.sleep(10)
    raise TimeoutError(f"Endpoint did not reach {desired} within ~7 min")


def _register_one(
    control,
    agent: dict,
    ecr_uri: str,
    role_arn: str,
) -> dict:
    runtime_name = agent["runtime_name"]
    endpoint_name = f"{runtime_name}-ep"

    env_vars = {k: v for k, v in agent["env"].items() if v}

    # ------------------------------------------------------------------
    # Runtime: create or reuse
    # ------------------------------------------------------------------
    all_runtimes = _list_all_runtimes(control)
    existing = next((r for r in all_runtimes if r["agentRuntimeName"] == runtime_name), None)

    if existing:
        runtime_id = existing["agentRuntimeId"]
        runtime_arn = existing["agentRuntimeArn"]
        print(f"  [{agent['name']}] Reusing Runtime: {runtime_id}")
    else:
        print(f"  [{agent['name']}] Creating Runtime '{runtime_name}' ...")
        kwargs: dict = {
            "agentRuntimeName": runtime_name,
            "description": agent["description"],
            "agentRuntimeArtifact": {
                "containerConfiguration": {"containerUri": ecr_uri},
            },
            "roleArn": role_arn,
            "networkConfiguration": {"networkMode": "PUBLIC"},
            "protocolConfiguration": {"serverProtocol": "A2A"},
            "tags": {
                "capability": CAPABILITY,
                "agent-type": agent["name"],
                "project": "agora",
            },
        }
        if env_vars:
            kwargs["environmentVariables"] = env_vars

        resp = control.create_agent_runtime(**kwargs)
        runtime_id = resp["agentRuntimeId"]
        runtime_arn = resp["agentRuntimeArn"]
        print(f"    Runtime ID: {runtime_id} — waiting for READY ...")
        _wait_for_runtime(control, runtime_id)

    # ------------------------------------------------------------------
    # Endpoint: create or reuse
    # ------------------------------------------------------------------
    all_endpoints = _list_all_endpoints(control, runtime_id)
    existing_ep = next((e for e in all_endpoints if e["name"] == endpoint_name), None)

    if existing_ep:
        endpoint_id = existing_ep["id"]
        print(f"  [{agent['name']}] Reusing Endpoint: {endpoint_id}")
    else:
        print(f"  [{agent['name']}] Creating Endpoint '{endpoint_name}' ...")
        resp = control.create_agent_runtime_endpoint(
            agentRuntimeId=runtime_id,
            name=endpoint_name,
            description=f"Default endpoint for {runtime_name}",
        )
        endpoint_id = resp.get("id", endpoint_name)
        print(f"    Endpoint ID: {endpoint_id} — waiting for READY ...")
        _wait_for_endpoint(control, runtime_id, endpoint_name)

    return {
        "name": agent["name"],
        "runtime_name": runtime_name,
        "runtime_id": runtime_id,
        "runtime_arn": runtime_arn,
        "endpoint_id": endpoint_id,
    }


def main() -> None:
    cf = boto3.client("cloudformation", region_name=REGION)
    control = boto3.client("bedrock-agentcore-control", region_name=REGION)

    print("Resolving CloudFormation outputs from AgoraComputeStack ...")
    try:
        outputs = _resolve_cfn_outputs(cf)
    except Exception as e:
        print(f"ERROR: Failed to read AgoraComputeStack outputs: {e}")
        print("  Make sure `make cdk-deploy` has completed.")
        sys.exit(1)

    role_arn = os.environ.get("AGENT_RUNTIME_ROLE_ARN") or outputs.get("AgentRuntimeRoleArn")
    if not role_arn:
        print("ERROR: AgentRuntimeRoleArn not found. Run `make cdk-deploy` first.")
        sys.exit(1)

    ticket_url = os.environ.get("TICKET_SERVICE_URL") or outputs.get("TicketFunctionUrl", "")
    if not ticket_url:
        print("WARNING: TicketFunctionUrl not found — TICKET_SERVICE_URL will be empty in agents.")

    # Inject TICKET_SERVICE_URL into agents that need it
    for agent in AGENTS:
        if agent["name"] in ("diagnosis", "resolution") and ticket_url:
            agent["env"]["TICKET_SERVICE_URL"] = ticket_url

    account = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    ecr_base = f"{account}.dkr.ecr.{REGION}.amazonaws.com"

    results = []
    for agent in AGENTS:
        ecr_uri = f"{ecr_base}/agora-{agent['name']}:latest"
        print(f"\nRegistering {agent['name']} ({ecr_uri}) ...")
        try:
            result = _register_one(control, agent, ecr_uri, role_arn)
            results.append(result)
        except Exception as e:
            print(f"  ERROR: {e}")
            sys.exit(1)

    print("\n=== A2A agent registration complete ===")
    print(f"  Capability tag: {CAPABILITY}")
    print()
    for r in results:
        print(f"  {r['name']}")
        print(f"    Runtime ID  : {r['runtime_id']}")
        print(f"    Runtime ARN : {r['runtime_arn']}")
        print(f"    Endpoint ID : {r['endpoint_id']}")
    print()
    print("Agents can be discovered via:")
    print("  from common.registry import discover_a2a_agents")
    print("  agents = discover_a2a_agents()")


if __name__ == "__main__":
    main()
