from __future__ import annotations

from typing import Annotated

import boto3
from fastapi import Depends, FastAPI, HTTPException

from app.models import Asset, AssetCreate, AssetUpdate
from app.repository import AssetRepository
from app.settings import Settings

settings = Settings()

# FastAPI auto-exposes /openapi.json — used by AgentCore Gateway for MCP tool generation
app = FastAPI(title="Asset Service")


def get_repository() -> AssetRepository:
    client = boto3.client("dynamodb", region_name=settings.aws_region)
    return AssetRepository(client, settings.table_name)


RepoDep = Annotated[AssetRepository, Depends(get_repository)]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/assets", response_model=Asset, status_code=201)
def create_asset(data: AssetCreate, repo: RepoDep) -> Asset:
    return repo.create(data)


@app.get("/assets", response_model=list[Asset])
def list_assets(
    repo: RepoDep,
    type: str | None = None,
    environment: str | None = None,
    limit: int = 50,
) -> list[Asset]:
    if type:
        return repo.list_by_type(type, limit)
    if environment:
        return repo.list_by_environment(environment, limit)
    return repo.scan(limit)


@app.get("/assets/{asset_id}", response_model=Asset)
def get_asset(asset_id: str, repo: RepoDep) -> Asset:
    asset = repo.get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@app.patch("/assets/{asset_id}", response_model=Asset)
def update_asset(asset_id: str, data: AssetUpdate, repo: RepoDep) -> Asset:
    asset = repo.update(asset_id, data)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset
