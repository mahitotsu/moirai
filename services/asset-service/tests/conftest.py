from __future__ import annotations

import boto3
import pytest
from app.repository import AssetRepository

TABLE_NAME = "agora-test-assets"


@pytest.fixture(scope="session")
def dynamodb_client():
    return boto3.client("dynamodb", region_name="us-east-1")


@pytest.fixture(scope="session", autouse=True)
def test_table(dynamodb_client):
    dynamodb_client.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "asset_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "asset_id", "AttributeType": "S"},
            {"AttributeName": "type", "AttributeType": "S"},
            {"AttributeName": "name", "AttributeType": "S"},
            {"AttributeName": "environment", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "type-name-index",
                "KeySchema": [
                    {"AttributeName": "type", "KeyType": "HASH"},
                    {"AttributeName": "name", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "environment-type-index",
                "KeySchema": [
                    {"AttributeName": "environment", "KeyType": "HASH"},
                    {"AttributeName": "type", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    waiter = dynamodb_client.get_waiter("table_exists")
    waiter.wait(TableName=TABLE_NAME)
    yield
    dynamodb_client.delete_table(TableName=TABLE_NAME)


@pytest.fixture
def repo(dynamodb_client) -> AssetRepository:
    return AssetRepository(dynamodb_client, TABLE_NAME)
