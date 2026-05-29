from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Category = Literal["database", "network", "memory", "deploy", "performance", "security", "other"]
Severity = Literal["low", "medium", "high", "critical"]
Status = Literal["open", "investigating", "resolved", "closed"]


class HistoryEntry(BaseModel):
    timestamp: str
    status: str
    note: str | None = None
    actor: str


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
            "lesson_learned": {"type": "string"},
            "category": {"type": "string", "enum": list(Category.__args__)},  # type: ignore[attr-defined]
            "note": {"type": "string"},
            "actor": {"type": "string"},
        }
    })
    status: Status | None = None
    resolution: str | None = None
    lesson_learned: str | None = None
    category: Category | None = None
    note: str | None = None
    actor: str = "system"


class Ticket(BaseModel):
    ticket_id: str
    title: str
    description: str
    category: str
    severity: str
    status: str
    resolution: str | None = None
    lesson_learned: str | None = None
    created_at: str
    updated_at: str
    resolved_at: str | None = None
    history: list[HistoryEntry] = []


class SimilarTicket(BaseModel):
    ticket_id: str
    title: str
    category: str
    severity: str
    distance: float
    resolution: str | None = None
    lesson_learned: str | None = None
