from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.modules.pop("client", None)
sys.modules.pop("server", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server as _so_server  # モジュール参照を固定。sys.modules["server"] が変わっても影響しない
from server import search_stackoverflow  # noqa: E402


@pytest.fixture
def mock_so_client():
    with patch.object(_so_server, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client
        yield mock_client


async def test_search_returns_formatted_markdown(mock_so_client):
    mock_so_client.search.return_value = [
        {
            "title": "Connection pool exhausted",
            "score": 42,
            "is_answered": True,
            "answer_count": 3,
            "link": "https://stackoverflow.com/questions/1",
            "body": "<p>Increase max_connections</p>",
        }
    ]
    result = await search_stackoverflow("PostgreSQL", "connection pool exhausted")

    assert "Connection pool exhausted" in result
    assert "Score: 42" in result
    assert "https://stackoverflow.com/questions/1" in result
    assert "Answers: 3" in result


async def test_search_strips_html_from_body(mock_so_client):
    mock_so_client.search.return_value = [
        {
            "title": "Test",
            "score": 1,
            "is_answered": False,
            "answer_count": 0,
            "link": "https://stackoverflow.com/questions/2",
            "body": "<p><strong>Use</strong> <em>pooling</em></p>",
        }
    ]
    result = await search_stackoverflow("PostgreSQL", "connection pooling")

    assert "<p>" not in result
    assert "<strong>" not in result
    assert "Use" in result


async def test_search_no_results_returns_helpful_message(mock_so_client):
    mock_so_client.search.return_value = []
    result = await search_stackoverflow("UnknownService", "xyzzy no match")

    assert "No results found" in result


async def test_search_api_error_raises_user_friendly_value_error(mock_so_client):
    """外部 API 障害はスタックトレースではなく ValueError でラップして返す。"""
    mock_so_client.search.side_effect = Exception("connection reset")

    with pytest.raises(ValueError, match="Stack Overflow search failed"):
        await search_stackoverflow("SomeService", "some error")


async def test_num_results_capped_at_10(mock_so_client):
    mock_so_client.search.return_value = []
    await search_stackoverflow("SomeService", "some error", num_results=99)

    assert mock_so_client.search.call_args.kwargs["num_results"] <= 10
