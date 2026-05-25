"""
CloudFormation Custom Resource handler — AgentCore Registry catalog.

Lifecycle:
  Create / Update : ensure the Registry exists, (re)register all records with
                    the latest runtime ARNs discovered from AgentCore.
  Delete          : delete all registry records (Registry itself is retained).

This handler is invoked by CDK custom_resources.Provider after all
CfnRuntime resources are created, so list_agent_runtimes() will always
find them.
"""

from __future__ import annotations

import json
import logging
import time

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGISTRY_NAME = "agora_registry"

# ---------------------------------------------------------------------------
# MCP server catalog — mirrors _MCP_SERVERS in agent_core_stack.py
# ---------------------------------------------------------------------------
MCP_CATALOG: list[dict] = [
    {
        "record_name": "agora-ticket-service",
        "runtime_name": None,  # OpenAPI HTTP target, not an AgentCore Runtime
        "endpoint_id": None,
        "capability": "ticket-management",
        "server_json": {
            "name": "agora/ticket-service",
            "description": "Agora Ticket Service — create, list, get, and update IT incident tickets",
            "version": "1.0.0",
        },
        "tools": [
            {
                "name": "create_ticket",
                "description": "Create a new IT incident ticket.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short title of the incident."},
                        "description": {"type": "string", "description": "Detailed description of the incident."},
                        "category": {"type": "string", "description": "Incident category (e.g. network, application, hardware)."},
                        "severity": {"type": "string", "description": "Severity level: low, medium, high, critical."},
                    },
                    "required": ["title", "description", "category", "severity"],
                },
            },
            {
                "name": "list_tickets",
                "description": "List IT incident tickets, optionally filtered by status or category.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "description": "Filter by status: open, investigating, resolved."},
                        "category": {"type": "string", "description": "Filter by category."},
                        "limit": {"type": "integer", "description": "Maximum number of tickets to return."},
                    },
                    "required": [],
                },
            },
            {
                "name": "get_ticket",
                "description": "Get details of a specific IT incident ticket by ID.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "string", "description": "The unique ticket ID."},
                    },
                    "required": ["ticket_id"],
                },
            },
            {
                "name": "update_ticket",
                "description": "Update the status or resolution of an existing ticket.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "string", "description": "The unique ticket ID."},
                        "status": {"type": "string", "description": "New status: open, investigating, resolved."},
                        "resolution": {"type": "string", "description": "Resolution notes (required when status=resolved)."},
                        "category": {"type": "string", "description": "Updated category if needed."},
                    },
                    "required": ["ticket_id"],
                },
            },
        ],
    },
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
                        "query": {"type": "string", "description": "The search query describing the technical problem."},
                        "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional technology tags."},
                        "num_results": {"type": "integer", "description": "Number of results to return (default 5, max 10)."},
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
                        "query": {"type": "string", "description": "The search query describing the issue or bug."},
                        "repos": {"type": "array", "items": {"type": "string"}, "description": "Optional list of repositories to restrict search to."},
                        "num_results": {"type": "integer", "description": "Number of results to return (default 5, max 10)."},
                    },
                    "required": ["query"],
                },
            },
        ],
    },
    {
        "record_name": "agora-cloudwatch",
        "runtime_name": None,  # Lambda wrap (agora-cloudwatch-mcp), not an AgentCore Runtime
        "endpoint_id": None,
        "capability": "aws-observability",
        "server_json": {
            "name": "agora/cloudwatch-mcp",
            "description": "CloudWatch MCP — metrics, alarms, and Logs Insights for AWS observability (awslabs/mcp)",
            "version": "1.0.0",
        },
        "tools": [
            {
                "name": "get_active_alarms",
                "description": "Get all CloudWatch alarms currently in ALARM state with their details.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "alarm_name_prefix": {"type": "string", "description": "Optional prefix to filter alarm names."},
                    },
                    "required": [],
                },
            },
            {
                "name": "get_metric_data",
                "description": "Retrieve CloudWatch metric data for a specific metric over a time range.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string", "description": "CloudWatch metric namespace (e.g. 'AWS/Lambda')."},
                        "metric_name": {"type": "string", "description": "Metric name (e.g. 'Errors')."},
                        "start_time": {"type": "string", "description": "Start time in ISO 8601 format or relative (e.g. '-1h')."},
                        "end_time": {"type": "string", "description": "End time in ISO 8601 format or 'now'."},
                        "dimensions": {"type": "object", "description": "Optional dimension filters."},
                        "statistic": {"type": "string", "description": "Statistic to retrieve (default: Sum)."},
                    },
                    "required": ["namespace", "metric_name"],
                },
            },
            {
                "name": "execute_log_insights_query",
                "description": "Run a CloudWatch Logs Insights query and return the results.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "log_group_names": {"type": "array", "items": {"type": "string"}, "description": "List of log group names to query."},
                        "query_string": {"type": "string", "description": "CloudWatch Logs Insights query string."},
                        "start_time": {"type": "string", "description": "Query start time (ISO 8601 or relative like '-1h')."},
                        "end_time": {"type": "string", "description": "Query end time (ISO 8601 or 'now')."},
                        "limit": {"type": "integer", "description": "Maximum number of log records to return (default 100)."},
                    },
                    "required": ["log_group_names", "query_string"],
                },
            },
        ],
    },
    {
        "record_name": "agora-infrastructure-inspector",
        "runtime_name": "agora_infrastructure_inspector",
        "endpoint_id": "agora_infrastructure_inspector_ep",
        "capability": "aws-infrastructure",
        "server_json": {
            "name": "agora/infrastructure-inspector-mcp",
            "description": "Infrastructure Inspector MCP — inspects Lambda, FIS experiments, and CloudFormation stacks",
            "version": "1.0.0",
        },
        "tools": [
            {
                "name": "list_active_fis_experiments",
                "description": "List all currently running AWS FIS (Fault Injection Simulator) experiments.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "inspect_lambda",
                "description": "Inspect the configuration of an AWS Lambda function (concurrency, environment, timeout, etc.).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "function_name": {"type": "string", "description": "The name or ARN of the Lambda function to inspect."},
                    },
                    "required": ["function_name"],
                },
            },
            {
                "name": "describe_cloudformation_stack",
                "description": "Describe the resources and status of a CloudFormation stack.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "stack_name": {"type": "string", "description": "The name of the CloudFormation stack."},
                    },
                    "required": ["stack_name"],
                },
            },
        ],
    },
    {
        "record_name": "agora-aws-knowledge",
        "runtime_name": None,  # External managed endpoint (https://knowledge-mcp.global.api.aws)
        "endpoint_id": None,
        "capability": "aws-knowledge",
        "server_json": {
            "name": "agora/aws-knowledge-mcp",
            "description": "AWS Knowledge MCP — AWS docs, blog posts, and Well-Architected guidance (awslabs)",
            "version": "1.0.0",
        },
        "tools": [
            {
                "name": "search_documentation",
                "description": "Search AWS documentation for a given query.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "searchPhrase": {"type": "string", "description": "The search phrase to find relevant AWS documentation."},
                    },
                    "required": ["searchPhrase"],
                },
            },
            {
                "name": "read_documentation",
                "description": "Read a specific AWS documentation page by URL.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "The URL of the AWS documentation page to read."},
                        "paragraph": {"type": "string", "description": "Optional specific paragraph or section to retrieve."},
                    },
                    "required": ["url"],
                },
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# A2A agent catalog — mirrors _A2A_AGENTS + _GATEWAY_AGENT in agent_core_stack.py
# ---------------------------------------------------------------------------
A2A_CATALOG: list[dict] = [
    {
        "record_name": "agora-triage-agent",
        "runtime_name": "agora_triage",
        "endpoint_id": "agora_triage_ep",
        "agent_type": "triage",
        "capability": "a2a-agent",
        "card": {
            "name": "Triage Agent",
            "description": "Classifies incident severity and category, then routes to the Diagnosis Agent",
            "skills": [{"id": "incident-triage", "name": "Incident Triage", "description": "Classify severity and category of a reported incident", "tags": ["itsm", "triage"]}],
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
            "description": "Diagnoses incidents by searching community knowledge sources, CloudWatch, and past tickets",
            "skills": [{"id": "incident-diagnosis", "name": "Incident Diagnosis", "description": "Search Stack Overflow, GitHub Issues, AWS Knowledge, CloudWatch, and past tickets for root cause", "tags": ["itsm", "diagnosis", "knowledge"]}],
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
            "skills": [{"id": "incident-resolution", "name": "Incident Resolution", "description": "Propose resolution steps and create an incident ticket", "tags": ["itsm", "resolution"]}],
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
            "skills": [{"id": "it-service-desk", "name": "IT Service Desk", "description": "Handle IT incidents end-to-end via the full A2A agent pipeline", "tags": ["itsm", "gateway"]}],
        },
    },
]


