from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

_KNOWLEDGE_TABLE = os.environ.get("KNOWLEDGE_TABLE_NAME", "agora-knowledge")

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_dynamodb = boto3.client("dynamodb")


def _is_newly_resolved(record: dict) -> bool:
    """Return True when a ticket transitions INTO resolved status."""
    new_image = record["dynamodb"].get("NewImage", {})
    old_image = record["dynamodb"].get("OldImage", {})
    new_status = new_image.get("status", {}).get("S", "")
    old_status = old_image.get("status", {}).get("S", "")
    return new_status == "resolved" and old_status != "resolved"


def _crystallize(new_image: dict) -> None:
    """Write (or overwrite) a knowledge record derived from a resolved ticket."""
    ticket_id = new_image["ticket_id"]["S"]
    item: dict = {
        "knowledge_id": {"S": ticket_id},
        "ticket_id": {"S": ticket_id},
        "title": {"S": new_image.get("title", {}).get("S", "")},
        "category": {"S": new_image.get("category", {}).get("S", "other")},
        "resolution": {"S": new_image.get("resolution", {}).get("S", "")},
        "crystallized_at": {"S": datetime.now(UTC).isoformat()},
        "source": {"S": "ticket-resolved"},
    }
    lesson_learned = new_image.get("lesson_learned", {}).get("S")
    if lesson_learned:
        item["lesson_learned"] = {"S": lesson_learned}
    _dynamodb.put_item(TableName=_KNOWLEDGE_TABLE, Item=item)
    logger.info("knowledge crystallized: ticket_id=%s", ticket_id)


def handler(event: dict, context: object) -> dict:
    """Process DynamoDB Streams MODIFY records from agora-tickets.

    Fires when a ticket's status changes to 'resolved' and writes a knowledge
    record to agora-knowledge for future Diagnosis Agent lookups.
    INSERT / REMOVE events are filtered out at the EventSourceMapping level.
    """
    failures: list[dict] = []
    for record in event["Records"]:
        if record["eventName"] != "MODIFY":
            continue
        if not _is_newly_resolved(record):
            continue

        new_image = record["dynamodb"]["NewImage"]
        ticket_id = new_image.get("ticket_id", {}).get("S", "?")
        logger.info("ticket resolved — crystallizing: ticket_id=%s", ticket_id)

        try:
            _crystallize(new_image)
        except ClientError as exc:
            logger.error("crystallize failed: ticket_id=%s error=%s", ticket_id, exc)
            failures.append({"itemIdentifier": record["dynamodb"]["SequenceNumber"]})

    return {"batchItemFailures": failures}
