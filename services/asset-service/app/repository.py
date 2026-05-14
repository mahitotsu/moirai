from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient

from app.models import Asset, AssetCreate, AssetUpdate


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _to_asset(item: dict[str, Any]) -> Asset:
    raw_meta = item.get("metadata")
    metadata = json.loads(raw_meta["S"]) if raw_meta else None
    return Asset(
        asset_id=item["asset_id"]["S"],
        name=item["name"]["S"],
        type=item["type"]["S"],
        environment=item["environment"]["S"],
        status=item["status"]["S"],
        description=item["description"]["S"] if "description" in item else None,
        metadata=metadata,
        created_at=item["created_at"]["S"],
        updated_at=item["updated_at"]["S"],
    )


class AssetRepository:
    def __init__(self, client: DynamoDBClient, table_name: str) -> None:
        self._client = client
        self._table = table_name

    def create(self, data: AssetCreate) -> Asset:
        now = _now()
        asset_id = str(uuid.uuid4())
        item: dict[str, Any] = {
            "asset_id": {"S": asset_id},
            "name": {"S": data.name},
            "type": {"S": data.type},
            "environment": {"S": data.environment},
            "status": {"S": data.status},
            "created_at": {"S": now},
            "updated_at": {"S": now},
        }
        if data.description is not None:
            item["description"] = {"S": data.description}
        if data.metadata is not None:
            item["metadata"] = {"S": json.dumps(data.metadata)}
        self._client.put_item(TableName=self._table, Item=item)
        return _to_asset(item)

    def get(self, asset_id: str) -> Asset | None:
        resp = self._client.get_item(
            TableName=self._table,
            Key={"asset_id": {"S": asset_id}},
        )
        item = resp.get("Item")
        return _to_asset(item) if item else None

    def update(self, asset_id: str, data: AssetUpdate) -> Asset | None:
        if self.get(asset_id) is None:
            return None

        now = _now()
        expr_parts = ["updated_at = :updated_at"]
        values: dict[str, Any] = {":updated_at": {"S": now}}

        if data.status is not None:
            expr_parts.append("#st = :status")
            values[":status"] = {"S": data.status}

        if data.description is not None:
            expr_parts.append("description = :description")
            values[":description"] = {"S": data.description}

        if data.metadata is not None:
            expr_parts.append("metadata = :metadata")
            values[":metadata"] = {"S": json.dumps(data.metadata)}

        kwargs: dict[str, Any] = {
            "TableName": self._table,
            "Key": {"asset_id": {"S": asset_id}},
            "UpdateExpression": "SET " + ", ".join(expr_parts),
            "ExpressionAttributeValues": values,
            "ReturnValues": "ALL_NEW",
        }
        if data.status is not None:
            kwargs["ExpressionAttributeNames"] = {"#st": "status"}

        resp = self._client.update_item(**kwargs)
        return _to_asset(resp["Attributes"])

    def list_by_type(self, asset_type: str, limit: int = 50) -> list[Asset]:
        resp = self._client.query(
            TableName=self._table,
            IndexName="type-name-index",
            KeyConditionExpression="#t = :type",
            ExpressionAttributeNames={"#t": "type"},
            ExpressionAttributeValues={":type": {"S": asset_type}},
            Limit=limit,
        )
        return [_to_asset(item) for item in resp.get("Items", [])]

    def list_by_environment(self, environment: str, limit: int = 50) -> list[Asset]:
        resp = self._client.query(
            TableName=self._table,
            IndexName="environment-type-index",
            KeyConditionExpression="environment = :env",
            ExpressionAttributeValues={":env": {"S": environment}},
            Limit=limit,
        )
        return [_to_asset(item) for item in resp.get("Items", [])]

    def scan(self, limit: int = 100) -> list[Asset]:
        resp = self._client.scan(TableName=self._table, Limit=limit)
        return [_to_asset(item) for item in resp.get("Items", [])]
