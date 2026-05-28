from __future__ import annotations

from typing import Literal

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


mcp = FastMCP(
    "github-issues-mcp",
    host="0.0.0.0",
    port=8000,
    stateless_http=True,
)


@mcp.tool()
async def search_github_issues(
    service: str,
    error_type: str,
    repos: list[str] | None = None,
    state: Literal["open", "closed", "all"] = "all",
    labels: list[str] | None = None,
    num_results: int = 5,
) -> str:
    """Search GitHub Issues for bug reports and discussions related to a technical failure.

    Args:
        service: The service or library where the failure occurred
            (e.g. "AWS Lambda", "boto3", "aws-cdk").
        error_type: The type of failure or error observed
            (e.g. "timeout", "InvalidParameterException", "connection refused").
        repos: Optional list of repositories to restrict search to
            (e.g. ["boto/boto3", "aws/aws-cdk"]).
        state: Filter by issue state — "open", "closed", or "all" (default).
        labels: Optional issue labels to filter by (e.g. ["bug", "regression"]).
        num_results: Number of results to return (default 5, max 10).

    Returns:
        Formatted text with matching issues, their state, labels, and URLs.
    """
    try:
        items = await _get_client().search_issues(
            service=service,
            error_type=error_type,
            repos=repos,
            state=state,
            labels=labels,
            num_results=min(num_results, 10),
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
    mcp.run(transport="streamable-http")