# ---------------------------------------------------------------------------
# AgentCore helpers
# ---------------------------------------------------------------------------


def _discover_runtime_arns(control) -> dict[str, str]:
    """Return {runtime_name: runtime_arn} for all ACTIVE AgentCore runtimes."""
    arns: dict[str, str] = {}
    kwargs: dict = {}
    while True:
        resp = control.list_agent_runtimes(**kwargs)
        for rt in resp.get("agentRuntimes", []):
            if rt.get("status") in ("READY", "ACTIVE"):
                arns[rt["agentRuntimeName"]] = rt["agentRuntimeArn"]
        token = resp.get("nextToken")
        if not token:
            break
        kwargs = {"nextToken": token}
    return arns


def _ensure_registry(control) -> str:
    resp = control.list_registries()
    for reg in resp.get("registries", []):
        if reg["name"] == REGISTRY_NAME:
            status = reg["status"]
            if status == "READY":
                return reg["registryId"]
            if "FAILED" in status:
                # 壊れた Registry を削除して再作成
                logger.info(f"Registry in {status}, deleting and recreating")
                control.delete_registry(registryId=reg["registryId"])
                break
            _wait_registry(control, reg["registryId"])
            return reg["registryId"]

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
                if status == "READY":
                    return
                if "FAILED" in status:
                    raise RuntimeError(f"Registry creation failed: {status}")
        time.sleep(5)
    raise TimeoutError("Registry did not reach READY within ~2 min")


