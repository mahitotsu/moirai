from __future__ import annotations

import httpx

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_REST = "https://en.wikipedia.org/api/rest_v1"
TIMEOUT = 10.0


class WikipediaClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=TIMEOUT,
            headers={"User-Agent": "agora-mcp/1.0 (github.com/agora)"},
        )

    async def search(self, query: str, num_results: int = 5) -> list[dict]:
        params: dict[str, str | int] = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": num_results,
            "format": "json",
            "utf8": 1,
        }
        response = await self._http.get(WIKIPEDIA_API, params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("query", {}).get("search", [])

    async def get_summary(self, title: str) -> dict:
        encoded = title.replace(" ", "_")
        response = await self._http.get(f"{WIKIPEDIA_REST}/page/summary/{encoded}")
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        await self._http.aclose()
