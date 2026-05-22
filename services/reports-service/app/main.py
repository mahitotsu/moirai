from __future__ import annotations

from typing import Annotated

import boto3
from app.models import Report, ReportCreate
from app.repository import ReportRepository
from app.settings import Settings
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

settings = Settings()  # type: ignore[call-arg]
_dynamo_client = boto3.client("dynamodb")

# FastAPI auto-exposes /openapi.json — used by AgentCore Gateway for MCP tool generation
app = FastAPI(title="Reports Service")


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if settings.api_key and request.url.path not in ("/health", "/openapi.json", "/docs", "/redoc"):
        key = request.headers.get("x-api-key", "")
        if key != settings.api_key:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)


def get_repository() -> ReportRepository:
    return ReportRepository(_dynamo_client, settings.table_name)


RepoDep = Annotated[ReportRepository, Depends(get_repository)]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/reports", response_model=Report, status_code=201)
def create_report(data: ReportCreate, repo: RepoDep) -> Report:
    return repo.create(data)


@app.get("/reports", response_model=list[Report])
def list_reports(
    repo: RepoDep,
    type: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[Report]:
    if type:
        return repo.list_by_type(type, limit)
    return repo.scan(limit)


@app.get("/reports/{report_id}", response_model=Report)
def get_report(report_id: str, repo: RepoDep) -> Report:
    report = repo.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report
