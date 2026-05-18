from __future__ import annotations

import json
import logging

import boto3
from pydantic_settings import BaseSettings


class _Settings(BaseSettings):
    agent_runtime_arn: str = ""


_AGENT_RUNTIME_ARN = _Settings().agent_runtime_arn
_AGENT_QUALIFIER = "DEFAULT"

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_agentcore = boto3.client("bedrock-agentcore")


def _invoke_gateway_agent(ticket_id: str, title: str, severity: str, description: str) -> None:
    """Send a diagnostic request to the Gateway Agent (Triage→Diagnosis→Resolution)."""
    if not _AGENT_RUNTIME_ARN:
        logger.warning("AGENT_RUNTIME_ARN not set — skipping agent invocation")
        return

    message = (
        f"新規インシデントチケット {ticket_id} が起票されました。\n"
        f"タイトル: {title}\n"
        f"重要度: {severity}\n"
        f"概要: {description}\n"
        "Triage → Diagnosis → Resolution パイプラインによる診断を開始してください。"
    )
    payload = json.dumps({"prompt": message, "user_id": "ticket-dispatcher"}).encode()

    resp = _agentcore.invoke_agent_runtime(
        agentRuntimeArn=_AGENT_RUNTIME_ARN,
        qualifier=_AGENT_QUALIFIER,
        payload=payload,
        runtimeSessionId=ticket_id,
    )
    body: bytes = resp["response"].read()
    logger.info("agent response (first 500 bytes): %s", body[:500])


def handler(event: dict, context: object) -> None:
    """Process DynamoDB Streams records from agora-tickets.

    INSERT only — fires the Gateway Agent diagnostic pipeline for each new ticket.
    MODIFY / REMOVE events are ignored; those are handled by future V4 consumers.
    """
    for record in event["Records"]:
        if record["eventName"] != "INSERT":
            continue

        new_image = record["dynamodb"]["NewImage"]
        ticket_id = new_image["ticket_id"]["S"]
        title = new_image.get("title", {}).get("S", "")
        severity = new_image.get("severity", {}).get("S", "")
        description = new_image.get("description", {}).get("S", "")

        logger.info("new ticket: ticket_id=%s severity=%s", ticket_id, severity)

        _invoke_gateway_agent(ticket_id, title, severity, description)
        logger.info("agent invoked: ticket_id=%s", ticket_id)
