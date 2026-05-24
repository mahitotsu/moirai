from __future__ import annotations

import logging

import boto3
from pydantic_settings import BaseSettings
from strands import tool

logger = logging.getLogger(__name__)


class _Settings(BaseSettings):
    tickets_table: str = "agora-tickets"
    aws_region: str = "us-east-1"


_settings = _Settings()
_dynamodb = boto3.client("dynamodb", region_name=_settings.aws_region)


@tool
def search_past_tickets(query: str, limit: int = 5) -> str:
    """Search past resolved incident tickets for similar issues.

    Args:
        query: Keywords or description of the incident to match against past tickets.
        limit: Maximum number of tickets to return (default 5).

    Returns:
        List of matching past tickets with their descriptions and resolutions.
    """
    try:
        resp = _dynamodb.query(
            TableName=_settings.tickets_table,
            IndexName="status-created_at-index",
            KeyConditionExpression="#s = :resolved",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":resolved": {"S": "resolved"}},
            Limit=limit,
            ScanIndexForward=False,
        )
        raw_items = resp.get("Items", [])
        tickets = [{k: list(v.values())[0] for k, v in item.items()} for item in raw_items]
    except Exception as exc:
        return f"Ticket search failed: {exc}"
    if not tickets:
        return "No past resolved tickets found."
    lines: list[str] = []
    for t in tickets:
        lines.append(f"Ticket {t.get('ticket_id', '?')!s}: {t.get('title', 'Untitled')!s}")
        lines.append(
            f"  Category: {t.get('category', '?')!s} | Severity: {t.get('severity', '?')!s}"
        )
        if t.get("resolution"):
            lines.append(f"  Resolution: {str(t['resolution'])[:300]}")
        lines.append("")
    return "\n".join(lines)
