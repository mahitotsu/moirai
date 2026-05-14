from __future__ import annotations

import os
import sys

# Each MCP server has its own client.py — clear any cached version before importing.
sys.modules.pop("client", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest
import pytest_httpx
from client import WikipediaClient


@pytest.fixture
def client():
    return WikipediaClient()


@pytest.mark.asyncio
async def test_search_returns_results(
    httpx_mock: pytest_httpx.HTTPXMock, client: WikipediaClient
):
    httpx_mock.add_response(
        json={
            "query": {
                "search": [
                    {
                        "title": "PostgreSQL",
                        "snippet": (
                            'PostgreSQL is an <span class="searchmatch">open-source</span>'
                            " relational database."
                        ),
                    }
                ]
            }
        },
    )
    results = await client.search("postgresql")
    assert len(results) == 1
    assert results[0]["title"] == "PostgreSQL"


@pytest.mark.asyncio
async def test_get_summary_returns_extract(
    httpx_mock: pytest_httpx.HTTPXMock, client: WikipediaClient
):
    httpx_mock.add_response(
        json={
            "title": "PostgreSQL",
            "description": "Open-source relational database",
            "extract": "PostgreSQL is a free and open-source relational database.",
        },
    )
    data = await client.get_summary("PostgreSQL")
    assert data["extract"] != ""


@pytest.mark.asyncio
async def test_get_summary_not_found(
    httpx_mock: pytest_httpx.HTTPXMock, client: WikipediaClient
):
    httpx_mock.add_response(status_code=404)
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_summary("NonExistentXXX")


@pytest.mark.asyncio
async def test_search_empty_results(
    httpx_mock: pytest_httpx.HTTPXMock, client: WikipediaClient
):
    httpx_mock.add_response(json={"query": {"search": []}})
    results = await client.search("zzznomatch")
    assert results == []
