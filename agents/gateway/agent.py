from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic_settings import BaseSettings
from strands import Agent
from strands.models import BedrockModel, CacheConfig
from tools import run_diagnosis, run_resolution, run_triage


class _Settings(BaseSettings):
    memory_id: str = ""
    aws_region: str = "us-east-1"
    guardrail_id: str = ""
    guardrail_version: str = "DRAFT"


_s = _Settings()
MODEL_ID = "us.anthropic.claude-sonnet-4-6"
REGION = _s.aws_region
MEMORY_ID = _s.memory_id

_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.md").read_text()

app = BedrockAgentCoreApp()

_memory_client: Any = None


def _memory() -> Any:
    global _memory_client
    if _memory_client is None:
        _memory_client = boto3.client("bedrock-agentcore", region_name=REGION)
    return _memory_client


def _retrieve_memories(actor_id: str, query: str) -> str:
    if not MEMORY_ID:
        return ""
    try:
        resp = _memory().retrieve_memory_records(
            memoryId=MEMORY_ID,
            namespace=f"users/{actor_id}",
            searchCriteria={"searchQuery": query, "topK": 5},
        )
        records = resp.get("memoryRecords", [])
        if not records:
            return ""
        lines = ["## Relevant memory from past sessions:"]
        for rec in records:
            text = rec.get("content", {}).get("text", "")
            if text:
                lines.append(f"- {text}")
        return "\n".join(lines)
    except Exception:
        return ""


def _save_memory(actor_id: str, prompt: str, response: str) -> None:
    if not MEMORY_ID:
        return
    try:
        summary = f"User reported: {prompt[:300]}. Outcome: {str(response)[:400]}"
        _memory().batch_create_memory_records(
            memoryId=MEMORY_ID,
            records=[
                {
                    "requestIdentifier": str(uuid.uuid4()),
                    "namespaces": [f"users/{actor_id}"],
                    "content": {"text": summary},
                    "timestamp": datetime.now(UTC),
                }
            ],
        )
    except Exception:
        pass


@app.entrypoint
def invoke(payload: dict[str, Any], context: Any) -> dict[str, str]:
    actor_id = payload.get("user_id", "default-user")
    prompt = payload.get("prompt", payload.get("message", ""))

    memories = _retrieve_memories(actor_id, prompt)
    system_prompt = _SYSTEM_PROMPT
    if memories:
        system_prompt = f"{_SYSTEM_PROMPT}\n\n{memories}"

    model_kwargs: dict = {
        "model_id": MODEL_ID,
        "region_name": REGION,
        "cache_config": CacheConfig(strategy="auto"),
    }
    if _s.guardrail_id:
        model_kwargs["guardrail_id"] = _s.guardrail_id
        model_kwargs["guardrail_version"] = _s.guardrail_version
    agent = Agent(
        model=BedrockModel(**model_kwargs),
        system_prompt=system_prompt,
        tools=[run_triage, run_diagnosis, run_resolution],
    )
    result = agent(prompt)
    _save_memory(actor_id, prompt, str(result))
    return {"response": str(result)}


if __name__ == "__main__":
    app.run()
