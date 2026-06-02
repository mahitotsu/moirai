from __future__ import annotations

import httpx

STACK_API_BASE = "https://api.stackexchange.com/2.3"
TIMEOUT = 10.0


class StackOverflowClient:
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key
        self._http = httpx.AsyncClient(timeout=TIMEOUT)

    async def search(
        self,
        query: str | None = None,
        service: str = "",
        error_type: str = "",
        tags: list[str] | None = None,
        num_results: int = 5,
    ) -> list[dict]:
        q = query or f"{service} {error_type}".strip()
        params: dict = {
            "order": "desc",
            "sort": "relevance",
            "q": q,
            "site": "stackoverflow",
            "pagesize": num_results,
            "filter": "withbody",
        }
        if tags:
            params["tagged"] = ";".join(tags)
        if self._api_key:
            params["key"] = self._api_key

        response = await self._http.get(f"{STACK_API_BASE}/search/advanced", params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("items", [])

    async def aclose(self) -> None:
        await self._http.aclose()
