from __future__ import annotations

import os

import boto3
import pytest
from app.repository import ReportRepository

TABLE_NAME = "agora-test-reports"
os.environ.setdefault("TABLE_NAME", TABLE_NAME)


@pytest.fixture(scope="session")
def dynamodb_client():
    return boto3.client("dynamodb")


@pytest.fixture(scope="session", autouse=True)
def test_table(dynamodb_client):
    dynamodb_client.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "report_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "report_id", "AttributeType": "S"},
            {"AttributeName": "type", "AttributeType": "S"},
            {"AttributeName": "created_at", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "type-created_at-index",
                "KeySchema": [
                    {"AttributeName": "type", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    waiter = dynamodb_client.get_waiter("table_exists")
    waiter.config.delay = 2  # デフォルト20秒→2秒ポーリングに短縮
    waiter.wait(TableName=TABLE_NAME)
    yield
    dynamodb_client.delete_table(TableName=TABLE_NAME)


@pytest.fixture
def repo(dynamodb_client) -> ReportRepository:
    return ReportRepository(dynamodb_client, TABLE_NAME)
