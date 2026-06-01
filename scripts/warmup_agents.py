"""Agent warm-up script — pre-warms Triage, Diagnosis, and Resolution agent containers.

AgentCore Runtime の DEFAULT エンドポイントはアイドル後の初回呼び出しで
コンテナ起動待ちが発生し RuntimeClientError になることがある。
このスクリプトはデモ前に軽量なリクエストを送って各コンテナを起動済み状態にする。

Usage:
    uv run python scripts/warmup_agents.py
"""

from __future__ import annotations

import json
import sys
import time
import uuid

import boto3

_REGION = "us-east-1"
_AGENTCORE_STACK = "AgoraStack"
_WARMUP_PAYLOAD = json.dumps({"message": "warm-up ping"}).encode()

_AGENT_NAMES = [
    ("Triage",      "agora_triage-uP753oEz32"),
    ("Diagnosis",   "agora_diagnosis-EUabSrCPzr"),
    ("Resolution",  "agora_resolution-4eGv3P423B"),
    ("Orchestrator","agora_orchestrator-bKwmnFAbLP"),
]

_MAX_RETRIES = 3
_RETRY_WAIT = 10  # seconds between retries


def _invoke(client, runtime_id: str) -> str:
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=f"arn:aws:bedrock-agentcore:{_REGION}:346929044083:runtime/{runtime_id}",
        qualifier="DEFAULT",
        payload=_WARMUP_PAYLOAD,
        runtimeSessionId=str(uuid.uuid4()),
    )
    body: bytes = resp["response"].read()
    try:
        return json.loads(body).get("response", body.decode())[:80]
    except Exception:
        return body.decode()[:80]


def warmup(client, name: str, runtime_id: str) -> bool:
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            result = _invoke(client, runtime_id)
            print(f"  ✅ {name}: OK — {result!r}")
            return True
        except Exception as e:
            err = str(e)[:120]
            if attempt < _MAX_RETRIES:
                print(f"  ⏳ {name}: attempt {attempt} failed ({err}) — retrying in {_RETRY_WAIT}s")
                time.sleep(_RETRY_WAIT)
            else:
                print(f"  ⚠️  {name}: all {_MAX_RETRIES} attempts failed ({err})")
    return False


def main() -> None:
    client = boto3.client("bedrock-agentcore", region_name=_REGION)
    print("==> Warming up AgentCore Runtime containers ...")
    print("    (軽量リクエストを送り、コンテナの起動を完了させます)\n")

    results: dict[str, bool] = {}
    for name, runtime_id in _AGENT_NAMES:
        results[name] = warmup(client, name, runtime_id)
        time.sleep(2)  # 連続呼び出しのレート制限対策

    failed = [n for n, ok in results.items() if not ok]
    if failed:
        print(f"\n⚠️  Warm-up incomplete: {', '.join(failed)} did not respond.")
        print("   デモを続行しますが、該当エージェントはコールドスタートの可能性があります。")
        sys.exit(1)
    else:
        print("\n✅ All agents warm. Demo ready.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
