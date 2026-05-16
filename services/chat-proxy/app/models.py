from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    userId: str = "demo-user"
    sessionId: str = ""


class ChatResponse(BaseModel):
    response: str
