from __future__ import annotations

from typing import Annotated

import boto3
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.models import ChatRequest, ChatResponse
from app.repository import AgentRepository
from app.settings import Settings

# FastAPI auto-exposes /openapi.json — used by AgentCore Gateway for MCP tool generation
app = FastAPI(title="Chat Proxy")

# Allow the React SPA (served from S3/CloudFront or localhost) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)

_settings = Settings()
_agentcore_client = boto3.client("bedrock-agentcore")


def get_repository() -> AgentRepository:
    return AgentRepository(_agentcore_client, _settings.agent_runtime_arn)


RepoDep = Annotated[AgentRepository, Depends(get_repository)]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, repo: RepoDep) -> ChatResponse:
    response = repo.invoke(req.message, req.userId, req.sessionId)
    return ChatResponse(response=response)
