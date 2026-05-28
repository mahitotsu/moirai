from __future__ import annotations

import json
import time
from typing import Any

import boto3
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "infrastructure-inspector-mcp",
    host="0.0.0.0",
    port=8000,
    stateless_http=True,
)

_clients: dict[str, Any] = {}


def _lambda() -> Any:
    if "lambda" not in _clients:
        _clients["lambda"] = boto3.client("lambda")
    return _clients["lambda"]


def _fis() -> Any:
    if "fis" not in _clients:
        _clients["fis"] = boto3.client("fis")
    return _clients["fis"]


def _cfn() -> Any:
    if "cfn" not in _clients:
        _clients["cfn"] = boto3.client("cloudformation")
    return _clients["cfn"]


def _logs() -> Any:
    if "logs" not in _clients:
        _clients["logs"] = boto3.client("logs")
    return _clients["logs"]


@mcp.tool()
def inspect_lambda(function_name: str) -> str:
    """Get configuration, tags, and trigger information for an AWS Lambda function.

    Use this to understand what a failing Lambda function does, how it is configured
    (timeout, memory, environment), what event sources trigger it, and which
    CloudFormation stack owns it. The 'aws:cloudformation:stack-name' tag (if present)
    can be used with describe_cfn_stack to explore the full resource topology.

    Args:
        function_name: The name or ARN of the Lambda function (e.g. "agora-fake-api-server").

    Returns:
        Function description, runtime, timeout, memory, environment variable keys,
        event source mappings (triggers), and all resource tags.
    """
    try:
        resp = _lambda().get_function(FunctionName=function_name)
        config = resp["Configuration"]
        function_arn = config["FunctionArn"]
        env_keys = list(config.get("Environment", {}).get("Variables", {}).keys())

        esm_resp = _lambda().list_event_source_mappings(FunctionName=function_name)
        triggers = [
            f"{m.get('EventSourceArn', 'unknown')} (state: {m.get('State', 'unknown')})"
            for m in esm_resp.get("EventSourceMappings", [])
        ]

        tags_resp = _lambda().list_tags(Resource=function_arn)
        tags = tags_resp.get("Tags", {})

        lines = [
            f"## Lambda Function: {config['FunctionName']}",
            f"ARN: {function_arn}",
            f"Description: {config.get('Description', '(none)')}",
            f"Runtime: {config.get('Runtime', 'N/A')}",
            f"Handler: {config.get('Handler', 'N/A')}",
            f"Timeout: {config.get('Timeout', 'N/A')}s",
            f"Memory: {config.get('MemorySize', 'N/A')} MB",
            f"Last modified: {config.get('LastModified', 'N/A')}",
            f"Environment variables (keys only): {', '.join(env_keys) if env_keys else '(none)'}",
            f"Event source mappings: {'; '.join(triggers) if triggers else '(none)'}",
        ]

        if tags:
            lines.append("Tags:")
            for k, v in sorted(tags.items()):
                lines.append(f"  {k}: {v}")
        else:
            lines.append("Tags: (none)")

        return "\n".join(lines)
    except Exception as e:
        return f"Failed to inspect Lambda '{function_name}': {e}"


@mcp.tool()
def get_lambda_recent_errors(function_name: str, minutes: int = 15) -> str:
    """Fetch recent error and exception log lines from a Lambda function's CloudWatch log group.

    Call this first when a Lambda alarm fires. It surfaces the actual error messages
    (exception type, error code, stack trace) so you can understand the root cause
    without any prior knowledge of what might be failing.

    Args:
        function_name: The Lambda function name (e.g. "agora-fake-api-server").
        minutes: How many minutes back to search (default 15).

    Returns:
        Up to 30 most recent log lines containing ERROR, Exception, or Traceback,
        with timestamps. If no errors are found, returns a message indicating that.
    """
    log_group = f"/aws/lambda/{function_name}"
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (minutes * 60 * 1000)

    try:
        resp = _logs().filter_log_events(
            logGroupName=log_group,
            startTime=start_ms,
            endTime=end_ms,
            filterPattern="?ERROR ?Exception ?Traceback",
            limit=30,
        )
        events = resp.get("events", [])
        if not events:
            return (
                f"No ERROR/Exception/Traceback log lines found in "
                f"/aws/lambda/{function_name} in the last {minutes} minutes."
            )

        lines = [f"## Recent errors from /aws/lambda/{function_name} (last {minutes} min)"]
        for ev in events:
            ts_sec = ev.get("timestamp", 0) // 1000
            ts_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts_sec))
            message = ev.get("message", "").rstrip()
            lines.append(f"[{ts_str}] {message}")

        return "\n".join(lines)
    except Exception as e:
        return f"Failed to fetch logs for '{function_name}': {e}"


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
        resp = _fis().list_experiments()
        experiments = [
            e for e in resp.get("experiments", [])
            if e.get("state", {}).get("status") == "running"
        ]
        if not experiments:
            return "No FIS experiments are currently running."

        lines = ["## Active FIS Experiments"]
        for exp in experiments:
            exp_id = exp.get("id", "unknown")
            template_id = exp.get("experimentTemplateId", "unknown")

            detail_resp = _fis().get_experiment(id=exp_id)
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
        stacks_resp = _cfn().describe_stacks(StackName=stack_name)
        stack = stacks_resp["Stacks"][0]

        resources_resp = _cfn().describe_stack_resources(StackName=stack_name)
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
