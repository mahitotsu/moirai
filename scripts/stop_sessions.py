"""Stop all active AgentCore Runtime sessions.

CloudWatch Logs から直近 2時間のセッション ID を収集し、
全アクティブセッションを停止してVM スロットを解放する。

Usage:
    uv run python scripts/stop_sessions.py
"""

from __future__ import annotations

import re
import sys
import time

import boto3
from botocore.exceptions import ClientError

_REGION = "us-east-1"
_SESSION_LOG_LOOKBACK_SEC = 7200  # 2時間
_AGENT_RUNTIMES = [
    ("orchestrator", "agora_orchestrator-bKwmnFAbLP",
     "arn:aws:bedrock-agentcore:us-east-1:346929044083:runtime/agora_orchestrator-bKwmnFAbLP"),
    ("triage",       "agora_triage-uP753oEz32",
     "arn:aws:bedrock-agentcore:us-east-1:346929044083:runtime/agora_triage-uP753oEz32"),
    ("diagnosis",    "agora_diagnosis-EUabSrCPzr",
     "arn:aws:bedrock-agentcore:us-east-1:346929044083:runtime/agora_diagnosis-EUabSrCPzr"),
    ("resolution",   "agora_resolution-4eGv3P423B",
     "arn:aws:bedrock-agentcore:us-east-1:346929044083:runtime/agora_resolution-4eGv3P423B"),
]


def stop_all_sessions() -> int:
    agentcore = boto3.client("bedrock-agentcore", region_name=_REGION)
    logs = boto3.client("logs", region_name=_REGION)
    start_ms = int((time.time() - _SESSION_LOG_LOOKBACK_SEC) * 1000)
    total_stopped = 0

    for name, runtime_id, runtime_arn in _AGENT_RUNTIMES:
        log_group = f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT"
        session_ids: set[str] = set()

        kwargs: dict = {
            "logGroupName": log_group,
            "startTime": start_ms,
            "filterPattern": "sessionId",
        }
        try:
            while True:
                resp = logs.filter_log_events(**kwargs)
                for event in resp.get("events", []):
                    for sid in re.findall(
                        r'"sessionId"\s*:\s*"([0-9a-f-]{36})"', event["message"]
                    ):
                        session_ids.add(sid)
                token = resp.get("nextToken")
                if not token:
                    break
                kwargs["nextToken"] = token
        except ClientError:
            pass

        stopped = 0
        for sid in session_ids:
            try:
                agentcore.stop_runtime_session(
                    agentRuntimeArn=runtime_arn,
                    runtimeSessionId=sid,
                )
                stopped += 1
            except ClientError:
                pass

        total_stopped += stopped
        if stopped:
            print(f"    {name}: stopped {stopped} sessions")
        else:
            print(f"    {name}: no active sessions")

    return total_stopped


def main() -> None:
    print("==> Stopping all active AgentCore Runtime sessions ...")
    total = stop_all_sessions()
    print(f"\n    Total stopped: {total}")
    if total == 0:
        print("    (all sessions already terminated)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
