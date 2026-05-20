from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from client import WikipediaClient
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings

_client: WikipediaClient | None = None


def _get_client() -> WikipediaClient:
    global _client
    if _client is None:
        _client = WikipediaClient()
    return _client


@asynccontextmanager
async def _lifespan(_: FastMCP) -> AsyncGenerator[None, None]:
    yield
    if _client is not None:
        await _client.aclose()


mcp = FastMCP(
    "wikipedia-mcp",
    lifespan=_lifespan,
    host="0.0.0.0",
    port=8080,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
async def search_wikipedia(query: str, num_results: int = 5) -> str:
    """Search Wikipedia for articles related to a topic or technology concept.

    Args:
        query: The topic or concept to search for.
        num_results: Number of articles to return (default 5, max 10).

    Returns:
        Formatted list of matching Wikipedia article titles and snippets.
    """
    try:
        results = await _get_client().search(query, num_results=min(num_results, 10))
    except Exception as e:
        raise ValueError(f"Wikipedia search failed: {e}") from e

    if not results:
        return "No Wikipedia articles found for the given query."

    lines: list[str] = []
    for result in results:
        title = result.get("title", "Untitled")
        raw = result.get("snippet", "")
        snippet = raw.replace('<span class="searchmatch">', "").replace("</span>", "")
        lines.append(f"- **{title}**: {snippet}")

    return "\n".join(lines)


@mcp.tool()
async def get_wikipedia_article(title: str) -> str:
    """Retrieve a summary of a specific Wikipedia article by its exact title.

    Args:
        title: The exact title of the Wikipedia article (e.g. "PostgreSQL").

    Returns:
        The article's summary text with key information.
    """
    try:
        data = await _get_client().get_summary(title)
    except Exception as e:
        raise ValueError(f"Failed to retrieve Wikipedia article '{title}': {e}") from e

    extract = data.get("extract", "")
    if not extract:
        return f"No content found for Wikipedia article '{title}'."

    description = data.get("description", "")
    header = f"# {title}"
    if description:
        header += f"\n_{description}_"

    return f"{header}\n\n{extract}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
