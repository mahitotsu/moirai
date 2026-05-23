from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

# Set env vars before module-level _Settings() runs
os.environ.setdefault("TICKET_SERVICE_URL", "http://test-ticket-service")
os.environ.setdefault("API_KEY_SECRET_NAME", "test-secret")

sys.modules.pop("lambda_function", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with patch("boto3.client", return_value=MagicMock()):
    import lambda_function


def _sqs_event(alarm_name: str, reason: str = "Threshold crossed") -> dict:
    """CloudWatch Alarm ALARM 状態変化を EventBridge 経由で受け取った SQS レコード。"""
    eb_event = {
        "source": "aws.cloudwatch",
        "detail-type": "CloudWatch Alarm State Change",
        "detail": {
            "alarmName": alarm_name,
            "state": {"value": "ALARM", "reason": reason},
        },
    }
    return {"Records": [{"body": json.dumps(eb_event)}]}


def test_handler_extracts_alarm_name_and_reason() -> None:
    with patch.object(lambda_function, "_create_ticket", return_value="t-1") as mock:
        lambda_function.handler(
            _sqs_event("agora-fake-api-error-rate", "2 datapoints breached"), None
        )
    mock.assert_called_once_with("agora-fake-api-error-rate", "2 datapoints breached")


def test_handler_defaults_when_alarm_name_missing() -> None:
    """alarmName が欠落した不正イベントでクラッシュせず 'Unknown' にフォールバックする。"""
    event = {
        "Records": [{"body": json.dumps({"detail": {"state": {"value": "ALARM", "reason": ""}}})}]
    }
    with patch.object(lambda_function, "_create_ticket", return_value="t-1") as mock:
        lambda_function.handler(event, None)
    mock.assert_called_once_with("Unknown", "")


def test_create_ticket_title_follows_convention() -> None:
    """タイトルは 'CloudWatch ALARM: {alarm_name}' 形式でなければならない。
    ticket-dispatcher や Gateway Agent がタイトルを解析してアラーム源を識別するため。
    """
    captured: list[dict] = []

    def fake_urlopen(req, timeout):
        captured.append(json.loads(req.data))
        resp = MagicMock()
        resp.read.return_value = json.dumps({"ticket_id": "t-99"}).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    with (
        patch("urllib.request.urlopen", side_effect=fake_urlopen),
        patch.object(lambda_function, "_get_api_key", return_value="test-key"),
    ):
        ticket_id = lambda_function._create_ticket("agora-fake-api-error-rate", "2 datapoints")

    assert ticket_id == "t-99"
    payload = captured[0]
    assert payload["title"] == "CloudWatch ALARM: agora-fake-api-error-rate"
    assert payload["severity"] == "high"
    assert payload["category"] == "other"
    assert "agora-fake-api-error-rate" in payload["description"]


def test_create_ticket_includes_reason_in_description() -> None:
    captured: list[dict] = []

    def fake_urlopen(req, timeout):
        captured.append(json.loads(req.data))
        resp = MagicMock()
        resp.read.return_value = json.dumps({"ticket_id": "t-1"}).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    reason = "Threshold Crossed: 2 out of the last 2 datapoints"
    with (
        patch("urllib.request.urlopen", side_effect=fake_urlopen),
        patch.object(lambda_function, "_get_api_key", return_value="test-key"),
    ):
        lambda_function._create_ticket("alarm-name", reason)

    assert reason in captured[0]["description"]
