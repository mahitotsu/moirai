from __future__ import annotations

import time
from collections.abc import Callable, Generator

import pytest
from app.main import app, get_repository
from app.models import AssetCreate, AssetUpdate
from app.repository import AssetRepository
from fastapi.testclient import TestClient


def _wait_for_gsi[T](
    fn: Callable[[], list[T]], *, expected: int = 1, retries: int = 5, delay: float = 1.0
) -> list[T]:
    """GSI の結果整合性を考慮してリトライする。書き込み直後の GSI クエリに使用する。"""
    result: list[T] = []
    for _ in range(retries):
        result = fn()
        if len(result) >= expected:
            return result
        time.sleep(delay)
    return result


@pytest.fixture
def client(repo: AssetRepository) -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_repository] = lambda: repo
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_asset(repo: AssetRepository) -> None:
    data = AssetCreate(
        name="prod-postgres-01",
        type="database",
        environment="production",
        status="healthy",
        description="Primary PostgreSQL cluster",
    )
    asset = repo.create(data)
    assert asset.asset_id
    assert asset.name == "prod-postgres-01"
    assert asset.type == "database"
    assert asset.environment == "production"
    assert asset.status == "healthy"
    assert asset.description == "Primary PostgreSQL cluster"
    assert asset.metadata is None


def test_create_asset_with_metadata(repo: AssetRepository) -> None:
    data = AssetCreate(
        name="prod-api-01",
        type="service",
        environment="production",
        metadata={"port": 8080, "replicas": 3},
    )
    asset = repo.create(data)
    assert asset.metadata == {"port": 8080, "replicas": 3}


def test_get_asset(repo: AssetRepository) -> None:
    created = repo.create(
        AssetCreate(name="staging-nginx", type="server", environment="staging")
    )
    fetched = repo.get(created.asset_id)
    assert fetched is not None
    assert fetched.asset_id == created.asset_id
    assert fetched.name == "staging-nginx"


def test_get_asset_not_found(repo: AssetRepository) -> None:
    assert repo.get("nonexistent-id") is None


def test_update_status(repo: AssetRepository) -> None:
    created = repo.create(
        AssetCreate(name="prod-cache", type="service", environment="production")
    )
    updated = repo.update(created.asset_id, AssetUpdate(status="degraded"))
    assert updated is not None
    assert updated.status == "degraded"
    assert updated.name == "prod-cache"


def test_update_metadata(repo: AssetRepository) -> None:
    created = repo.create(
        AssetCreate(name="prod-lb", type="network", environment="production")
    )
    updated = repo.update(
        created.asset_id,
        AssetUpdate(metadata={"backend_count": 5, "algorithm": "round_robin"}),
    )
    assert updated is not None
    assert updated.metadata == {"backend_count": 5, "algorithm": "round_robin"}


def test_update_nonexistent(repo: AssetRepository) -> None:
    result = repo.update("no-such-id", AssetUpdate(status="down"))
    assert result is None


def test_list_by_type(repo: AssetRepository) -> None:
    repo.create(AssetCreate(name="db-replica-1", type="database", environment="production"))
    repo.create(AssetCreate(name="db-replica-2", type="database", environment="staging"))
    assets = _wait_for_gsi(lambda: repo.list_by_type("database"), expected=2)
    assert len(assets) >= 2
    assert all(a.type == "database" for a in assets)


def test_list_by_environment(repo: AssetRepository) -> None:
    repo.create(AssetCreate(name="dev-server-1", type="server", environment="development"))
    assets = _wait_for_gsi(lambda: repo.list_by_environment("development"), expected=1)
    assert len(assets) >= 1
    assert all(a.environment == "development" for a in assets)


def test_api_create_and_get(client: TestClient) -> None:
    resp = client.post(
        "/assets",
        json={
            "name": "api-server-01",
            "type": "server",
            "environment": "production",
            "status": "healthy",
        },
    )
    assert resp.status_code == 201
    asset_id = resp.json()["asset_id"]

    resp = client.get(f"/assets/{asset_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "api-server-01"


def test_api_404(client: TestClient) -> None:
    resp = client.get("/assets/does-not-exist")
    assert resp.status_code == 404


def test_api_patch(client: TestClient) -> None:
    create_resp = client.post(
        "/assets",
        json={"name": "prod-db", "type": "database", "environment": "production"},
    )
    asset_id = create_resp.json()["asset_id"]

    patch_resp = client.patch(f"/assets/{asset_id}", json={"status": "down"})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "down"
