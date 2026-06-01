"""Demo clear script — deletes all tickets, knowledge records, and vectors.

Usage:
    uv run python scripts/clear_demo_data.py

Resolves resource names from constants matching CDK definitions.
Safe to run multiple times (idempotent).
"""

from __future__ import annotations

import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# stop_sessions.py を同じディレクトリから import できるようにする
sys.path.insert(0, str(Path(__file__).parent))

_REGION = "us-east-1"
_TICKETS_TABLE = "agora-tickets"
_KNOWLEDGE_TABLE = "agora-knowledge"
_VECTOR_BUCKET_NAME = "agora-incident-vectors"
_VECTOR_INDEX_NAME = "tickets"
_DYNAMO_BATCH_SIZE = 25   # DynamoDB batch_write_item 上限
_VECTOR_BATCH_SIZE = 100  # S3 Vectors delete_vectors バッチサイズ
_SQS_QUEUES = [
    "https://sqs.us-east-1.amazonaws.com/346929044083/agora-alarm-queue",
    "https://sqs.us-east-1.amazonaws.com/346929044083/agora-alarm-dlq",
    "https://sqs.us-east-1.amazonaws.com/346929044083/agora-knowledge-consumer-dlq",
    "https://sqs.us-east-1.amazonaws.com/346929044083/agora-ticket-dispatcher-dlq",
]


def _scan_all_keys(dynamo, table_name: str, key_attr: str) -> list[str]:
    """テーブルをフルスキャンしてパーティションキーの値一覧を返す。"""
    keys: list[str] = []
    kwargs: dict = {"TableName": table_name, "ProjectionExpression": key_attr}
    while True:
        resp = dynamo.scan(**kwargs)
        for item in resp.get("Items", []):
            val = item.get(key_attr, {}).get("S")
            if val:
                keys.append(val)
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return keys


def _batch_delete_dynamo(dynamo, table_name: str, key_attr: str, keys: list[str]) -> None:
    """DynamoDB アイテムを 25 件ずつバッチ削除する。"""
    for i in range(0, len(keys), _DYNAMO_BATCH_SIZE):
        batch = keys[i : i + _DYNAMO_BATCH_SIZE]
        dynamo.batch_write_item(
            RequestItems={
                table_name: [
                    {"DeleteRequest": {"Key": {key_attr: {"S": k}}}}
                    for k in batch
                ]
            }
        )


def _delete_vectors(s3v, ticket_ids: list[str]) -> int:
    """S3 Vectors からベクトルをバッチ削除して削除件数を返す。"""
    deleted = 0
    for i in range(0, len(ticket_ids), _VECTOR_BATCH_SIZE):
        batch = ticket_ids[i : i + _VECTOR_BATCH_SIZE]
        try:
            s3v.delete_vectors(
                vectorBucketName=_VECTOR_BUCKET_NAME,
                indexName=_VECTOR_INDEX_NAME,
                keys=batch,
            )
            deleted += len(batch)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            # キーが存在しない場合は無視 (冪等)
            if code not in ("ResourceNotFoundException", "NoSuchKey"):
                print(f"    Warning: vector delete error ({code}): {e}")
    return deleted




def _purge_sqs_queues(sqs) -> int:
    """SQS キューをパージして削除メッセージ数の概算を返す。"""
    purged = 0
    for url in _SQS_QUEUES:
        try:
            attrs = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"])
            count = int(attrs["Attributes"].get("ApproximateNumberOfMessages", "0"))
            if count > 0:
                sqs.purge_queue(QueueUrl=url)
                purged += count
                print(f"    Purged {count} messages from {url.split('/')[-1]}")
            else:
                print(f"    {url.split('/')[-1]}: empty")
        except ClientError as e:
            print(f"    Warning: SQS purge error for {url.split('/')[-1]}: {e}")
    return purged


def main() -> None:
    dynamo = boto3.client("dynamodb", region_name=_REGION)
    s3v = boto3.client("s3vectors", region_name=_REGION)
    sqs = boto3.client("sqs", region_name=_REGION)
    # 0a. AgentCore セッションを全停止 (maxVms 枯渇対策)
    from stop_sessions import stop_all_sessions  # noqa: PLC0415
    print("==> Stopping all active AgentCore Runtime sessions ...")
    stop_all_sessions()

    # 0b. SQS キューをパージ (デモ前のノイズメッセージを除去)
    print("==> Purging SQS queues ...")
    _purge_sqs_queues(sqs)

    # 1. チケット一覧を先に取得 (S3 Vectors の削除キーとして使う)
    print(f"==> Scanning {_TICKETS_TABLE} ...")
    ticket_ids = _scan_all_keys(dynamo, _TICKETS_TABLE, "ticket_id")
    print(f"    Found {len(ticket_ids)} tickets")

    # 2. S3 Vectors を先に削除 (DynamoDB 削除前に ID を保持)
    if ticket_ids:
        print("==> Deleting S3 Vectors ...")
        deleted_vectors = _delete_vectors(s3v, ticket_ids)
        print(f"    Deleted {deleted_vectors} vectors")
    else:
        print("==> S3 Vectors: nothing to delete")

    # 3. agora-tickets 全削除
    if ticket_ids:
        print(f"==> Deleting {len(ticket_ids)} tickets from {_TICKETS_TABLE} ...")
        _batch_delete_dynamo(dynamo, _TICKETS_TABLE, "ticket_id", ticket_ids)
        print("    Done")
    else:
        print(f"==> {_TICKETS_TABLE}: nothing to delete")

    # 4. agora-knowledge 全削除
    print(f"==> Scanning {_KNOWLEDGE_TABLE} ...")
    knowledge_ids = _scan_all_keys(dynamo, _KNOWLEDGE_TABLE, "knowledge_id")
    print(f"    Found {len(knowledge_ids)} knowledge records")
    if knowledge_ids:
        print(f"==> Deleting {len(knowledge_ids)} records from {_KNOWLEDGE_TABLE} ...")
        _batch_delete_dynamo(dynamo, _KNOWLEDGE_TABLE, "knowledge_id", knowledge_ids)
        print("    Done")
    else:
        print(f"==> {_KNOWLEDGE_TABLE}: nothing to delete")

    print(f"""
==> Clear complete.
    tickets  : {len(ticket_ids)} deleted
    knowledge: {len(knowledge_ids)} deleted
    vectors  : {len(ticket_ids)} deleted (resolved tickets only)
    SQS      : all queues purged

Note: DynamoDB Streams の残処理が knowledge-consumer を再トリガーする場合があります。
      30 秒後に Knowledge タブが空であることを確認してください。
""")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
