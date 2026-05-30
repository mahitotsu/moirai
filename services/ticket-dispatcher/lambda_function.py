from __future__ import annotations

import json
import logging
import re

import boto3
from pydantic_settings import BaseSettings


class _Settings(BaseSettings):
    agent_runtime_arn: str
    dispatcher_prompt_arn: str


_settings = _Settings()  # type: ignore[call-arg]
_AGENT_QUALIFIER = "DEFAULT"

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_agentcore = boto3.client("bedrock-agentcore")
_bedrock_agent = boto3.client("bedrock-agent")

_prompt_template_cache: str | None = None


def _get_prompt_template() -> str:
    global _prompt_template_cache
    if _prompt_template_cache is None:
        resp = _bedrock_agent.get_prompt(promptIdentifier=_settings.dispatcher_prompt_arn)
        variants = resp.get("variants", [])
        if not variants:
            arn = _settings.dispatcher_prompt_arn
            raise RuntimeError(f"No variants found for prompt ARN: {arn}")
        _prompt_template_cache = variants[0]["templateConfiguration"]["text"]["text"]
        logger.info("Loaded dispatcher prompt template from Bedrock Prompt Management")
    return _prompt_template_cache


def _expand_template(template: str, **variables: str) -> str:
    """Replace {{variable}} placeholders with provided values."""
    result = template
    for key, value in variables.items():
        result = re.sub(r"\{\{" + re.escape(key) + r"\}\}", value, result)
    return result


def _invoke_gateway_agent(ticket_id: str, title: str, severity: str, description: str) -> None:
    """Send a diagnostic request to the Pipeline Orchestrator."""
    template = _get_prompt_template()
    message = _expand_template(
        template,
        ticket_id=ticket_id,
        title=title,
        severity=severity,
        description=description,
    )
    payload = json.dumps({"prompt": message, "user_id": "ticket-dispatcher"}).encode()

    resp = _agentcore.invoke_agent_runtime(
        agentRuntimeArn=_settings.agent_runtime_arn,
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

        # Only process tickets created by the Bridge Lambda (alarm-driven).
        # Resolution Agent tickets have a different title, preventing infinite loops.
        if not title.startswith("CloudWatch ALARM:"):
            logger.info("skipping non-alarm ticket: ticket_id=%s title=%r", ticket_id, title)
            continue

        logger.info("new ticket: ticket_id=%s severity=%s", ticket_id, severity)

        _invoke_gateway_agent(ticket_id, title, severity, description)
        logger.info("orchestrator invoked: ticket_id=%s", ticket_id)
