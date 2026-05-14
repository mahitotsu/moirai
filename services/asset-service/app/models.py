from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

AssetType = Literal["server", "database", "service", "network", "storage"]
Environment = Literal["production", "staging", "development"]
AssetStatus = Literal["healthy", "degraded", "down", "unknown"]


class AssetCreate(BaseModel):
    name: str
    type: AssetType
    environment: Environment
    status: AssetStatus = "unknown"
    description: str | None = None
    metadata: dict[str, Any] | None = None


class AssetUpdate(BaseModel):
    status: AssetStatus | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None


class Asset(BaseModel):
    asset_id: str
    name: str
    type: str
    environment: str
    status: str
    description: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: str
    updated_at: str
