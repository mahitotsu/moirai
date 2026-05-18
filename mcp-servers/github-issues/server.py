from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from client import GitHubIssuesClient
from mcp.server.fastmcp import FastMCP
from pydantic_settings import BaseSettings


class _Settings(BaseSettings):
    github_token: str = ""


_client: GitHubIssuesClient | None = None


def _get_client() -> GitHubIssuesClient:
    global _client
    if _client is None:
        token = _Settings().github_token or None
        _client = GitHubIssuesClient(token=token)
    return _client


@asynccontextmanager
async def _lifespan(_: FastMCP) -> AsyncGenerator[None, None]:
    yield
    if _client is not None:
        await _client.aclose()


mcp = FastMCP("github-issues-mcp", lifespan=_lifespan)


@mcp.tool()
async def search_github_issues(
    query: str,
    repos: list[str] | None = None,
    num_results: int = 5,
) -> str:
    """Search GitHub Issues and Pull Requests for bug reports and discussions related to a problem.

    Args:
        query: The search query describing the issue or bug.
        repos: Optional list of repositories to restrict search to
            (e.g. ["django/django", "psf/requests"]).
        num_results: Number of results to return (default 5, max 10).

    Returns:
        Formatted text with matching issues, their state, labels, and URLs.
    """
    try:
        items = await _get_client().search_issues(
            query, repos=repos, num_results=min(num_results, 10)
        )
    except Exception as e:
        raise ValueError(f"GitHub Issues search failed: {e}") from e

    if not items:
        return "No issues found for the given query."

    lines: list[str] = []
    for item in items:
        title = item.get("title", "Untitled")
        state = item.get("state", "unknown")
        html_url = item.get("html_url", "")
        body = (item.get("body") or "")[:400].strip()
        labels = [lbl.get("name", "") for lbl in item.get("labels", [])]
        comments = item.get("comments", 0)
        lines.append(f"### {title}")
        label_str = ", ".join(labels) or "none"
        lines.append(f"State: {state} | Comments: {comments} | Labels: {label_str}")
        lines.append(f"URL: {html_url}")
        if body:
            lines.append(f"Preview: {body}...")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
