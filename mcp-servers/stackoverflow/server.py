from __future__ import annotations

import logging
import re
import sys

from client import StackOverflowClient
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, force=True)

mcp = FastMCP(
    "stackoverflow-mcp",
    host="0.0.0.0",
    port=8080,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
_client: StackOverflowClient | None = None


def _get_client() -> StackOverflowClient:
    global _client
    if _client is None:
        _client = StackOverflowClient()
    return _client


@mcp.tool()
async def search_stackoverflow(
    query: str,
    tags: list[str] | None = None,
    num_results: int = 5,
) -> str:
    """Search Stack Overflow for questions and accepted answers related to a technical problem.

    Args:
        query: The search query describing the technical problem.
        tags: Optional list of technology tags to filter by (e.g. ["python", "postgresql"]).
        num_results: Number of results to return (default 5, max 10).

    Returns:
        Formatted text with top questions, their scores, and accepted answers.
    """
    try:
        items = await _get_client().search(query, tags=tags, num_results=min(num_results, 10))
    except Exception as e:
        raise ValueError(f"Stack Overflow search failed: {e}") from e

    if not items:
        return "No results found for the given query."

    lines: list[str] = []
    for item in items:
        title = item.get("title", "Untitled")
        score = item.get("score", 0)
        is_answered = item.get("is_answered", False)
        link = item.get("link", "")
        answer_count = item.get("answer_count", 0)
        lines.append(f"### {title}")
        lines.append(f"Score: {score} | Answers: {answer_count} | Answered: {is_answered}")
        lines.append(f"URL: {link}")
        body = item.get("body", "")
        if body:
            text = re.sub(r"<[^>]+>", "", body)[:500].strip()
            if text:
                lines.append(f"Preview: {text}...")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
