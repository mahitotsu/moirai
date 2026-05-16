"""
Chat proxy — forwards /api/chat to the Gateway Agent via boto3.

Run:
    uv run uvicorn ui.proxy:app --port 8001

Or from the ui/ directory:
    uv run uvicorn proxy:app --port 8001

Requires env vars (copy .env.example → .env.local and source it, or export manually):
    AGENT_RUNTIME_ARN  — ARN of the agora_gateway AgentCore Runtime
    AWS_REGION         — default: us-east-1
"""

from __future__ import annotations

import json
import os
import uuid

import boto3
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Agora Chat Proxy")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)

REGION = os.getenv("AWS_REGION", "us-east-1")
AGENT_RUNTIME_ARN = os.getenv("AGENT_RUNTIME_ARN", "")


class ChatRequest(BaseModel):
    message: str
    userId: str = "demo-user"
    sessionId: str = ""


@app.post("/api/chat")
async def chat(req: ChatRequest) -> dict[str, str]:
    if not AGENT_RUNTIME_ARN:
        return {
            "response": (
                "[Demo mode] エージェントが未設定です。\n"
                "AGENT_RUNTIME_ARN 環境変数に Gateway Agent のARNを設定してください。\n"
                "CDK outputs の AgoraGatewayRuntimeArn を確認してください。"
            )
        }

    session_id = req.sessionId or str(uuid.uuid4())
    client = boto3.client("bedrock-agentcore", region_name=REGION)

    resp = client.invoke_agent_runtime(
        agentRuntimeArn=AGENT_RUNTIME_ARN,
        qualifier="DEFAULT",
        payload=json.dumps({"prompt": req.message, "user_id": req.userId}).encode(),
        runtimeSessionId=session_id,
    )
    body_bytes = resp["response"].read()

    try:
        result: dict = json.loads(body_bytes)
        return {"response": result.get("response", str(result))}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"response": body_bytes.decode("utf-8", errors="replace")}
