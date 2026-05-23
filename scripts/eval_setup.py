"""
Agora — OnlineEvaluationConfig セットアップスクリプト

前提条件:
  1. make cdk-deploy が完了していること
  2. make obs-setup が完了していること (make eval-setup が自動実行する)
  3. Gateway エージェントが少なくとも1回呼び出されていること
     (X-Ray トレースが生成されることで bedrock-agentcore 評価レジストリが初期化される)

使い方: make eval-setup
"""
from __future__ import annotations

import sys

import boto3

_REGION = "us-east-1"
_STACK = "AgoraStack"

_CONFIGS = [
    {
        "name": "agora_gateway_evaluation",
        "logical_id": "AgoraGatewayRuntime",
        "endpoint": "agora_gateway_ep",
        "runtime_name": "agora_gateway",
        "evaluators": ["Builtin.Helpfulness", "Builtin.Faithfulness"],
        "description": "Gateway Agent online evaluation — HELPFULNESS / FAITHFULNESS",
    },
    {
        "name": "agora_triage_evaluation",
        "logical_id": "AgoraTriageRuntime",
        "endpoint": "agora_triage_ep",
        "runtime_name": "agora_triage",
        "evaluators": ["Builtin.ToolSelectionAccuracy"],
        "description": "Triage Agent online evaluation — TOOL_SELECTION_ACCURACY",
    },
    {
        "name": "agora_diagnosis_evaluation",
        "logical_id": "AgoraDiagnosisRuntime",
        "endpoint": "agora_diagnosis_ep",
        "runtime_name": "agora_diagnosis",
        "evaluators": ["Builtin.Correctness"],
        "description": "Diagnosis Agent online evaluation — CORRECTNESS",
    },
    {
        "name": "agora_resolution_evaluation",
        "logical_id": "AgoraResolutionRuntime",
        "endpoint": "agora_resolution_ep",
        "runtime_name": "agora_resolution",
        "evaluators": ["Builtin.Faithfulness"],
        "description": "Resolution Agent online evaluation — FAITHFULNESS",
    },
]


def _runtime_id(cf: boto3.client, logical_id: str) -> str:
    resp = cf.describe_stack_resource(
        StackName=_STACK, LogicalResourceId=logical_id
    )
    return resp["StackResourceDetail"]["PhysicalResourceId"]


def _eval_role_arn(sts: boto3.client) -> str:
    account = sts.get_caller_identity()["Account"]
    return f"arn:aws:iam::{account}:role/agora-evaluation-execution-role"


def _check_transaction_search(xray: boto3.client) -> bool:
    """X-Ray trace segment destination が CloudWatchLogs/ACTIVE であることを確認する。"""
    resp = xray.get_trace_segment_destination()
    return resp.get("Destination") == "CloudWatchLogs" and resp.get("Status") == "ACTIVE"


def main() -> None:
    cf = boto3.client("cloudformation", region_name=_REGION)
    xray = boto3.client("xray", region_name=_REGION)
    sts = boto3.client("sts")
    client = boto3.client("bedrock-agentcore-control", region_name=_REGION)

    if not _check_transaction_search(xray):
        print(
            "ERROR: CloudWatch Transaction Search が有効ではありません。\n"
            "  'make obs-setup' を実行してから再試行してください。"
        )
        sys.exit(1)

    role_arn = _eval_role_arn(sts)
    existing = {
        c["onlineEvaluationConfigName"]
        for c in client.list_online_evaluation_configs().get("onlineEvaluationConfigs", [])
    }

    ok = 0
    log_group_error = False
    for cfg in _CONFIGS:
        if cfg["name"] in existing:
            print(f"  SKIP {cfg['name']} (already exists)")
            ok += 1
            continue
        try:
            rid = _runtime_id(cf, cfg["logical_id"])
        except Exception as e:
            print(f"  FAIL {cfg['name']}: runtime ID を解決できません — {e}")
            continue
        log_group = f"/aws/bedrock-agentcore/runtimes/{rid}-{cfg['endpoint']}"
        service_name = f"{cfg['runtime_name']}.{cfg['endpoint']}"
        try:
            client.create_online_evaluation_config(
                onlineEvaluationConfigName=cfg["name"],
                description=cfg["description"],
                dataSourceConfig={
                    "cloudWatchLogs": {
                        "logGroupNames": [log_group],
                        "serviceNames": [service_name],
                    }
                },
                evaluators=[{"evaluatorId": e} for e in cfg["evaluators"]],
                rule={"samplingConfig": {"samplingPercentage": 100}},
                evaluationExecutionRoleArn=role_arn,
                enableOnCreate=True,
            )
            print(f"  OK  {cfg['name']}")
            ok += 1
        except Exception as e:
            msg = str(e)
            if "log groups do not exist" in msg.lower():
                log_group_error = True
                print(f"  FAIL {cfg['name']}: {e}")
            else:
                print(f"  FAIL {cfg['name']}: {e}")

    if log_group_error:
        print(
            "\n[ヒント] 'One or more specified log groups do not exist' エラーは\n"
            "  bedrock-agentcore 評価レジストリの未初期化を示します。\n"
            "  Gateway エージェントを少なくとも1回呼び出してから再試行してください。\n"
            "  (X-Ray トレースが生成されることでレジストリが初期化されます)"
        )

    if ok < len(_CONFIGS):
        sys.exit(1)


if __name__ == "__main__":
    main()
