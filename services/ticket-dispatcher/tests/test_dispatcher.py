from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("AGENT_RUNTIME_ARN", "")

sys.modules.pop("lambda_function", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with patch("boto3.client", return_value=MagicMock()):
    import lambda_function


def _streams_event(
    event_name: str,
    ticket_id: str = "t-1",
    title: str = "CloudWatch ALARM: Test Incident",
    severity: str = "high",
    description: str = "EC2 DescribeInstances throttled",
) -> dict:
    """DynamoDB Streams のレコードを模倣した最小イベント。"""
    return {
        "Records": [
            {
                "eventName": event_name,
                "dynamodb": {
                    "NewImage": {
                        "ticket_id": {"S": ticket_id},
                        "title": {"S": title},
                        "severity": {"S": severity},
                        "description": {"S": description},
                    }
                },
            }
        ]
    }


def test_insert_triggers_agent_with_ticket_fields() -> None:
    with patch.object(lambda_function, "_invoke_gateway_agent") as mock:
        lambda_function.handler(
            _streams_event(
                "INSERT",
                ticket_id="t-42",
                title="CloudWatch ALARM: DB down",
                severity="critical",
            ),
            None,
        )
    mock.assert_called_once_with(
        "t-42",
        "CloudWatch ALARM: DB down",
        "critical",
        "EC2 DescribeInstances throttled",
    )


def test_modify_is_ignored() -> None:
    """MODIFY イベントは V4 の stream consumer が担う設計のため dispatcher は無視する。"""
    with patch.object(lambda_function, "_invoke_gateway_agent") as mock:
        lambda_function.handler(_streams_event("MODIFY"), None)
    mock.assert_not_called()


def test_remove_is_ignored() -> None:
    with patch.object(lambda_function, "_invoke_gateway_agent") as mock:
        lambda_function.handler(_streams_event("REMOVE"), None)
    mock.assert_not_called()


def test_agent_not_called_when_arn_unset() -> None:
    """AGENT_RUNTIME_ARN 未設定時はエラーを起こさずスキップする (初回デプロイ想定)。"""
    with (
        patch.object(lambda_function, "_AGENT_RUNTIME_ARN", ""),
        patch.object(lambda_function, "_agentcore") as mock_agentcore,
    ):
        lambda_function._invoke_gateway_agent("t-1", "title", "high", "desc")
    mock_agentcore.invoke_agent_runtime.assert_not_called()


def test_invoke_gateway_agent_builds_prompt_with_ticket_info() -> None:
    """診断依頼プロンプトにチケットID・タイトル・重要度・概要がすべて含まれる。"""
    captured: list[dict] = []

    def fake_invoke(**kwargs):
        captured.append(kwargs)
        resp_mock = MagicMock()
        resp_mock.__getitem__ = (
            lambda s, k: MagicMock(read=lambda: b"ok") if k == "response" else None
        )
        return resp_mock

    arn = "arn:aws:bedrock-agentcore:::runtime/test"
    with patch.object(lambda_function, "_AGENT_RUNTIME_ARN", arn):
        lambda_function._agentcore.invoke_agent_runtime.side_effect = fake_invoke
        lambda_function._invoke_gateway_agent("t-99", "API Error", "critical", "Throttling on EC2")

    assert len(captured) == 1
    payload_str = captured[0]["payload"].decode()
    assert "t-99" in payload_str
    assert "API Error" in payload_str
    assert "critical" in payload_str
    assert "Throttling on EC2" in payload_str
