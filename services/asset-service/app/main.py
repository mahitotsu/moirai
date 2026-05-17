from __future__ import annotations

from typing import Annotated

import boto3
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.models import Asset, AssetCreate, AssetUpdate
from app.repository import AssetRepository
from app.settings import Settings

settings = Settings()  # type: ignore[call-arg]

# FastAPI auto-exposes /openapi.json — used by AgentCore Gateway for MCP tool generation
app = FastAPI(title="Asset Service")


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if settings.api_key and request.url.path not in ("/health", "/openapi.json", "/docs", "/redoc"):
        key = request.headers.get("x-api-key", "")
        if key != settings.api_key:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)


def get_repository() -> AssetRepository:
    client = boto3.client("dynamodb")
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
