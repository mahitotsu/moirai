from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError
from pydantic_settings import BaseSettings


class _Settings(BaseSettings):
    knowledge_table_name: str
    vector_bucket_name: str
    vector_index_name: str


_settings = _Settings()  # type: ignore[call-arg]

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_dynamodb = boto3.client("dynamodb")
_s3vectors = boto3.client("s3vectors")
_bedrock_runtime = boto3.client("bedrock-runtime")

_EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"


def _embed(text: str) -> list[float]:
    resp = _bedrock_runtime.invoke_model(
        modelId=_EMBED_MODEL_ID,
        body=json.dumps({"inputText": text}),
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(resp["body"].read())["embedding"]


def _build_embed_text(new_image: dict) -> str:
    parts = [
        f"Title: {new_image.get('title', {}).get('S', '')}",
        f"Category: {new_image.get('category', {}).get('S', '')}",
        f"Resolution: {new_image.get('resolution', {}).get('S', '')}",
    ]
    ll = new_image.get("lesson_learned", {}).get("S")
    if ll:
        parts.append(f"Lesson learned: {ll}")
    return "\n".join(parts)


def _index_vector(new_image: dict) -> None:
    ticket_id = new_image["ticket_id"]["S"]
    embedding = _embed(_build_embed_text(new_image))
    metadata: dict[str, Any] = {
        "ticket_id": ticket_id,
        "title": new_image.get("title", {}).get("S", ""),
        "category": new_image.get("category", {}).get("S", ""),
        "severity": new_image.get("severity", {}).get("S", ""),
    }
    _s3vectors.put_vectors(
        vectorBucketName=_settings.vector_bucket_name,
        indexName=_settings.vector_index_name,
        vectors=[{
            "key": ticket_id,
            "data": {"float32": embedding},
            "metadata": metadata,
        }],
    )
    logger.info("vector indexed: ticket_id=%s", ticket_id)


def _is_newly_resolved(record: dict) -> bool:
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
    _dynamodb.put_item(TableName=_settings.knowledge_table_name, Item=item)
    logger.info("knowledge crystallized: ticket_id=%s", ticket_id)


def handler(event: dict, context: object) -> dict:
    """Process DynamoDB Streams MODIFY records from agora-tickets.

    Fires when a ticket's status changes to 'resolved', writes a knowledge
    record to agora-knowledge and indexes a vector in S3 Vectors.
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
            _index_vector(new_image)
        except ClientError as exc:
            logger.error("processing failed: ticket_id=%s error=%s", ticket_id, exc)
            failures.append({"itemIdentifier": record["dynamodb"]["SequenceNumber"]})

    return {"batchItemFailures": failures}
