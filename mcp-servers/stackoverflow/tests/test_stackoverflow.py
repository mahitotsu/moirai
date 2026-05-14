from __future__ import annotations

import os
import sys

# Each MCP server has its own client.py — clear any cached version before importing.
sys.modules.pop("client", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest
import pytest_httpx
from client import StackOverflowClient


@pytest.fixture
def client():
    return StackOverflowClient()


@pytest.mark.asyncio
async def test_search_returns_results(
    httpx_mock: pytest_httpx.HTTPXMock, client: StackOverflowClient
):
    httpx_mock.add_response(
        json={
            "items": [
                {
                    "title": "PostgreSQL connection timeout",
                    "score": 42,
                    "is_answered": True,
                    "answer_count": 3,
                    "link": "https://stackoverflow.com/questions/1",
                    "body": "<p>Check max_connections setting</p>",
                }
            ],
            "has_more": False,
        },
    )
    results = await client.search("postgresql timeout")
    assert len(results) == 1
    assert results[0]["title"] == "PostgreSQL connection timeout"
    assert results[0]["score"] == 42


@pytest.mark.asyncio
async def test_search_with_tags(
    httpx_mock: pytest_httpx.HTTPXMock, client: StackOverflowClient
):
    httpx_mock.add_response(json={"items": [], "has_more": False})
    results = await client.search("timeout", tags=["postgresql"])
    assert results == []


@pytest.mark.asyncio
async def test_search_http_error(
    httpx_mock: pytest_httpx.HTTPXMock, client: StackOverflowClient
):
    httpx_mock.add_response(status_code=500)
    with pytest.raises(httpx.HTTPStatusError):
        await client.search("some query")
