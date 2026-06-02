from __future__ import annotations

import httpx

GITHUB_API_BASE = "https://api.github.com"
TIMEOUT = 10.0


class GitHubIssuesClient:
    def __init__(self, token: str | None = None) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.AsyncClient(timeout=TIMEOUT, headers=headers)

    async def search_issues(
        self,
        query: str | None = None,
        service: str = "",
        error_type: str = "",
        repos: list[str] | None = None,
        state: str = "all",
        labels: list[str] | None = None,
        num_results: int = 5,
    ) -> list[dict]:
        base = query or f"{service} {error_type}".strip()
        q = f"{base} is:issue"
        if state != "all":
            q += f" is:{state}"
        if repos:
            q += " " + " ".join(f"repo:{r}" for r in repos)
        if labels:
            q += " " + " ".join(f'label:"{lbl}"' for lbl in labels)

        params: dict[str, str | int] = {
            "q": q,
            "per_page": num_results,
            "sort": "best-match",
            "order": "desc",
        }
        response = await self._http.get(f"{GITHUB_API_BASE}/search/issues", params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("items", [])

    async def aclose(self) -> None:
        await self._http.aclose()
