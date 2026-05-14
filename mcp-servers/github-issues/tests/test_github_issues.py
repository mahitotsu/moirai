from __future__ import annotations

import os
import sys

# Each MCP server has its own client.py — clear any cached version before importing.
sys.modules.pop("client", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest
import pytest_httpx
from client import GitHubIssuesClient


@pytest.fixture
def client():
    return GitHubIssuesClient(token=None)


@pytest.mark.asyncio
async def test_search_issues_returns_results(
    httpx_mock: pytest_httpx.HTTPXMock, client: GitHubIssuesClient
):
    httpx_mock.add_response(
        json={
            "total_count": 1,
            "incomplete_results": False,
            "items": [
                {
                    "title": "Connection pool exhausted",
                    "state": "open",
                    "html_url": "https://github.com/org/repo/issues/1",
                    "body": "Connection pool exhausted errors in production.",
                    "labels": [{"name": "bug"}, {"name": "database"}],
                    "comments": 5,
                }
            ],
        },
    )
    results = await client.search_issues("connection pool exhausted")
    assert len(results) == 1
    assert results[0]["title"] == "Connection pool exhausted"
    assert results[0]["state"] == "open"


@pytest.mark.asyncio
async def test_search_issues_with_repos(
    httpx_mock: pytest_httpx.HTTPXMock, client: GitHubIssuesClient
):
    httpx_mock.add_response(
        json={"total_count": 0, "incomplete_results": False, "items": []}
    )
    results = await client.search_issues("timeout", repos=["psf/requests"])
    assert results == []


@pytest.mark.asyncio
async def test_search_issues_http_error(
    httpx_mock: pytest_httpx.HTTPXMock, client: GitHubIssuesClient
):
    httpx_mock.add_response(status_code=422)
    with pytest.raises(httpx.HTTPStatusError):
        await client.search_issues("some query")