def _list_all_records(control, registry_id: str) -> dict[str, str]:
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


def _delete_all_records(control, registry_id: str) -> None:
    records = _list_all_records(control, registry_id)
    for name, record_id in records.items():
        logger.info(f"Deleting record: {name}")
        control.delete_registry_record(registryId=registry_id, recordId=record_id)


def _wait_record(control, registry_id: str, record_id: str) -> None:
    for _ in range(12):
        try:
            rec = control.get_registry_record(registryId=registry_id, recordId=record_id)
            if rec.get("status") not in ("CREATING", "UPDATING"):
                return
        except Exception:
            pass
        time.sleep(5)


def _register_mcp(control, registry_id: str, server: dict, runtime_arn: str, existing: dict) -> None:
    name = server["record_name"]
    if name in existing:
        logger.info(f"[{name}] Already registered — skipping")
        return

    server_content: dict = {
        **server["server_json"],
        "capability": server["capability"],
    }
    if server["runtime_name"]:
        server_content["runtimeName"] = server["runtime_name"]
    if runtime_arn:
        server_content["runtimeArn"] = runtime_arn
    if server["endpoint_id"]:
        server_content["endpointId"] = server["endpoint_id"]
    resp = control.create_registry_record(
        registryId=registry_id,
        name=name,
        description=server["server_json"]["description"],
        descriptorType="MCP",
        descriptors={
            "mcp": {
                "server": {"schemaVersion": "2025-12-11", "inlineContent": json.dumps(server_content)},
                "tools": {"protocolVersion": "2025-11-25", "inlineContent": json.dumps({"tools": server["tools"]})},
            }
        },
    )
    record_id = resp["recordArn"].split("/")[-1]
    _wait_record(control, registry_id, record_id)
    logger.info(f"[{name}] Registered as MCP (id={record_id})")


