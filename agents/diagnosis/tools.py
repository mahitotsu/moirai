from __future__ import annotations

import json
import os
from uuid import uuid4

import boto3
import httpx
from common.registry import discover_by_capability
from strands import tool

REGION = "us-east-1"
TICKET_SERVICE_URL = os.environ.get("TICKET_SERVICE_URL", "")

# Maps runtime name → (tool_name, extra_args_template)
_MCP_TOOL_MAP: dict[str, tuple[str, dict]] = {
    "agora-stackoverflow": ("search_stackoverflow", {"num_results": 5}),
    "agora-github-issues": ("search_github_issues", {"num_results": 5}),
    "agora-wikipedia": ("search_wikipedia", {"num_results": 3}),
    "agora-aws-docs": ("search_documentation", {}),
}


def _call_mcp_tool_sync(runtime_arn: str, tool_name: str, arguments: dict) -> str:
    """Invoke a tool on an AgentCore MCP runtime via invoke_agent_runtime."""
    client = boto3.client("bedrock-agentcore", region_name=REGION)
    session_id = str(uuid4())

    # MCP initialize
    init_payload = json.dumps({
        "jsonrpc": "2.0",
        "id": "1",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "diagnosis-agent", "version": "1.0"},
        },
    }).encode()
    client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        qualifier="DEFAULT",
        payload=init_payload,
        mcpSessionId=session_id,
        mcpProtocolVersion="2024-11-05",
    )

    # MCP tools/call
    call_payload = json.dumps({
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }).encode()
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        qualifier="DEFAULT",
        payload=call_payload,
        mcpSessionId=session_id,
        mcpProtocolVersion="2024-11-05",
    )

    body = resp["response"].read()
    result = json.loads(body.decode() if isinstance(body, bytes) else body)
    # MCP result format: {"result": {"content": [{"type": "text", "text": "..."}]}}
    content = result.get("result", {})
    if isinstance(content, dict):
        parts = content.get("content", [])
        if parts:
            return " ".join(p.get("text", "") for p in parts if p.get("type") == "text")
    return str(content)


@tool
def search_community_knowledge(query: str, tags: list[str] | None = None) -> str:
    """Search community knowledge sources for solutions to a technical problem.

    Searches Stack Overflow, GitHub Issues, Wikipedia, and AWS documentation
    in parallel using the query. All sources with capability="community-knowledge"
    in the AgentCore Registry are queried.

    Args:
        query: The technical problem or error message to search for.
        tags: Optional technology tags to narrow results (e.g. ["postgresql", "python"]).

    Returns:
        Combined search results from all available community knowledge sources.
    """
    runtimes = discover_by_capability("community-knowledge")
    if not runtimes:
        return "No community knowledge MCP servers are currently registered."

    def _search_one(rt: dict) -> str:
        name = rt["name"]
        arn = rt["runtime_arn"]
        entry = _MCP_TOOL_MAP.get(name)
        if not entry:
            return f"[{name}] Unknown runtime — skipped."
        tool_name, extra = entry
        args: dict = {"query": query, **extra}
        if tags and tool_name == "search_stackoverflow":
            args["tags"] = tags
        try:
            result = _call_mcp_tool_sync(arn, tool_name, args)
            return f"=== {name} ===\n{result}"
        except Exception as exc:
            return f"=== {name} ===\nError: {exc}"

    # Run searches concurrently using threads (sync tools, no event loop issues)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    parts: list[str] = []
    with ThreadPoolExecutor(max_workers=len(runtimes)) as pool:
        futures = {pool.submit(_search_one, rt): rt["name"] for rt in runtimes}
        for future in as_completed(futures):
            parts.append(future.result())

    return "\n\n".join(parts) if parts else "No results returned from any knowledge source."


@tool
def search_past_tickets(query: str, limit: int = 5) -> str:
    """Search past incident tickets for similar issues and their resolutions.

    Args:
        query: Keywords or description of the incident to match against past tickets.
        limit: Maximum number of tickets to return (default 5).

    Returns:
        List of matching past tickets with their descriptions and resolutions.
    """
    if not TICKET_SERVICE_URL:
        return "TICKET_SERVICE_URL is not configured — cannot search past tickets."

    params: dict[str, str] = {"q": query, "limit": str(limit), "status": "resolved"}
    try:
        resp = httpx.get(
            f"{TICKET_SERVICE_URL.rstrip('/')}/tickets",
            params=params,
            timeout=15.0,
        )
        resp.raise_for_status()
        tickets = resp.json()
    except Exception as exc:
        return f"Ticket search failed: {exc}"

    if not tickets:
        return "No past tickets found matching this query."

    lines: list[str] = []
    for t in tickets:
        lines.append(f"Ticket {t.get('ticket_id', '?')}: {t.get('title', 'Untitled')}")
        lines.append(f"  Category: {t.get('category', '?')} | Severity: {t.get('severity', '?')}")
        if t.get("resolution"):
            lines.append(f"  Resolution: {t['resolution']}")
        lines.append("")
    return "\n".join(lines)
