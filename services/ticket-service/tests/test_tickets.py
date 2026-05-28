from __future__ import annotations

import json
import time
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from app.main import app, get_repository
from app.models import TicketCreate, TicketUpdate
from app.repository import TicketRepository
from fastapi.testclient import TestClient


@pytest.fixture
def client(repo: TicketRepository) -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_repository] = lambda: repo
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_ticket(repo: TicketRepository) -> None:
    data = TicketCreate(
        title="DB connection timeout",
        description="PostgreSQL connections all timing out",
        category="database",
        severity="high",
    )
    ticket = repo.create(data)
    assert ticket.ticket_id
    assert ticket.status == "open"
    assert ticket.title == "DB connection timeout"
    assert ticket.category == "database"
    assert ticket.resolved_at is None


def test_get_ticket(repo: TicketRepository) -> None:
    created = repo.create(
        TicketCreate(title="Test", description="desc", category="network", severity="low")
    )
    fetched = repo.get(created.ticket_id)
    assert fetched is not None
    assert fetched.ticket_id == created.ticket_id


def test_get_ticket_not_found(repo: TicketRepository) -> None:
    assert repo.get("nonexistent-id") is None


def test_update_status(repo: TicketRepository) -> None:
    created = repo.create(
        TicketCreate(
            title="Memory spike",
            description="90% usage",
            category="memory",
            severity="high",
        )
    )
    updated = repo.update(created.ticket_id, TicketUpdate(status="investigating"))
    assert updated is not None
    assert updated.status == "investigating"
    assert updated.resolved_at is None


def test_resolve_ticket(repo: TicketRepository) -> None:
    created = repo.create(
        TicketCreate(
            title="Deploy failure",
            description="500s after deploy",
            category="deploy",
            severity="critical",
        )
    )
    updated = repo.update(
        created.ticket_id,
        TicketUpdate(status="resolved", resolution="Rolled back to previous version"),
    )
    assert updated is not None
    assert updated.status == "resolved"
    assert updated.resolution == "Rolled back to previous version"
    assert updated.resolved_at is not None


def test_lesson_learned_field(repo: TicketRepository) -> None:
    created = repo.create(
        TicketCreate(
            title="Memory leak",
            description="OOM after 2 hours",
            category="memory",
            severity="high",
        )
    )
    updated = repo.update(
        created.ticket_id,
        TicketUpdate(
            status="resolved",
            resolution="Restarted service and patched memory leak",
            lesson_learned="Always add memory limits to containers to prevent OOM cascades.",
        ),
    )
    assert updated is not None
    expected = "Always add memory limits to containers to prevent OOM cascades."
    assert updated.lesson_learned == expected
    assert updated.resolution == "Restarted service and patched memory leak"


def test_update_nonexistent(repo: TicketRepository) -> None:
    result = repo.update("no-such-id", TicketUpdate(status="closed"))
    assert result is None


def test_list_by_status(repo: TicketRepository) -> None:
    repo.create(TicketCreate(title="Open 1", description="d", category="database", severity="low"))
    repo.create(TicketCreate(title="Open 2", description="d", category="network", severity="low"))
    time.sleep(3)  # GSI eventual consistency
    tickets = repo.list_by_status("open")
    assert len(tickets) >= 2
    assert all(t.status == "open" for t in tickets)


def test_list_by_category(repo: TicketRepository) -> None:
    repo.create(TicketCreate(title="Cat test", description="d", category="other", severity="low"))
    time.sleep(3)  # GSI eventual consistency
    tickets = repo.list_by_category("other")
    assert len(tickets) >= 1
    assert all(t.category == "other" for t in tickets)


def test_api_create_and_get(client: TestClient) -> None:
    resp = client.post(
        "/tickets",
        json={
            "title": "API test",
            "description": "via REST",
            "category": "database",
            "severity": "medium",
        },
    )
    assert resp.status_code == 201
    ticket_id = resp.json()["ticket_id"]

    resp = client.get(f"/tickets/{ticket_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "API test"


def test_api_404(client: TestClient) -> None:
    resp = client.get("/tickets/does-not-exist")
    assert resp.status_code == 404


def test_api_patch(client: TestClient) -> None:
    create_resp = client.post(
        "/tickets",
        json={"title": "Patch test", "description": "d", "category": "network", "severity": "high"},
    )
    ticket_id = create_resp.json()["ticket_id"]

    patch_resp = client.patch(
        f"/tickets/{ticket_id}",
        json={"status": "resolved", "resolution": "Fixed"},
    )
    assert patch_resp.status_code == 200
    body = patch_resp.json()
    assert body["status"] == "resolved"
    assert body["resolved_at"] is not None


def test_create_ticket_has_initial_history(repo: TicketRepository) -> None:
    ticket = repo.create(
        TicketCreate(title="History init test", description="d", category="other", severity="low")
    )
    assert len(ticket.history) == 1
    entry = ticket.history[0]
    assert entry.status == "open"
    assert entry.actor == "system"
    assert entry.note is None
    assert entry.timestamp


def test_update_appends_history_entry(repo: TicketRepository) -> None:
    ticket = repo.create(
        TicketCreate(title="History update test", description="d", category="other", severity="low")
    )
    updated = repo.update(
        ticket.ticket_id,
        TicketUpdate(
            status="investigating",
            note="Starting root cause analysis",
            actor="triage-agent",
        ),
    )
    assert updated is not None
    assert len(updated.history) == 2
    last = updated.history[-1]
    assert last.status == "investigating"
    assert last.note == "Starting root cause analysis"
    assert last.actor == "triage-agent"


def test_resolve_appends_history_with_actor(repo: TicketRepository) -> None:
    ticket = repo.create(
        TicketCreate(
            title="Resolve history test", description="d", category="deploy", severity="critical"
        )
    )
    repo.update(ticket.ticket_id, TicketUpdate(status="investigating", actor="triage-agent"))
    resolved = repo.update(
        ticket.ticket_id,
        TicketUpdate(
            status="resolved",
            resolution="Rolled back",
            note="Resolved via rollback",
            actor="resolution-agent",
        ),
    )
    assert resolved is not None
    assert len(resolved.history) == 3
    assert resolved.history[0].status == "open"
    assert resolved.history[1].status == "investigating"
    assert resolved.history[2].status == "resolved"
    assert resolved.history[2].actor == "resolution-agent"


def test_non_status_update_does_not_append_history(repo: TicketRepository) -> None:
    ticket = repo.create(
        TicketCreate(title="No history change", description="d", category="other", severity="low")
    )
    updated = repo.update(ticket.ticket_id, TicketUpdate(resolution="Some note"))
    assert updated is not None
    assert len(updated.history) == 1  # only initial open entry


def test_duplicate_status_update_does_not_append_history(repo: TicketRepository) -> None:
    """Repeated update with same status (e.g. Streams retry) must not create duplicate entries."""
    ticket = repo.create(
        TicketCreate(title="Dedup test", description="d", category="other", severity="low")
    )
    first = repo.update(ticket.ticket_id, TicketUpdate(status="resolved", resolution="Fixed"))
    assert first is not None
    assert len(first.history) == 2  # open + resolved

    # Simulate a DynamoDB Streams retry re-invoking the same update
    second = repo.update(ticket.ticket_id, TicketUpdate(status="resolved", resolution="Fixed"))
    assert second is not None
    assert len(second.history) == 2  # must NOT grow to 3


# ── search_similar ─────────────────────────────────────────────────────────

def _make_search_repo(dynamodb_client, table_name: str) -> TicketRepository:
    fake_embedding = [0.1] * 1024
    mock_br = MagicMock()
    mock_br.invoke_model.return_value = {
        "body": MagicMock(read=lambda: json.dumps({"embedding": fake_embedding}).encode())
    }
    mock_sv = MagicMock()
    mock_sv.query_vectors.return_value = {
        "vectors": [
            {
                "key": "t-abc",
                "distance": 0.12,
                "metadata": {
                    "ticket_id": "t-abc",
                    "title": "API timeout",
                    "category": "network",
                    "severity": "high",
                },
            }
        ]
    }
    return TicketRepository(
        dynamodb_client,
        table_name,
        s3vectors_client=mock_sv,
        bedrock_runtime_client=mock_br,
        vector_bucket_name="agora-test-vectors",
        vector_index_name="tickets",
    )


def test_search_similar_returns_results(repo: TicketRepository) -> None:
    search_repo = _make_search_repo(repo._client, repo._table)
    results = search_repo.search_similar("database connection issue", top_k=3)
    assert len(results) == 1
    assert results[0].ticket_id == "t-abc"
    assert results[0].title == "API timeout"
    assert results[0].category == "network"
    assert results[0].distance == 0.12


def test_search_similar_without_vector_config_returns_empty(repo: TicketRepository) -> None:
    results = repo.search_similar("anything")
    assert results == []


def test_search_endpoint_returns_similar_tickets(
    repo: TicketRepository, client: TestClient
) -> None:
    search_repo = _make_search_repo(repo._client, repo._table)
    app.dependency_overrides[get_repository] = lambda: search_repo
    try:
        resp = client.get("/tickets/search", params={"q": "slow query"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["ticket_id"] == "t-abc"
    finally:
        app.dependency_overrides[get_repository] = lambda: repo
