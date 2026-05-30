"""Pipeline test script — triggers the agent pipeline without FIS injection.

Usage:
    uv run python scripts/pipeline_test.py

Creates a ticket with title starting with "CloudWatch ALARM:" which causes
ticket-dispatcher to invoke the Pipeline Orchestrator immediately, bypassing
the FIS → CloudWatch Alarm → Bridge Lambda flow.

Useful for:
  - デモ本番前のパイプライン単体確認
  - seed 後の Triage → Diagnosis → Resolution の動作検証
  - e2e フロー全体の staging 確認
"""

from __future__ import annotations

import sys

import boto3
import httpx

_REGION = "us-east-1"
_AGORA_STACK = "AgoraStack"
_API_KEY_SECRET = "agora/services-api-key"


def _resolve_ticket_url() -> str:
    cfn = boto3.client("cloudformation", region_name=_REGION)
    resp = cfn.describe_stacks(StackName=_AGORA_STACK)
    for output in resp["Stacks"][0].get("Outputs", []):
        if output["OutputKey"] == "TicketFunctionUrl":
            return output["OutputValue"].rstrip("/")
    raise RuntimeError(
        f"TicketFunctionUrl not found in {_AGORA_STACK}. Run 'make cdk-deploy' first."
    )


def _resolve_api_key() -> str:
    sm = boto3.client("secretsmanager", region_name=_REGION)
    return sm.get_secret_value(SecretId=_API_KEY_SECRET)["SecretString"]


def main() -> None:
    print("==> Resolving Ticket Service URL from CloudFormation ...")
    base_url = _resolve_ticket_url()
    print(f"    URL: {base_url}")

    print("==> Fetching API key from Secrets Manager ...")
    api_key = _resolve_api_key()
    print("    OK")

    payload = {
        "title": "CloudWatch ALARM: agora-fake-api-error-rate",
        "description": (
            "EC2 DescribeInstances で ThrottlingException が発生しています。\n"
            "fake-api-server Lambda のエラーレートが急上昇しました。\n"
            "パイプラインテスト用の手動トリガーです。"
        ),
        "category": "other",
        "severity": "high",
    }

    print("\n==> Creating trigger ticket ...")
    resp = httpx.post(
        f"{base_url}/tickets",
        json=payload,
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    ticket = resp.json()
    ticket_id = ticket["ticket_id"]

    print(f"""
==> Ticket created: {ticket_id}
    title   : {ticket["title"]}
    status  : {ticket["status"]}
    severity: {ticket["severity"]}

==> Pipeline triggered.
    DynamoDB Streams → ticket-dispatcher → Pipeline Orchestrator が起動しました。
    Triage → Diagnosis → Resolution の完了まで約 60〜120 秒かかります。

確認方法:
  UI Tickets タブ    : open → investigating → resolved の遷移を確認
  UI Knowledge タブ  : lesson_learned の自動追記を確認 (resolved 後 ~30 秒)
  CloudWatch Logs    : /aws/lambda/agora-ticket-dispatcher
  Transaction Search : agora-orchestrator でトレースを確認
""")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
