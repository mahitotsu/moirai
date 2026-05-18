from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.modules.pop("client", None)
sys.modules.pop("server", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server as _gh_server  # モジュール参照を固定
from server import search_github_issues  # noqa: E402


@pytest.fixture
def mock_gh_client():
    with patch.object(_gh_server, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client
        yield mock_client


async def test_search_returns_formatted_markdown(mock_gh_client):
    mock_gh_client.search_issues.return_value = [
        {
            "title": "Connection pool exhausted",
            "state": "open",
            "html_url": "https://github.com/org/repo/issues/1",
            "body": "Connections are exhausted in production.",
            "labels": [{"name": "bug"}, {"name": "database"}],
            "comments": 5,
        }
    ]
    result = await search_github_issues("connection pool")

    assert "Connection pool exhausted" in result
    assert "State: open" in result
    assert "https://github.com/org/repo/issues/1" in result
    assert "bug" in result
    assert "Comments: 5" in result


async def test_search_no_results_returns_helpful_message(mock_gh_client):
    mock_gh_client.search_issues.return_value = []
    result = await search_github_issues("xyzzy no match")

    assert "No issues found" in result


async def test_search_api_error_raises_user_friendly_value_error(mock_gh_client):
    """外部 API 障害はスタックトレースではなく ValueError でラップして返す。"""
    mock_gh_client.search_issues.side_effect = Exception("rate limit exceeded")

    with pytest.raises(ValueError, match="GitHub Issues search failed"):
        await search_github_issues("some query")


async def test_body_truncated_in_preview(mock_gh_client):
    """issue body が長い場合、プレビューとして切り詰めて返す。"""
    long_body = "A" * 1000
    mock_gh_client.search_issues.return_value = [
        {
            "title": "Long issue",
            "state": "open",
            "html_url": "https://github.com/org/repo/issues/2",
            "body": long_body,
            "labels": [],
            "comments": 0,
        }
    ]
    result = await search_github_issues("long")

    assert len(result) < len(long_body)
