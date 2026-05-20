from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

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
    # Pydantic V2 generates anyOf:[{type:string},{type:null}] for Optional fields,
    # which AgentCore Gateway cannot validate. Override to emit plain type:string.
    model_config = ConfigDict(json_schema_extra={
        "properties": {
            "status": {"type": "string", "enum": list(AssetStatus.__args__)},  # type: ignore[attr-defined]
            "description": {"type": "string"},
            "metadata": {"type": "object"},
        }
    })
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
