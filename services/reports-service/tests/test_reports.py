from __future__ import annotations

import time

from app.main import app, get_repository
from app.models import ReportCreate
from app.repository import ReportRepository
from fastapi.testclient import TestClient


def _client(repo: ReportRepository) -> TestClient:
    app.dependency_overrides[get_repository] = lambda: repo
    return TestClient(app)


def test_health(repo: ReportRepository) -> None:
    c = _client(repo)
    resp = c.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    app.dependency_overrides.clear()


def test_create_report(repo: ReportRepository) -> None:
    data = ReportCreate(
        title="Weekly Incident Summary",
        type="incident-summary",
        summary="3 incidents resolved this week.",
        details="## Details\n- 2 network, 1 database",
    )
    report = repo.create(data)
    assert report.report_id
    assert report.title == "Weekly Incident Summary"
    assert report.type == "incident-summary"
    assert report.created_at


def test_get_report(repo: ReportRepository) -> None:
    created = repo.create(
        ReportCreate(title="Cost", type="cost", summary="Low cost.", details="$0.01")
    )
    fetched = repo.get(created.report_id)
    assert fetched is not None
    assert fetched.report_id == created.report_id
    assert fetched.type == "cost"


def test_get_report_not_found(repo: ReportRepository) -> None:
    assert repo.get("nonexistent-id") is None


def test_list_by_type(repo: ReportRepository) -> None:
    repo.create(
        ReportCreate(title="Ops 1", type="operational", summary="All good.", details="OK")
    )
    time.sleep(1)  # GSI eventual consistency
    results = repo.list_by_type("operational")
    assert len(results) >= 1
    assert all(r.type == "operational" for r in results)


def test_scan_returns_reports(repo: ReportRepository) -> None:
    repo.create(
        ReportCreate(title="Custom", type="custom", summary="Custom report.", details="...")
    )
    results = repo.scan()
    assert len(results) >= 1


def test_api_create_and_get(repo: ReportRepository) -> None:
    c = _client(repo)
    resp = c.post(
        "/reports",
        json={
            "title": "API test",
            "type": "cost",
            "summary": "Test summary.",
            "details": "Test details.",
        },
    )
    assert resp.status_code == 201
    report_id = resp.json()["report_id"]

    resp = c.get(f"/reports/{report_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "API test"
    app.dependency_overrides.clear()


def test_api_404(repo: ReportRepository) -> None:
    c = _client(repo)
    resp = c.get("/reports/does-not-exist")
    assert resp.status_code == 404
    app.dependency_overrides.clear()


def test_api_list(repo: ReportRepository) -> None:
    c = _client(repo)
    resp = c.get("/reports")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    app.dependency_overrides.clear()
