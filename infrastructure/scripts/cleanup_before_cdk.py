"""
CDKデプロイ前クリーンアップスクリプト。

スクリプトで手動登録した以下のリソースを削除する:
  - Registry records（CDKデプロイ後に新ARNで register_catalog.py が再登録する）
  - Gateway targets → Gateway → ApiKeyCredentialProvider
  - CDK管理対象のRuntime endpoints → Runtimes

削除しないもの:
  - agora_registry 本体（register_catalog.py が再利用する）
  - agora_ticket_service / agora_asset_service Runtime（CDK管理外）

Usage:
    uv run --package agora-infrastructure python infrastructure/scripts/cleanup_before_cdk.py
"""

from __future__ import annotations

import sys
import time

import boto3

REGION = "us-east-1"

# CDKが管理する runtime name の集合
CDK_MANAGED_RUNTIMES = {
    "agora_stackoverflow",
    "agora_github_issues",
    "agora_wikipedia",
    "agora_aws_docs",
    "agora_triage",
    "agora_diagnosis",
    "agora_resolution",
    "agora_gateway",
}


def _wait_deleted(check_fn, label: str, interval: int = 5, max_tries: int = 24) -> None:
    for _ in range(max_tries):
        try:
            check_fn()
            time.sleep(interval)
        except ctrl.exceptions.ResourceNotFoundException:
            return
        except Exception:
            time.sleep(interval)
    print(f"  WARNING: {label} did not confirm deletion within timeout")


ctrl = boto3.client("bedrock-agentcore-control", region_name=REGION)


# ---------------------------------------------------------------------------
# 1. Registry records
# ---------------------------------------------------------------------------
def cleanup_registry_records() -> None:
    print("=== 1. Deleting registry records ===")
    resp = ctrl.list_registries()
    for reg in resp.get("registries", []):
        reg_id = reg["registryId"]
        print(f"  Registry: {reg['name']} ({reg_id})")
        kwargs: dict = {"registryId": reg_id}
        while True:
            rec_resp = ctrl.list_registry_records(**kwargs)
            for rec in rec_resp.get("registryRecords", []):
                ctrl.delete_registry_record(registryId=reg_id, recordId=rec["recordId"])
                print(f"    Deleted record: {rec['name']}")
            token = rec_resp.get("nextToken")
            if not token:
                break
            kwargs["nextToken"] = token


# ---------------------------------------------------------------------------
# 2. Gateway targets → Gateway → ApiKeyCredentialProvider
# ---------------------------------------------------------------------------
def cleanup_gateway() -> None:
    print("=== 2. Deleting gateway targets, gateway, and credential provider ===")
    gateways = ctrl.list_gateways().get("items", [])
    for gw in gateways:
        gw_id = gw["gatewayId"]
        print(f"  Gateway: {gw['name']} ({gw_id})")
        targets = ctrl.list_gateway_targets(gatewayIdentifier=gw_id).get("items", [])
        for t in targets:
            ctrl.delete_gateway_target(gatewayIdentifier=gw_id, targetId=t["targetId"])
            print(f"    Deleted target: {t['name']}")

        # 全targetが消えるまで待つ
        for _ in range(30):
            remaining = ctrl.list_gateway_targets(gatewayIdentifier=gw_id).get("items", [])
            if not remaining:
                break
            print(f"    Waiting for targets to be deleted ... ({len(remaining)} remaining)")
            time.sleep(5)

        ctrl.delete_gateway(gatewayIdentifier=gw_id)
        print(f"  Deleted gateway: {gw['name']}")

    creds = ctrl.list_api_key_credential_providers().get("credentialProviders", [])
    for c in creds:
        ctrl.delete_api_key_credential_provider(name=c["name"])
        print(f"  Deleted credential provider: {c['name']}")


# ---------------------------------------------------------------------------
# 3. Runtime endpoints → Runtimes (CDK管理対象のみ)
# ---------------------------------------------------------------------------
def cleanup_runtimes() -> None:
    print("=== 3. Deleting CDK-managed runtime endpoints and runtimes ===")
    runtimes = ctrl.list_agent_runtimes().get("agentRuntimes", [])
    to_delete = [r for r in runtimes if r["agentRuntimeName"] in CDK_MANAGED_RUNTIMES]

    # 手動作成の名前付きエンドポイント(DEFAULT以外)を先に削除
    for rt in to_delete:
        rt_id = rt["agentRuntimeId"]
        rt_name = rt["agentRuntimeName"]
        eps = ctrl.list_agent_runtime_endpoints(agentRuntimeId=rt_id).get("runtimeEndpoints", [])
        named_eps = [e for e in eps if e["name"] != "DEFAULT"]
        for ep in named_eps:
            ctrl.delete_agent_runtime_endpoint(agentRuntimeId=rt_id, endpointName=ep["name"])
            print(f"  Deleted endpoint: {rt_name}/{ep['name']}")

    # 名前付きエンドポイントのDELETING完了を待ってからRuntime削除
    for rt in to_delete:
        rt_id = rt["agentRuntimeId"]
        rt_name = rt["agentRuntimeName"]
        for _ in range(36):
            eps = ctrl.list_agent_runtime_endpoints(
                agentRuntimeId=rt_id
            ).get("runtimeEndpoints", [])
            blocking = [e for e in eps if e["name"] != "DEFAULT" and e["status"] != "DELETING"]
            if not blocking:
                break
            time.sleep(5)
        # DELETINGが残っていてもRuntime削除をリトライ(最大3分)
        for attempt in range(36):
            try:
                ctrl.delete_agent_runtime(agentRuntimeId=rt_id)
                print(f"  Deleted runtime: {rt_name}")
                break
            except ctrl.exceptions.ConflictException:
                if attempt < 35:
                    time.sleep(5)
                else:
                    raise

    # DELETINGが完全に消えるまで待つ
    names = {rt["agentRuntimeName"] for rt in to_delete}
    for _ in range(72):
        remaining = [
            r["agentRuntimeName"]
            for r in ctrl.list_agent_runtimes().get("agentRuntimes", [])
            if r["agentRuntimeName"] in names
        ]
        if not remaining:
            break
        time.sleep(5)

    skipped = [
        r["agentRuntimeName"] for r in runtimes if r["agentRuntimeName"] not in CDK_MANAGED_RUNTIMES
    ]
    if skipped:
        print(f"  Kept (not CDK-managed): {', '.join(skipped)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("CDKデプロイ前クリーンアップを開始します ...\n")

    try:
        cleanup_registry_records()
        cleanup_gateway()
        cleanup_runtimes()
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    print("\n完了。次のステップ:")
    print("  1. make cdk-deploy")
    print("  2. uv run --package agora-infrastructure python infrastructure/scripts/register_catalog.py")  # noqa: E501


if __name__ == "__main__":
    main()
