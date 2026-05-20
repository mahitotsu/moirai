from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
import httpx
from boto3.dynamodb.conditions import Key
from pydantic_settings import BaseSettings
from strands import tool

_STACK_API_BASE = "https://api.stackexchange.com/2.3"
_GITHUB_API_BASE = "https://api.github.com"
_WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
_TICKETS_TABLE = "agora-tickets"
_REGION = "us-east-1"


class _Settings(BaseSettings):
    github_token: str = ""


_github_token = _Settings().github_token


def _stackoverflow(query: str, tags: list[str] | None = None, num_results: int = 5) -> str:
    params: dict = {
        "order": "desc", "sort": "relevance", "q": query,
        "site": "stackoverflow", "pagesize": num_results, "filter": "withbody",
    }
    if tags:
        params["tagged"] = ";".join(tags)
    try:
        resp = httpx.get(f"{_STACK_API_BASE}/search/advanced", params=params, timeout=10)
        items = resp.json().get("items", []) if resp.is_success else []
    except Exception as exc:
        return f"Stack Overflow search failed: {exc}"
    if not items:
        return "No Stack Overflow results found."
    lines: list[str] = []
    for item in items[:num_results]:
        lines.append(f"### {item.get('title', 'Untitled')}")
        lines.append(f"Score: {item.get('score', 0)} | Answered: {item.get('is_answered', False)}")
        lines.append(f"URL: {item.get('link', '')}")
        body = item.get("body", "")
        if body:
            text = re.sub(r"<[^>]+>", "", body)[:400].strip()
            if text:
                lines.append(f"Preview: {text}...")
        lines.append("")
    return "\n".join(lines)


def _github_issues(query: str, num_results: int = 5) -> str:
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if _github_token:
        headers["Authorization"] = f"Bearer {_github_token}"
    try:
        resp = httpx.get(
            f"{_GITHUB_API_BASE}/search/issues",
            params={"q": query, "per_page": num_results, "sort": "best-match"},
            headers=headers,
            timeout=10,
        )
        items = resp.json().get("items", []) if resp.is_success else []
    except Exception as exc:
        return f"GitHub Issues search failed: {exc}"
    if not items:
        return "No GitHub Issues results found."
    lines: list[str] = []
    for item in items[:num_results]:
        lines.append(f"### {item.get('title', 'Untitled')}")
        lines.append(f"State: {item.get('state', '?')} | Comments: {item.get('comments', 0)}")
        lines.append(f"URL: {item.get('html_url', '')}")
        body = (item.get("body") or "")[:400].strip()
        if body:
            lines.append(f"Preview: {body}...")
        lines.append("")
    return "\n".join(lines)


def _wikipedia(query: str, num_results: int = 3) -> str:
    try:
        resp = httpx.get(
            _WIKIPEDIA_API,
            params={
                "action": "query", "list": "search", "srsearch": query,
                "srlimit": num_results, "format": "json", "utf8": 1,
            },
            headers={"User-Agent": "agora/1.0"},
            timeout=10,
        )
        results = resp.json().get("query", {}).get("search", []) if resp.is_success else []
    except Exception as exc:
        return f"Wikipedia search failed: {exc}"
    if not results:
        return "No Wikipedia results found."
    lines: list[str] = []
    for r in results:
        raw = r.get("snippet", "")
        snippet = raw.replace('<span class="searchmatch">', "").replace("</span>", "")
        lines.append(f"- **{r.get('title', '')}**: {snippet}")
    return "\n".join(lines)


@tool
def search_community_knowledge(query: str, tags: list[str] | None = None) -> str:
    """Search community knowledge sources for solutions to a technical problem.

    Searches Stack Overflow, GitHub Issues, and Wikipedia in parallel.

    Args:
        query: The technical problem or error message to search for.
        tags: Optional technology tags to narrow results (e.g. ["dynamodb", "aws"]).

    Returns:
        Combined search results from all available community knowledge sources.
    """
    sources = {
        "Stack Overflow": lambda: _stackoverflow(query, tags),
        "GitHub Issues": lambda: _github_issues(query),
        "Wikipedia": lambda: _wikipedia(query),
    }

    parts: list[str] = []
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        futures = {pool.submit(fn): name for name, fn in sources.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = f"Error: {exc}"
            parts.append(f"=== {name} ===\n{result}")

    return "\n\n".join(parts) if parts else "No results returned from knowledge sources."


@tool
def check_cloudwatch_alarms() -> str:
    """Check CloudWatch for active alarms indicating AWS infrastructure issues.

    Queries all CloudWatch alarms currently in ALARM state. Use this tool when
    diagnosing incidents that may be related to AWS infrastructure metrics
    (Lambda errors, DynamoDB throttling, API errors, high latency, etc.).

    Returns:
        Active CloudWatch alarms with details, or a message if none are found.
    """
    try:
        cw = boto3.client("cloudwatch", region_name=_REGION)
        resp = cw.describe_alarms(StateValue="ALARM", MaxRecords=50)
        alarms = resp.get("MetricAlarms", [])
        if not alarms:
            return "=== CloudWatch Active Alarms ===\nNo active alarms found."
        lines = ["=== CloudWatch Active Alarms ==="]
        for a in alarms:
            lines.append(f"\nAlarm: {a['AlarmName']}")
            if a.get("AlarmDescription"):
                lines.append(f"  Description: {a['AlarmDescription']}")
            lines.append(f"  State: {a['StateValue']} since {a.get('StateUpdatedTimestamp', '?')}")
            lines.append(f"  Metric: {a.get('Namespace', '?')}/{a.get('MetricName', '?')}")
            if a.get("StateReason"):
                lines.append(f"  Reason: {a['StateReason'][:300]}")
        return "\n".join(lines)
    except Exception as exc:
        return f"CloudWatch alarm check failed: {exc}"


@tool
def search_past_tickets(query: str, limit: int = 5) -> str:
    """Search past resolved incident tickets for similar issues.

    Args:
        query: Keywords or description of the incident to match against past tickets.
        limit: Maximum number of tickets to return (default 5).

    Returns:
        List of matching past tickets with their descriptions and resolutions.
    """
    try:
        dynamodb = boto3.resource("dynamodb", region_name=_REGION)
        table = dynamodb.Table(_TICKETS_TABLE)
        resp = table.query(
            IndexName="status-created_at-index",
            KeyConditionExpression=Key("status").eq("resolved"),
            Limit=limit,
            ScanIndexForward=False,
        )
        tickets = resp.get("Items", [])
    except Exception as exc:
        return f"Ticket search failed: {exc}"
    if not tickets:
        return "No past resolved tickets found."
    lines: list[str] = []
    for t in tickets:
        lines.append(f"Ticket {t.get('ticket_id', '?')!s}: {t.get('title', 'Untitled')!s}")
        lines.append(
            f"  Category: {t.get('category', '?')!s} | Severity: {t.get('severity', '?')!s}"
        )
        if t.get("resolution"):
            lines.append(f"  Resolution: {str(t['resolution'])[:300]}")
        lines.append("")
    return "\n".join(lines)
