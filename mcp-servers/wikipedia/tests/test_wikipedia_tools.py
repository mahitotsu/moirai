from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.modules.pop("client", None)
sys.modules.pop("server", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server as _wiki_server  # モジュール参照を固定
from server import get_wikipedia_article, search_wikipedia  # noqa: E402


@pytest.fixture
def mock_wiki_client():
    with patch.object(_wiki_server, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client
        yield mock_client


async def test_search_returns_formatted_list(mock_wiki_client):
    mock_wiki_client.search.return_value = [
        {
            "title": "PostgreSQL",
            "snippet": 'PostgreSQL is an <span class="searchmatch">open-source</span> database.',
        }
    ]
    result = await search_wikipedia("postgresql")

    assert "PostgreSQL" in result
    assert "open-source database" in result
    # HTML タグはクライアント層で除去されていることを確認
    assert '<span class="searchmatch">' not in result


async def test_search_no_results_returns_helpful_message(mock_wiki_client):
    mock_wiki_client.search.return_value = []
    result = await search_wikipedia("xyzzy no match")

    assert "No Wikipedia articles found" in result


async def test_search_api_error_raises_user_friendly_value_error(mock_wiki_client):
    """外部 API 障害はスタックトレースではなく ValueError でラップして返す。"""
    mock_wiki_client.search.side_effect = Exception("network error")

    with pytest.raises(ValueError, match="Wikipedia search failed"):
        await search_wikipedia("some query")


async def test_get_article_returns_formatted_content(mock_wiki_client):
    mock_wiki_client.get_summary.return_value = {
        "title": "PostgreSQL",
        "description": "Open-source relational database",
        "extract": "PostgreSQL is a free and open-source relational database system.",
    }
    result = await get_wikipedia_article("PostgreSQL")

    assert "PostgreSQL" in result
    assert "Open-source relational database" in result
    assert "free and open-source" in result


async def test_get_article_empty_extract_returns_not_found_message(mock_wiki_client):
    mock_wiki_client.get_summary.return_value = {"title": "Unknown", "extract": ""}
    result = await get_wikipedia_article("Unknown")

    assert "No content found" in result


async def test_get_article_api_error_raises_user_friendly_value_error(mock_wiki_client):
    mock_wiki_client.get_summary.side_effect = Exception("404 not found")

    with pytest.raises(ValueError, match="Failed to retrieve Wikipedia article"):
        await get_wikipedia_article("NonExistentPage")
