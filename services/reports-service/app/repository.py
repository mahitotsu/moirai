from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient

from app.models import Report, ReportCreate

_REPORTS_TYPE_INDEX = "type-created_at-index"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _to_report(item: dict[str, Any]) -> Report:
    return Report(
        report_id=item["report_id"]["S"],
        title=item["title"]["S"],
        type=item["type"]["S"],
        summary=item["summary"]["S"],
        details=item["details"]["S"],
        created_at=item["created_at"]["S"],
    )


class ReportRepository:
    def __init__(self, client: DynamoDBClient, table_name: str) -> None:
        self._client = client
        self._table = table_name

    def create(self, data: ReportCreate) -> Report:
        now = _now()
        report_id = str(uuid.uuid4())
        item: dict[str, Any] = {
            "report_id": {"S": report_id},
            "title": {"S": data.title},
            "type": {"S": data.type},
            "summary": {"S": data.summary},
            "details": {"S": data.details},
            "created_at": {"S": now},
        }
        self._client.put_item(TableName=self._table, Item=item)
        return _to_report(item)

    def get(self, report_id: str) -> Report | None:
        resp = self._client.get_item(
            TableName=self._table,
            Key={"report_id": {"S": report_id}},
        )
        item = resp.get("Item")
        return _to_report(item) if item else None

    def list_by_type(self, report_type: str, limit: int = 50) -> list[Report]:
        resp = self._client.query(
            TableName=self._table,
            IndexName=_REPORTS_TYPE_INDEX,
            KeyConditionExpression="#t = :type",
            ExpressionAttributeNames={"#t": "type"},
            ExpressionAttributeValues={":type": {"S": report_type}},
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_to_report(item) for item in resp.get("Items", [])]

    def scan(self, limit: int = 100) -> list[Report]:
        resp = self._client.scan(TableName=self._table, Limit=limit)
        items = sorted(
            resp.get("Items", []),
            key=lambda x: x.get("created_at", {}).get("S", ""),
            reverse=True,
        )
        return [_to_report(item) for item in items[:limit]]
