from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Category = Literal["database", "network", "memory", "deploy", "other"]
Severity = Literal["low", "medium", "high", "critical"]
Status = Literal["open", "investigating", "resolved", "closed"]


class TicketCreate(BaseModel):
    title: str
    description: str
    category: Category
    severity: Severity


class TicketUpdate(BaseModel):
    # Pydantic V2 generates anyOf:[{type:string},{type:null}] for Optional fields,
    # which AgentCore Gateway cannot validate. Override to emit plain type:string.
    model_config = ConfigDict(json_schema_extra={
        "properties": {
            "status": {"type": "string", "enum": list(Status.__args__)},  # type: ignore[attr-defined]
            "resolution": {"type": "string"},
        }
    })
    status: Status | None = None
    resolution: str | None = None


class Ticket(BaseModel):
    ticket_id: str
    title: str
    description: str
    category: str
    severity: str
    status: str
    resolution: str | None = None
    created_at: str
    updated_at: str
    resolved_at: str | None = None
