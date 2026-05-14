from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Category = Literal["database", "network", "memory", "deploy", "other"]
Severity = Literal["low", "medium", "high", "critical"]
Status = Literal["open", "investigating", "resolved", "closed"]


class TicketCreate(BaseModel):
    title: str
    description: str
    category: Category
    severity: Severity


class TicketUpdate(BaseModel):
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
