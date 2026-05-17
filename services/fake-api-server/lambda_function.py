from __future__ import annotations

import json
import logging

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_ec2 = boto3.client("ec2")


def handler(event: dict, context: object) -> dict:
    """Simulate an API server health-check by calling EC2 DescribeInstances.

    FIS injects ThrottlingException on ec2:DescribeInstances via
    aws:fis:inject-api-throttle-error targeting this function's IAM role,
    causing ClientError → Lambda/Errors metric spikes → CloudWatch alarm fires.
    """
    logger.info("fake-api-server: calling EC2 DescribeInstances (FIS injection target)")

    response = _ec2.describe_instances(
        Filters=[{"Name": "instance-state-name", "Values": ["running"]}],
        MaxResults=5,
    )

    count = sum(len(r["Instances"]) for r in response.get("Reservations", []))
    logger.info("fake-api-server: DescribeInstances succeeded running_instances=%d", count)

    return {
        "statusCode": 200,
        "body": json.dumps({"status": "ok", "running_instances": count}),
    }
