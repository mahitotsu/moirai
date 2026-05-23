from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient

from app.models import HistoryEntry, Ticket, TicketCreate, TicketUpdate


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_history(raw: list[dict[str, Any]]) -> list[HistoryEntry]:
    entries = []
    for e in raw:
        m = e["M"]  # each list element is wrapped in {"M": {...}} by DynamoDB wire format
        entries.append(HistoryEntry(
            timestamp=m["timestamp"]["S"],
            status=m["status"]["S"],
            note=m["note"]["S"] if "note" in m else None,
            actor=m["actor"]["S"],
        ))
    return entries


def _history_entry_to_dynamo(entry: HistoryEntry) -> dict[str, Any]:
    item: dict[str, Any] = {
        "timestamp": {"S": entry.timestamp},
        "status": {"S": entry.status},
        "actor": {"S": entry.actor},
    }
    if entry.note is not None:
        item["note"] = {"S": entry.note}
    return item


def _to_ticket(item: dict[str, Any]) -> Ticket:
    raw_history = item.get("history", {}).get("L", [])
    return Ticket(
        ticket_id=item["ticket_id"]["S"],
        title=item["title"]["S"],
        description=item["description"]["S"],
        category=item["category"]["S"],
        severity=item["severity"]["S"],
        status=item["status"]["S"],
        resolution=item["resolution"]["S"] if "resolution" in item else None,
        lesson_learned=item["lesson_learned"]["S"] if "lesson_learned" in item else None,
        created_at=item["created_at"]["S"],
        updated_at=item["updated_at"]["S"],
        resolved_at=item["resolved_at"]["S"] if "resolved_at" in item else None,
        history=_parse_history(raw_history),
    )


class TicketRepository:
    def __init__(self, client: DynamoDBClient, table_name: str) -> None:
        self._client = client
        self._table = table_name

    def create(self, data: TicketCreate) -> Ticket:
        now = _now()
        ticket_id = str(uuid.uuid4())
        initial_entry = HistoryEntry(timestamp=now, status="open", actor="system")
        item: dict[str, Any] = {
            "ticket_id": {"S": ticket_id},
            "title": {"S": data.title},
            "description": {"S": data.description},
            "category": {"S": data.category},
            "severity": {"S": data.severity},
            "status": {"S": "open"},
            "created_at": {"S": now},
            "updated_at": {"S": now},
            "history": {"L": [{"M": _history_entry_to_dynamo(initial_entry)}]},
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
        existing = self.get(ticket_id)
        if existing is None:
            return None

        now = _now()
        expr_parts = ["updated_at = :updated_at"]
        values: dict[str, Any] = {":updated_at": {"S": now}}
        attr_names: dict[str, str] = {}

        if data.status is not None:
            expr_parts.append("#st = :status")
            attr_names["#st"] = "status"
            values[":status"] = {"S": data.status}
            if data.status == "resolved":
                expr_parts.append("resolved_at = :resolved_at")
                values[":resolved_at"] = {"S": now}
            # Only append history when the status is actually changing to avoid
            # duplicate entries caused by DynamoDB Streams retry re-invocations.
            if data.status != existing.status:
                entry = HistoryEntry(
                    timestamp=now,
                    status=data.status,
                    note=data.note,
                    actor=data.actor,
                )
                expr_parts.append(
                    "history = list_append(if_not_exists(history, :empty_list), :new_entry)"
                )
                values[":empty_list"] = {"L": []}
                values[":new_entry"] = {"L": [{"M": _history_entry_to_dynamo(entry)}]}

        if data.resolution is not None:
            expr_parts.append("resolution = :resolution")
            values[":resolution"] = {"S": data.resolution}

        if data.lesson_learned is not None:
            expr_parts.append("lesson_learned = :lesson_learned")
            values[":lesson_learned"] = {"S": data.lesson_learned}

        if data.category is not None:
            expr_parts.append("category = :category")
            values[":category"] = {"S": data.category}

        kwargs: dict[str, Any] = {
            "TableName": self._table,
            "Key": {"ticket_id": {"S": ticket_id}},
            "UpdateExpression": "SET " + ", ".join(expr_parts),
            "ExpressionAttributeValues": values,
            "ReturnValues": "ALL_NEW",
        }
        if attr_names:
            # status is a reserved word in DynamoDB; only add when non-empty
            kwargs["ExpressionAttributeNames"] = attr_names
        resp = self._client.update_item(**kwargs)
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
