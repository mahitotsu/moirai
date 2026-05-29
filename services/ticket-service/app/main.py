from __future__ import annotations

from typing import Annotated

import boto3
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.models import SimilarTicket, Ticket, TicketCreate, TicketUpdate
from app.repository import TicketRepository
from app.settings import Settings

settings = Settings()  # type: ignore[call-arg]
_dynamo_client = boto3.client("dynamodb")
_bedrock_agent_client = boto3.client("bedrock-agent")
_s3vectors_client = boto3.client("s3vectors") if settings.vector_bucket_name else None
_bedrock_runtime_client = boto3.client("bedrock-runtime") if settings.vector_bucket_name else None

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
    return TicketRepository(
        _dynamo_client,
        settings.table_name,
        s3vectors_client=_s3vectors_client,
        bedrock_runtime_client=_bedrock_runtime_client,
        vector_bucket_name=settings.vector_bucket_name,
        vector_index_name=settings.vector_index_name,
    )


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
    limit: int = Query(default=50, ge=1, le=100),
) -> list[Ticket]:
    if status:
        return repo.list_by_status(status, limit)
    if category:
        return repo.list_by_category(category, limit)
    return repo.scan(limit)


@app.get("/tickets/search", response_model=list[SimilarTicket])
def search_tickets(
    repo: RepoDep,
    q: str = Query(description="自然言語クエリ（例: 'database connection timeout'）"),
    top_k: int = Query(default=5, ge=1, le=20),
) -> list[SimilarTicket]:
    """ベクトル類似度検索で過去の類似インシデントを取得する。

    S3 Vectors に保存された解決済みチケットの埋め込みに対して意味的類似度検索を行い、
    最も近い past incidents を返す。各結果には resolution と lesson_learned が含まれる。
    distance が小さいほど類似度が高い（0 が完全一致）。
    """
    return repo.search_similar(q, top_k)


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


def _fetch_prompt_text(arn: str) -> str:
    if not arn:
        return ""
    try:
        resp = _bedrock_agent_client.get_prompt(promptIdentifier=arn)
        variants = resp.get("variants", [])
        if variants:
            return variants[0]["templateConfiguration"]["text"]["text"]
    except Exception:
        pass
    return ""


@app.get("/prompts")
def get_prompts() -> dict[str, str]:
    return {
        "gateway": _fetch_prompt_text(settings.gateway_prompt_arn),
        "triage": _fetch_prompt_text(settings.triage_prompt_arn),
        "diagnosis": _fetch_prompt_text(settings.diagnosis_prompt_arn),
        "resolution": _fetch_prompt_text(settings.resolution_prompt_arn),
    }
