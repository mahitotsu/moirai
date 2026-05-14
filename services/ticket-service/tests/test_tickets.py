from __future__ import annotations

from collections.abc import Generator

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


def test_update_nonexistent(repo: TicketRepository) -> None:
    result = repo.update("no-such-id", TicketUpdate(status="closed"))
    assert result is None


def test_list_by_status(repo: TicketRepository) -> None:
    repo.create(TicketCreate(title="Open 1", description="d", category="database", severity="low"))
    repo.create(TicketCreate(title="Open 2", description="d", category="network", severity="low"))
    tickets = repo.list_by_status("open")
    assert len(tickets) >= 2
    assert all(t.status == "open" for t in tickets)


def test_list_by_category(repo: TicketRepository) -> None:
    repo.create(TicketCreate(title="Cat test", description="d", category="other", severity="low"))
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
