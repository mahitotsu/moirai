from __future__ import annotations

import json
import logging
import sys

import boto3
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, force=True)

mcp = FastMCP(
    "infrastructure-inspector-mcp",
    host="0.0.0.0",
    port=8080,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

_lambda_client = boto3.client("lambda")
_fis_client = boto3.client("fis")
_cfn_client = boto3.client("cloudformation")


@mcp.tool()
def inspect_lambda(function_name: str) -> str:
    """Get configuration and trigger information for an AWS Lambda function.

    Use this to understand what a failing Lambda function does, how it is configured
    (timeout, memory, environment), and what event sources trigger it. Particularly
    useful when diagnosing Lambda errors reported in CloudWatch alarms.

    Args:
        function_name: The name or ARN of the Lambda function (e.g. "agora-fake-api-server").

    Returns:
        Function description, runtime, timeout, memory, environment variable keys,
        and event source mappings (triggers).
    """
    try:
        resp = _lambda_client.get_function(FunctionName=function_name)
        config = resp["Configuration"]
        env_keys = list(config.get("Environment", {}).get("Variables", {}).keys())

        esm_resp = _lambda_client.list_event_source_mappings(FunctionName=function_name)
        triggers = [
            f"{m.get('EventSourceArn', 'unknown')} (state: {m.get('State', 'unknown')})"
            for m in esm_resp.get("EventSourceMappings", [])
        ]

        lines = [
            f"## Lambda Function: {config['FunctionName']}",
            f"Description: {config.get('Description', '(none)')}",
            f"Runtime: {config.get('Runtime', 'N/A')}",
            f"Handler: {config.get('Handler', 'N/A')}",
            f"Timeout: {config.get('Timeout', 'N/A')}s",
            f"Memory: {config.get('MemorySize', 'N/A')} MB",
            f"Last modified: {config.get('LastModified', 'N/A')}",
            f"Environment variables (keys only): {', '.join(env_keys) if env_keys else '(none)'}",
            f"Event source mappings: {'; '.join(triggers) if triggers else '(none)'}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to inspect Lambda '{function_name}': {e}"


@mcp.tool()
def list_active_fis_experiments() -> str:
    """List currently running AWS FIS (Fault Injection Simulator) experiments.

    Use this to determine what fault injection is actively occurring in the environment.
    Returns experiment IDs, injected fault types, targeted resources, and start times.
    Call this when an alarm fires and the root cause may be deliberate fault injection.

    Returns:
        Details of all running FIS experiments including the fault being injected,
        or a message indicating no experiments are running.
    """
    try:
        resp = _fis_client.list_experiments(
            filters=[{"key": "state", "values": ["running"]}]
        )
        experiments = resp.get("experiments", [])
        if not experiments:
            return "No FIS experiments are currently running."

        lines = ["## Active FIS Experiments"]
        for exp in experiments:
            exp_id = exp.get("id", "unknown")
            template_id = exp.get("experimentTemplateId", "unknown")

            detail_resp = _fis_client.get_experiment(id=exp_id)
            detail = detail_resp.get("experiment", {})
            state = detail.get("state", {})
            actions = detail.get("actions", {})
            targets = detail.get("targets", {})

            lines.append(f"\n### Experiment: {exp_id}")
            lines.append(f"Template: {template_id}")
            lines.append(f"State: {state.get('status', 'unknown')}")
            lines.append(f"Started: {detail.get('startTime', 'unknown')}")

            if actions:
                lines.append("Actions (faults being injected):")
                for action_id, action in actions.items():
                    lines.append(f"  - {action_id}: {action.get('actionId', 'unknown')}")
                    for k, v in action.get("parameters", {}).items():
                        lines.append(f"    {k}: {v}")

            if targets:
                lines.append("Targets:")
                for target_id, target in targets.items():
                    lines.append(
                        f"  - {target_id}: {target.get('resourceType', 'unknown')}"
                        f" ({json.dumps(target.get('resourceArns', target.get('filters', [])))})"
                    )

        return "\n".join(lines)
    except Exception as e:
        return f"Failed to list FIS experiments: {e}"


@mcp.tool()
def describe_cfn_stack(stack_name: str) -> str:
    """Describe an AWS CloudFormation stack and its deployed resources.

    Use this to understand the infrastructure components that support a failing service.
    Particularly useful for inspecting the FaultInjectionStack (which contains the
    fake-api-server Lambda and FIS template) or the AgoraStack.

    Args:
        stack_name: The CloudFormation stack name (e.g. "FaultInjectionStack", "AgoraStack").

    Returns:
        Stack status, creation time, and a list of all resources with their types,
        logical IDs, and physical IDs.
    """
    try:
        stacks_resp = _cfn_client.describe_stacks(StackName=stack_name)
        stack = stacks_resp["Stacks"][0]

        resources_resp = _cfn_client.describe_stack_resources(StackName=stack_name)
        resources = resources_resp.get("StackResources", [])

        lines = [
            f"## CloudFormation Stack: {stack['StackName']}",
            f"Status: {stack['StackStatus']}",
            f"Created: {stack.get('CreationTime', 'N/A')}",
            f"Description: {stack.get('Description', '(none)')}",
            "",
            f"Resources ({len(resources)}):",
        ]
        for r in resources:
            physical = r.get("PhysicalResourceId", "(pending)")
            lines.append(
                f"  - [{r['ResourceType']}] {r['LogicalResourceId']}"
                f" → {physical} ({r['ResourceStatus']})"
            )

        return "\n".join(lines)
    except Exception as e:
        return f"Failed to describe CloudFormation stack '{stack_name}': {e}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
