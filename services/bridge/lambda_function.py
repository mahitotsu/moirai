from __future__ import annotations

import json
import logging
import os
import urllib.request
from functools import lru_cache

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_TICKET_SERVICE_URL = os.environ["TICKET_SERVICE_URL"].rstrip("/")
_API_KEY_SECRET_NAME = os.environ["API_KEY_SECRET_NAME"]

_sm = boto3.client("secretsmanager")


@lru_cache(maxsize=1)
def _get_api_key() -> str:
    """Fetch the Ticket Service API key from Secrets Manager (cached per container)."""
    return _sm.get_secret_value(SecretId=_API_KEY_SECRET_NAME)["SecretString"]


def _create_ticket(alarm_name: str, reason: str) -> str:
    """POST to Ticket Service REST API and return the new ticket_id."""
    payload = json.dumps(
        {
            "title": f"CloudWatch ALARM: {alarm_name}",
            "description": (
                f"CloudWatch アラーム '{alarm_name}' が ALARM 状態に遷移しました。\n"
                f"理由: {reason}\n"
                "自動診断パイプラインを起動します。"
            ),
            "category": "database",
            "severity": "high",
        }
    ).encode()

    req = urllib.request.Request(
        f"{_TICKET_SERVICE_URL}/tickets",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": _get_api_key(),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        ticket: dict = json.loads(resp.read())

    return ticket["ticket_id"]


def handler(event: dict, context: object) -> None:
    """Process one SQS record = one CloudWatch Alarm ALARM-state event from EventBridge.

    Failure propagates to SQS: message is retried up to maxReceiveCount, then sent to DLQ.
    Agent invocation is NOT triggered here — DynamoDB Streams on agora-tickets handles that
    on the Agora platform side (ticket-dispatcher Lambda in ComputeStack).
    """
    for record in event["Records"]:
        eb_event: dict = json.loads(record["body"])
        detail = eb_event.get("detail", {})
        alarm_name: str = detail.get("alarmName", "Unknown")
        reason: str = detail.get("state", {}).get("reason", "")

        logger.info("alarm_name=%s", alarm_name)

        ticket_id = _create_ticket(alarm_name, reason)
        logger.info("ticket_id=%s created", ticket_id)
