"""
AgentCore Registry catalog registration script.

Creates the 'agora_registry' Registry (if not exists) and populates it with
records validated against official protocol schemas:
  - MCP descriptor (schemaVersion=2025-12-11, protocolVersion=2025-11-25)
    for the 4 Community Knowledge MCP servers
  - A2A descriptor (schemaVersion=0.3) for the 3 specialist A2A agents
    and the Gateway agent

Run AFTER:
  1. `make cdk-deploy`
  2. `make build/deploy` for each MCP server
  3. `uv run --package agora-infrastructure python infrastructure/scripts/register_registry.py`
  4. `uv run --package agora-infrastructure python infrastructure/scripts/register_agents.py`

Usage:
    uv run --package agora-infrastructure python infrastructure/scripts/register_catalog.py
"""

from __future__ import annotations

import json
import sys
import time

import boto3

REGION = "us-east-1"
REGISTRY_NAME = "agora_registry"

# ---------------------------------------------------------------------------
# MCP server definitions
# runtimeName must match the agentRuntimeName registered by register_registry.py
# ---------------------------------------------------------------------------
MCP_SERVERS: list[dict] = [
    {
        "record_name": "agora-stackoverflow",
        "runtime_name": "agora_stackoverflow",
        "endpoint_id": "agora_stackoverflow_ep",
        "capability": "community-knowledge",
        "server_json": {
            "name": "agora/stackoverflow-mcp",
            "description": "Search Stack Overflow Q&A via Stack Exchange API",
            "version": "1.0.0",
        },
        "tools": [
            {
                "name": "search_stackoverflow",
                "description": "Search Stack Overflow for questions and accepted answers related to a technical problem.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query describing the technical problem.",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": 'Optional technology tags to filter by (e.g. ["python", "postgresql"]).',
                        },
                        "num_results": {
                            "type": "integer",
                            "description": "Number of results to return (default 5, max 10).",
                        },
                    },
                    "required": ["query"],
                },
            },
        ],
    },
    {
        "record_name": "agora-github-issues",
        "runtime_name": "agora_github_issues",
        "endpoint_id": "agora_github_issues_ep",
        "capability": "community-knowledge",
        "server_json": {
            "name": "agora/github-issues-mcp",
            "description": "Search GitHub Issues and Pull Requests for bug reports and discussions",
            "version": "1.0.0",
        },
        "tools": [
            {
                "name": "search_github_issues",
                "description": "Search GitHub Issues and Pull Requests for bug reports and discussions related to a problem.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query describing the issue or bug.",
                        },
                        "repos": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": 'Optional list of repositories to restrict search to (e.g. ["django/django"]).',
                        },
                        "num_results": {
                            "type": "integer",
                            "description": "Number of results to return (default 5, max 10).",
                        },
                    },
                    "required": ["query"],
                },
            },
        ],
    },
    {
        "record_name": "agora-wikipedia",
        "runtime_name": "agora_wikipedia",
        "endpoint_id": "agora_wikipedia_ep",
        "capability": "community-knowledge",
        "server_json": {
            "name": "agora/wikipedia-mcp",
            "description": "Search Wikipedia articles for technology concepts and general knowledge",
            "version": "1.0.0",
        },
        "tools": [
            {
                "name": "search_wikipedia",
                "description": "Search Wikipedia for articles related to a topic or technology concept.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The topic or concept to search for.",
                        },
                        "num_results": {
                            "type": "integer",
                            "description": "Number of articles to return (default 5, max 10).",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_wikipedia_article",
                "description": "Retrieve a summary of a specific Wikipedia article by its exact title.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": 'The exact title of the Wikipedia article (e.g. "PostgreSQL").',
                        },
                    },
                    "required": ["title"],
                },
            },
        ],
    },
    {
        "record_name": "agora-aws-docs",
        "runtime_name": "agora_aws_docs",
        "endpoint_id": "agora_aws_docs_ep",
        "capability": "community-knowledge",
        "server_json": {
            "name": "agora/aws-docs-mcp",
            "description": "Search AWS documentation via awslabs/mcp",
            "version": "1.0.0",
        },
        "tools": [
            {
                "name": "search_documentation",
                "description": "Search the AWS documentation for a given query.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query for AWS documentation.",
                        },
                    },
                    "required": ["query"],
                },
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# A2A agent definitions
# runtimeName must match the agentRuntimeName registered by register_agents.py
# ---------------------------------------------------------------------------
A2A_AGENTS: list[dict] = [
    {
        "record_name": "agora-triage-agent",
        "runtime_name": "agora_triage",
        "endpoint_id": "agora_triage_ep",
        "agent_type": "triage",
        "capability": "a2a-agent",
        "card": {
            "name": "Triage Agent",
            "description": "Classifies incident severity and category, then routes to the Diagnosis Agent",
            "skills": [
                {
                    "id": "incident-triage",
                    "name": "Incident Triage",
                    "description": "Classify severity and category of a reported incident",
                    "tags": ["itsm", "triage"],
                }
            ],
        },
    },
    {
        "record_name": "agora-diagnosis-agent",
        "runtime_name": "agora_diagnosis",
        "endpoint_id": "agora_diagnosis_ep",
        "agent_type": "diagnosis",
        "capability": "a2a-agent",
        "card": {
            "name": "Diagnosis Agent",
            "description": "Diagnoses incidents by searching community knowledge sources and past tickets in parallel",
            "skills": [
                {
                    "id": "incident-diagnosis",
                    "name": "Incident Diagnosis",
                    "description": "Search Stack Overflow, GitHub Issues, Wikipedia, AWS docs and past tickets for root cause",
                    "tags": ["itsm", "diagnosis", "knowledge"],
                }
            ],
        },
    },
    {
        "record_name": "agora-resolution-agent",
        "runtime_name": "agora_resolution",
        "endpoint_id": "agora_resolution_ep",
        "agent_type": "resolution",
        "capability": "a2a-agent",
        "card": {
            "name": "Resolution Agent",
            "description": "Generates resolution proposals and records incidents as tickets in the Ticket Service",
            "skills": [
                {
                    "id": "incident-resolution",
                    "name": "Incident Resolution",
                    "description": "Propose resolution steps and create an incident ticket",
                    "tags": ["itsm", "resolution"],
                }
            ],
        },
    },
    {
        "record_name": "agora-gateway-agent",
        "runtime_name": "agora_gateway",
        "endpoint_id": "agora_gateway_ep",
        "agent_type": "gateway",
        "capability": "gateway",
        "card": {
            "name": "Gateway Agent",
            "description": "AG-UI entry point; orchestrates the Triage → Diagnosis → Resolution pipeline",
            "skills": [
                {
                    "id": "it-service-desk",
                    "name": "IT Service Desk",
                    "description": "Handle IT incidents end-to-end via the full A2A agent pipeline",
                    "tags": ["itsm", "gateway"],
                }
            ],
        },
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_runtime_arns_from_cfn(cf) -> dict[str, str]:
    """Read all AgentCore runtime ARNs from AgoraAgentCoreStack outputs."""
    stacks = cf.describe_stacks(StackName="AgoraAgentCoreStack")["Stacks"]
    outputs = stacks[0].get("Outputs", [])
    return {o["ExportName"]: o["OutputValue"] for o in outputs if "ExportName" in o}


def _get_runtime_arn(runtime_name: str, cfn_arns: dict[str, str]) -> str:
    key = f"AgentCore-{runtime_name.replace('_', '-')}-arn"
    arn = cfn_arns.get(key)
    if not arn:
        raise LookupError(
            f"Runtime ARN for '{runtime_name}' not found in AgoraAgentCoreStack outputs "
            f"(expected export key: {key!r}). Run `make cdk-deploy` first."
        )
    return arn


def _ensure_registry(control) -> str:
    resp = control.list_registries()
    for reg in resp.get("registries", []):
        if reg["name"] == REGISTRY_NAME:
            if reg["status"] != "READY":
                print(f"  Registry status={reg['status']}, waiting ...")
                _wait_registry(control, reg["registryId"])
            return reg["registryId"]

    print(f"  Creating registry '{REGISTRY_NAME}' ...")
    resp = control.create_registry(
        name=REGISTRY_NAME,
        description="Agora IT Service Desk — capability catalog for MCP servers and A2A agents",
        authorizerType="AWS_IAM",
    )
    registry_id = resp["registryArn"].split("/")[-1]
    _wait_registry(control, registry_id)
    return registry_id


def _wait_registry(control, registry_id: str) -> None:
    for _ in range(24):
        resp = control.list_registries()
        for reg in resp.get("registries", []):
            if reg["registryId"] == registry_id:
                status = reg["status"]
                print(f"    Registry status: {status}")
                if status == "READY":
                    return
                if "FAILED" in status:
                    raise RuntimeError(f"Registry failed: {status}")
        time.sleep(5)
    raise TimeoutError("Registry did not reach READY within ~2 min")


def _wait_record(control, registry_id: str, record_id: str) -> None:
    for _ in range(12):
        try:
            rec = control.get_registry_record(registryId=registry_id, recordId=record_id)
            status = rec.get("status", "UNKNOWN")
            if status not in ("CREATING", "UPDATING"):
                return
        except Exception:
            pass
        time.sleep(5)


def _existing_records(control, registry_id: str) -> dict[str, str]:
    """Return {record_name: record_id}."""
    records: dict[str, str] = {}
    kwargs: dict = {"registryId": registry_id}
    while True:
        resp = control.list_registry_records(**kwargs)
        for rec in resp.get("registryRecords", []):
            records[rec["name"]] = rec["recordId"]
        token = resp.get("nextToken")
        if not token:
            break
        kwargs = {"registryId": registry_id, "nextToken": token}
    return records


def _register_mcp_server(
    control, registry_id: str, server: dict, runtime_arn: str, existing: dict
) -> str:
    name = server["record_name"]
    if name in existing:
        print(f"  [{name}] Already registered — skipping")
        return existing[name]

    server_content = {
        **server["server_json"],
        # Extra fields for AgentCore runtime discovery (additional properties allowed by schema)
        "runtimeName": server["runtime_name"],
        "runtimeArn": runtime_arn,
        "endpointId": server["endpoint_id"],
        "capability": server["capability"],
    }
    tools_content = {"tools": server["tools"]}

    resp = control.create_registry_record(
        registryId=registry_id,
        name=name,
        description=server["server_json"]["description"],
        descriptorType="MCP",
        descriptors={
            "mcp": {
                "server": {
                    "schemaVersion": "2025-12-11",
                    "inlineContent": json.dumps(server_content),
                },
                "tools": {
                    "protocolVersion": "2025-11-25",
                    "inlineContent": json.dumps(tools_content),
                },
            }
        },
    )
    record_id = resp["recordArn"].split("/")[-1]
    _wait_record(control, registry_id, record_id)
    print(f"  [{name}] Registered as MCP (id={record_id})")
    return record_id


def _register_a2a_agent(
    control, registry_id: str, agent: dict, runtime_arn: str, existing: dict
) -> str:
    name = agent["record_name"]
    if name in existing:
        print(f"  [{name}] Already registered — skipping")
        return existing[name]

    agent_card = {
        **agent["card"],
        "version": "1.0.0",
        "protocolVersion": "0.3.0",
        # Placeholder HTTP URL (required by A2A spec); actual invocation is via AWS SDK
        "url": f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{runtime_arn.split('/')[-1]}/invoke",
        "capabilities": {},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        # Extra fields for AgentCore runtime discovery
        "runtimeName": agent["runtime_name"],
        "agentType": agent["agent_type"],
        "runtimeArn": runtime_arn,
        "endpointId": agent["endpoint_id"],
        "capability": agent["capability"],
    }

    resp = control.create_registry_record(
        registryId=registry_id,
        name=name,
        description=agent["card"]["description"],
        descriptorType="A2A",
        descriptors={
            "a2a": {
                "agentCard": {
                    "schemaVersion": "0.3",
                    "inlineContent": json.dumps(agent_card),
                }
            }
        },
    )
    record_id = resp["recordArn"].split("/")[-1]
    _wait_record(control, registry_id, record_id)
    print(f"  [{name}] Registered as A2A (id={record_id})")
    return record_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    cf = boto3.client("cloudformation", region_name=REGION)
    control = boto3.client("bedrock-agentcore-control", region_name=REGION)

    print("Reading runtime ARNs from AgoraAgentCoreStack outputs ...")
    try:
        cfn_arns = _get_runtime_arns_from_cfn(cf)
    except Exception as e:
        print(f"ERROR: Failed to read AgoraAgentCoreStack outputs: {e}")
        print("  Make sure `make cdk-deploy` has completed.")
        sys.exit(1)

    print(f"Ensuring registry '{REGISTRY_NAME}' ...")
    registry_id = _ensure_registry(control)
    print(f"  Registry ID: {registry_id}")

    existing = _existing_records(control, registry_id)
    print(f"  Existing records: {len(existing)}")

    print("\n=== Registering MCP servers (descriptorType=MCP, schemaVersion=2025-12-11) ===")
    for server in MCP_SERVERS:
        try:
            runtime_arn = _get_runtime_arn(server["runtime_name"], cfn_arns)
        except LookupError as e:
            print(f"  [{server['record_name']}] SKIP — {e}")
            continue
        _register_mcp_server(control, registry_id, server, runtime_arn, existing)

    print("\n=== Registering A2A agents (descriptorType=A2A, schemaVersion=0.3) ===")
    for agent in A2A_AGENTS:
        try:
            runtime_arn = _get_runtime_arn(agent["runtime_name"], cfn_arns)
        except LookupError as e:
            print(f"  [{agent['record_name']}] SKIP — {e}")
            continue
        _register_a2a_agent(control, registry_id, agent, runtime_arn, existing)

    print("\n=== Summary ===")
    final = _existing_records(control, registry_id)
    print(f"  Registry: {REGISTRY_NAME} (id={registry_id})")
    print(f"  Total records: {len(final)}")
    for name in sorted(final):
        print(f"    {name}")

    print()
    print("Agents can discover resources via:")
    print("  from common.registry import discover_by_capability, discover_a2a_agents")
    print("  runtimes = discover_by_capability('community-knowledge')")


if __name__ == "__main__":
    main()
