from __future__ import annotations

from typing import Annotated

import boto3
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.models import Ticket, TicketCreate, TicketUpdate
from app.repository import TicketRepository
from app.settings import Settings

settings = Settings()  # type: ignore[call-arg]

# FastAPI auto-exposes /openapi.json — used by AgentCore Gateway for MCP tool generation
app = FastAPI(title="Ticket Service")


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if settings.api_key and request.url.path not in ("/health", "/openapi.json", "/docs", "/redoc"):
        key = request.headers.get("x-api-key", "")
        if key != settings.api_key:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)


def get_repository() -> TicketRepository:
    client = boto3.client("dynamodb")
    return TicketRepository(client, settings.table_name)


RepoDep = Annotated[TicketRepository, Depends(get_repository)]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tickets", response_model=Ticket, status_code=201)
def create_ticket(data: TicketCreate, repo: RepoDep) -> Ticket:
    return repo.create(data)


@app.get("/tickets", response_model=list[Ticket])
def list_tickets(
    repo: RepoDep,
    status: str | None = None,
    category: str | None = None,
    limit: int = 50,
) -> list[Ticket]:
    if status:
        return repo.list_by_status(status, limit)
    if category:
        return repo.list_by_category(category, limit)
    return repo.scan(limit)


@app.get("/tickets/{ticket_id}", response_model=Ticket)
def get_ticket(ticket_id: str, repo: RepoDep) -> Ticket:
    ticket = repo.get(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@app.patch("/tickets/{ticket_id}", response_model=Ticket)
def update_ticket(ticket_id: str, data: TicketUpdate, repo: RepoDep) -> Ticket:
    ticket = repo.update(ticket_id, data)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket
