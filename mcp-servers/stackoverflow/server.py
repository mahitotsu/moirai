from __future__ import annotations

import re

from client import StackOverflowClient
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "stackoverflow-mcp",
    host="0.0.0.0",
    port=8000,
    stateless_http=True,
)
_client: StackOverflowClient | None = None


def _get_client() -> StackOverflowClient:
    global _client
    if _client is None:
        _client = StackOverflowClient()
    return _client


@mcp.tool()
async def search_stackoverflow(
    service: str,
    error_type: str,
    tags: list[str] | None = None,
    num_results: int = 5,
) -> str:
    """技術的な障害に関連する質問と回答をStack Overflowで検索する。

    Args:
        service: 障害が発生したサービスまたは技術
            （例："AWS Lambda"、"PostgreSQL"、"Python boto3"）。
        error_type: 観測された障害またはエラーの種類
            （例："timeout"、"connection refused"、"memory limit exceeded"、"permission denied"）。
        tags: 結果を絞り込むSOタグ（省略可）（例：["aws-lambda", "python"]）。
            明示的に不明な場合はサービス名から推測する。
        num_results: 返す結果数（デフォルト5、最大10）。

    Returns:
        上位の質問・スコア・承認済み回答を含むフォーマット済みテキスト。
    """
    try:
        items = await _get_client().search(
            service=service, error_type=error_type, tags=tags, num_results=min(num_results, 10)
        )
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
