from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("KNOWLEDGE_TABLE_NAME", "agora-test-knowledge")

sys.modules.pop("lambda_function", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

with patch("boto3.client", return_value=MagicMock()):
    import lambda_function


def _streams_event(
    event_name: str,
    new_status: str = "resolved",
    old_status: str = "investigating",
    ticket_id: str = "t-1",
    title: str = "CloudWatch ALARM: Test",
    category: str = "network",
    resolution: str = "Throttling cleared after FIS experiment ended.",
) -> dict:
    record: dict = {
        "eventName": event_name,
        "dynamodb": {
            "SequenceNumber": "1234567890",
            "NewImage": {
                "ticket_id": {"S": ticket_id},
                "title": {"S": title},
                "status": {"S": new_status},
                "category": {"S": category},
                "resolution": {"S": resolution},
            },
            "OldImage": {
                "ticket_id": {"S": ticket_id},
                "status": {"S": old_status},
            },
        },
    }
    return {"Records": [record]}


def test_modify_resolved_calls_crystallize() -> None:
    with patch.object(lambda_function, "_crystallize") as mock:
        result = lambda_function.handler(
            _streams_event("MODIFY", new_status="resolved", old_status="investigating"),
            None,
        )
    mock.assert_called_once()
    assert result == {"batchItemFailures": []}


def test_insert_is_ignored() -> None:
    with patch.object(lambda_function, "_crystallize") as mock:
        lambda_function.handler(_streams_event("INSERT"), None)
    mock.assert_not_called()


def test_remove_is_ignored() -> None:
    with patch.object(lambda_function, "_crystallize") as mock:
        lambda_function.handler(_streams_event("REMOVE"), None)
    mock.assert_not_called()


def test_already_resolved_modify_is_skipped() -> None:
    """MODIFY where ticket was already resolved should not re-crystallize."""
    with patch.object(lambda_function, "_crystallize") as mock:
        lambda_function.handler(
            _streams_event("MODIFY", new_status="resolved", old_status="resolved"),
            None,
        )
    mock.assert_not_called()


def test_non_resolved_modify_is_skipped() -> None:
    with patch.object(lambda_function, "_crystallize") as mock:
        lambda_function.handler(
            _streams_event("MODIFY", new_status="investigating", old_status="open"),
            None,
        )
    mock.assert_not_called()


def test_crystallize_failure_reported_as_batch_item_failure() -> None:
    from botocore.exceptions import ClientError

    err = ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}}, "PutItem"
    )
    with patch.object(lambda_function, "_crystallize", side_effect=err):
        result = lambda_function.handler(
            _streams_event("MODIFY", new_status="resolved", old_status="open"),
            None,
        )
    assert result["batchItemFailures"] == [{"itemIdentifier": "1234567890"}]


def test_crystallize_builds_correct_knowledge_item() -> None:
    """_crystallize が正しいフィールドで put_item を呼ぶことを確認する。"""
    new_image = {
        "ticket_id": {"S": "t-99"},
        "title": {"S": "API down"},
        "category": {"S": "network"},
        "resolution": {"S": "Restart resolved it."},
    }
    with patch.object(lambda_function, "_dynamodb") as mock_db:
        lambda_function._crystallize(new_image)

    call_kwargs = mock_db.put_item.call_args.kwargs
    item = call_kwargs["Item"]
    assert item["knowledge_id"]["S"] == "t-99"
    assert item["ticket_id"]["S"] == "t-99"
    assert item["title"]["S"] == "API down"
    assert item["category"]["S"] == "network"
    assert item["resolution"]["S"] == "Restart resolved it."
    assert item["source"]["S"] == "ticket-resolved"
    assert "crystallized_at" in item
    assert "lesson_learned" not in item


def test_crystallize_includes_lesson_learned_when_present() -> None:
    """lesson_learned フィールドがあれば knowledge レコードに含まれる。"""
    new_image = {
        "ticket_id": {"S": "t-100"},
        "title": {"S": "DB slow"},
        "category": {"S": "database"},
        "resolution": {"S": "Added index."},
        "lesson_learned": {"S": "Add indexes before high-traffic launches."},
    }
    with patch.object(lambda_function, "_dynamodb") as mock_db:
        lambda_function._crystallize(new_image)

    item = mock_db.put_item.call_args.kwargs["Item"]
    assert item["lesson_learned"]["S"] == "Add indexes before high-traffic launches."
