from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with patch("boto3.client", return_value=MagicMock()):
    import lambda_function


def test_handler_returns_200_on_success() -> None:
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {
        "Reservations": [{"Instances": [{}, {}]}, {"Instances": [{}]}]
    }
    with patch.object(lambda_function, "_ec2", mock_ec2):
        resp = lambda_function.handler({}, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "ok"
    assert body["running_instances"] == 3


def test_handler_returns_zero_instances_when_none_running() -> None:
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {"Reservations": []}
    with patch.object(lambda_function, "_ec2", mock_ec2):
        resp = lambda_function.handler({}, None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["running_instances"] == 0


def test_handler_filters_by_running_state() -> None:
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {"Reservations": []}
    with patch.object(lambda_function, "_ec2", mock_ec2):
        lambda_function.handler({}, None)

    call_kwargs = mock_ec2.describe_instances.call_args[1]
    filters = call_kwargs["Filters"]
    state_filter = next(f for f in filters if f["Name"] == "instance-state-name")
    assert state_filter["Values"] == ["running"]