def _register_mcp_gateway(control, registry_id: str, gateway_url: str, existing: dict) -> None:
    name = "agora-mcp-gateway"
    if name in existing:
        logger.info(f"[{name}] Already registered — skipping")
        return

    server_content = {
        "name": "agora/mcp-gateway",
        "description": "AgentCore MCP Gateway — aggregated MCP endpoint for all Agora tools",
        "version": "1.0.0",
        "url": gateway_url,
    }
    resp = control.create_registry_record(
        registryId=registry_id,
        name=name,
        description="AgentCore MCP Gateway URL — agents discover this to access all MCP tools",
        descriptorType="MCP",
        descriptors={
            "mcp": {
                "server": {"schemaVersion": "2025-12-11", "inlineContent": json.dumps(server_content)},
                "tools": {"protocolVersion": "2025-11-25", "inlineContent": json.dumps({"tools": []})},
            }
        },
    )
    record_id = resp["recordArn"].split("/")[-1]
    _wait_record(control, registry_id, record_id)
    logger.info(f"[{name}] Registered MCP Gateway URL (id={record_id})")


def _register_a2a(control, registry_id: str, agent: dict, runtime_arn: str, existing: dict) -> None:
    name = agent["record_name"]
    if name in existing:
        logger.info(f"[{name}] Already registered — skipping")
        return

    region = runtime_arn.split(":")[3]
    runtime_id = runtime_arn.split("/")[-1]
    agent_card = {
        **agent["card"],
        "version": "1.0.0",
        "protocolVersion": "0.3.0",
        "url": f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{runtime_id}/invoke",
        "capabilities": {},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
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
            "a2a": {"agentCard": {"schemaVersion": "0.3", "inlineContent": json.dumps(agent_card)}}
        },
    )
    record_id = resp["recordArn"].split("/")[-1]
    _wait_record(control, registry_id, record_id)
    logger.info(f"[{name}] Registered as A2A (id={record_id})")


# ---------------------------------------------------------------------------
# CloudFormation Custom Resource entrypoint
# ---------------------------------------------------------------------------


def handler(event: dict, context: object) -> dict:
    request_type = event["RequestType"]
    logger.info(f"Registry catalog handler: {request_type}")

    control = boto3.client("bedrock-agentcore-control")

    if request_type == "Delete":
        try:
            resp = control.list_registries()
            for reg in resp.get("registries", []):
                if reg["name"] == REGISTRY_NAME:
                    _delete_all_records(control, reg["registryId"])
        except Exception as e:
            logger.warning(f"Cleanup failed (non-fatal): {e}")
        return {"PhysicalResourceId": "agora-registry-catalog"}

    # Create or Update: always clear and re-register so ARNs are always current.
    # On Create this also evicts any stale records from manual registration.
    mcp_gateway_url: str = event.get("ResourceProperties", {}).get("McpGatewayUrl", "")
    runtime_arns = _discover_runtime_arns(control)
    logger.info(f"Discovered {len(runtime_arns)} active runtimes: {list(runtime_arns.keys())}")

    registry_id = _ensure_registry(control)
    logger.info(f"Registry ID: {registry_id}")

    logger.info(f"{request_type}: clearing existing records before re-registration")
    _delete_all_records(control, registry_id)

    existing: dict = {}

    if mcp_gateway_url:
        _register_mcp_gateway(control, registry_id, mcp_gateway_url, existing)
    else:
        logger.warning("McpGatewayUrl not provided — skipping MCP Gateway record")

    for server in MCP_CATALOG:
        if server["runtime_name"] is not None:
            arn = runtime_arns.get(server["runtime_name"])
            if not arn:
                logger.warning(f"[{server['record_name']}] Runtime not found — skipping")
                continue
        else:
            arn = ""
        _register_mcp(control, registry_id, server, arn, existing)

    for agent in A2A_CATALOG:
        arn = runtime_arns.get(agent["runtime_name"])
        if not arn:
            logger.warning(f"[{agent['record_name']}] Runtime not found — skipping")
            continue
        _register_a2a(control, registry_id, agent, arn, existing)

    final = _list_all_records(control, registry_id)
    logger.info(f"Registry catalog complete. Total records: {len(final)}")

    return {"PhysicalResourceId": "agora-registry-catalog"}
