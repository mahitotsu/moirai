from __future__ import annotations

import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_TABLE_NAME = os.environ["TABLE_NAME"]
_ITEM_ID = os.environ.get("ITEM_ID", "config-001")

_dynamodb = boto3.client("dynamodb")


def handler(event: dict, context: object) -> dict:
    """Simulate an API server health-check by reading from DynamoDB.

    FIS injects ProvisionedThroughputExceededException on dynamodb:GetItem,
    causing this function to raise ClientError → Lambda/Errors metric spikes
    → CloudWatch alarm transitions to ALARM state.
    """
    logger.info("fake-api-server: invoking DynamoDB GetItem (FIS injection target)")

    response = _dynamodb.get_item(
        TableName=_TABLE_NAME,
        Key={"item_id": {"S": _ITEM_ID}},
    )

    item = response.get("Item")
    logger.info(
        "fake-api-server: GetItem succeeded item_id=%s found=%s",
        _ITEM_ID,
        item is not None,
    )

    return {
        "statusCode": 200,
        "body": json.dumps({"status": "ok", "item_id": _ITEM_ID}),
    }
