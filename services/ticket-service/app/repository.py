from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient

from app.models import Ticket, TicketCreate, TicketUpdate


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _to_ticket(item: dict[str, Any]) -> Ticket:
    return Ticket(
        ticket_id=item["ticket_id"]["S"],
        title=item["title"]["S"],
        description=item["description"]["S"],
        category=item["category"]["S"],
        severity=item["severity"]["S"],
        status=item["status"]["S"],
        resolution=item["resolution"]["S"] if "resolution" in item else None,
        created_at=item["created_at"]["S"],
        updated_at=item["updated_at"]["S"],
        resolved_at=item["resolved_at"]["S"] if "resolved_at" in item else None,
    )


class TicketRepository:
    def __init__(self, client: DynamoDBClient, table_name: str) -> None:
        self._client = client
        self._table = table_name

    def create(self, data: TicketCreate) -> Ticket:
        now = _now()
        ticket_id = str(uuid.uuid4())
        item: dict[str, Any] = {
            "ticket_id": {"S": ticket_id},
            "title": {"S": data.title},
            "description": {"S": data.description},
            "category": {"S": data.category},
            "severity": {"S": data.severity},
            "status": {"S": "open"},
            "created_at": {"S": now},
            "updated_at": {"S": now},
        }
        self._client.put_item(TableName=self._table, Item=item)
        return _to_ticket(item)

    def get(self, ticket_id: str) -> Ticket | None:
        resp = self._client.get_item(
            TableName=self._table,
            Key={"ticket_id": {"S": ticket_id}},
        )
        item = resp.get("Item")
        return _to_ticket(item) if item else None

    def update(self, ticket_id: str, data: TicketUpdate) -> Ticket | None:
        if self.get(ticket_id) is None:
            return None

        now = _now()
        expr_parts = ["updated_at = :updated_at"]
        values: dict[str, Any] = {":updated_at": {"S": now}}

        if data.status is not None:
            expr_parts.append("#st = :status")
            values[":status"] = {"S": data.status}
            if data.status == "resolved":
                expr_parts.append("resolved_at = :resolved_at")
                values[":resolved_at"] = {"S": now}

        if data.resolution is not None:
            expr_parts.append("resolution = :resolution")
            values[":resolution"] = {"S": data.resolution}

        resp = self._client.update_item(
            TableName=self._table,
            Key={"ticket_id": {"S": ticket_id}},
            UpdateExpression="SET " + ", ".join(expr_parts),
            # status is a reserved word in DynamoDB
            ExpressionAttributeNames={"#st": "status"} if data.status is not None else {},
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
        return _to_ticket(resp["Attributes"])

    def list_by_status(self, status: str, limit: int = 50) -> list[Ticket]:
        resp = self._client.query(
            TableName=self._table,
            IndexName="status-created_at-index",
            KeyConditionExpression="#st = :status",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":status": {"S": status}},
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_to_ticket(item) for item in resp.get("Items", [])]

    def list_by_category(self, category: str, limit: int = 50) -> list[Ticket]:
        resp = self._client.query(
            TableName=self._table,
            IndexName="category-created_at-index",
            KeyConditionExpression="category = :category",
            ExpressionAttributeValues={":category": {"S": category}},
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_to_ticket(item) for item in resp.get("Items", [])]

    def scan(self, limit: int = 100) -> list[Ticket]:
        resp = self._client.scan(TableName=self._table, Limit=limit)
        return [_to_ticket(item) for item in resp.get("Items", [])]
