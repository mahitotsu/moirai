from __future__ import annotations

import json
import time
from typing import Any

import boto3
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "infrastructure-inspector-mcp",
    host="0.0.0.0",
    port=8000,
    stateless_http=True,
)

_clients: dict[str, Any] = {}


def _lambda() -> Any:
    if "lambda" not in _clients:
        _clients["lambda"] = boto3.client("lambda")
    return _clients["lambda"]


def _fis() -> Any:
    if "fis" not in _clients:
        _clients["fis"] = boto3.client("fis")
    return _clients["fis"]


def _cfn() -> Any:
    if "cfn" not in _clients:
        _clients["cfn"] = boto3.client("cloudformation")
    return _clients["cfn"]


def _logs() -> Any:
    if "logs" not in _clients:
        _clients["logs"] = boto3.client("logs")
    return _clients["logs"]


@mcp.tool()
def inspect_lambda(function_name: str) -> str:
    """AWS Lambda関数の設定・タグ・トリガー情報を取得する。

    障害が発生しているLambda関数の動作内容、設定（タイムアウト・メモリ・環境変数）、
    イベントソース（トリガー）、および所有するCloudFormationスタックを把握するために使用する。
    'aws:cloudformation:stack-name' タグ（存在する場合）を describe_cfn_stack と組み合わせることで
    完全なリソーストポロジーを探索できる。

    Args:
        function_name: Lambda関数の名前またはARN（例："agora-fake-api-server"）。

    Returns:
        関数の説明、ランタイム、タイムアウト、メモリ、環境変数キー、
        イベントソースマッピング（トリガー）、および全リソースタグ。
    """
    try:
        resp = _lambda().get_function(FunctionName=function_name)
        config = resp["Configuration"]
        function_arn = config["FunctionArn"]
        env_keys = list(config.get("Environment", {}).get("Variables", {}).keys())

        esm_resp = _lambda().list_event_source_mappings(FunctionName=function_name)
        triggers = [
            f"{m.get('EventSourceArn', 'unknown')} (state: {m.get('State', 'unknown')})"
            for m in esm_resp.get("EventSourceMappings", [])
        ]

        tags_resp = _lambda().list_tags(Resource=function_arn)
        tags = tags_resp.get("Tags", {})

        lines = [
            f"## Lambda Function: {config['FunctionName']}",
            f"ARN: {function_arn}",
            f"Description: {config.get('Description', '(none)')}",
            f"Runtime: {config.get('Runtime', 'N/A')}",
            f"Handler: {config.get('Handler', 'N/A')}",
            f"Timeout: {config.get('Timeout', 'N/A')}s",
            f"Memory: {config.get('MemorySize', 'N/A')} MB",
            f"Last modified: {config.get('LastModified', 'N/A')}",
            f"Environment variables (keys only): {', '.join(env_keys) if env_keys else '(none)'}",
            f"Event source mappings: {'; '.join(triggers) if triggers else '(none)'}",
        ]

        if tags:
            lines.append("Tags:")
            for k, v in sorted(tags.items()):
                lines.append(f"  {k}: {v}")
        else:
            lines.append("Tags: (none)")

        return "\n".join(lines)
    except Exception as e:
        return f"Failed to inspect Lambda '{function_name}': {e}"


@mcp.tool()
def get_lambda_recent_errors(function_name: str, minutes: int = 15) -> str:
    """Lambda関数のCloudWatchロググループから直近のエラーと例外ログ行を取得する。

    Lambdaアラームが発生した際に最初に呼び出すツール。例外の種類・エラーコード・スタックトレースなど
    実際のエラーメッセージを表示し、何が失敗しているかを事前知識なしで把握できる。

    Args:
        function_name: Lambda関数名（例："agora-fake-api-server"）。
        minutes: 何分前まで遡って検索するか（デフォルト15分）。

    Returns:
        ERROR、Exception、Tracebackを含む直近のログ行（最大30件）とタイムスタンプ。
        エラーが見つからない場合はその旨を示すメッセージを返す。
    """
    log_group = f"/aws/lambda/{function_name}"
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (minutes * 60 * 1000)

    try:
        resp = _logs().filter_log_events(
            logGroupName=log_group,
            startTime=start_ms,
            endTime=end_ms,
            filterPattern="?ERROR ?Exception ?Traceback",
            limit=30,
        )
        events = resp.get("events", [])
        if not events:
            return (
                f"No ERROR/Exception/Traceback log lines found in "
                f"/aws/lambda/{function_name} in the last {minutes} minutes."
            )

        lines = [f"## Recent errors from /aws/lambda/{function_name} (last {minutes} min)"]
        for ev in events:
            ts_sec = ev.get("timestamp", 0) // 1000
            ts_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts_sec))
            message = ev.get("message", "").rstrip()
            lines.append(f"[{ts_str}] {message}")

        return "\n".join(lines)
    except Exception as e:
        return f"Failed to fetch logs for '{function_name}': {e}"


@mcp.tool()
def list_active_fis_experiments() -> str:
    """実行中のAWS FIS（Fault Injection Simulator）実験を一覧表示する。

    環境で現在実行中のフォルトインジェクションを確認するために使用する。
    実験ID・インジェクションされた障害の種類・ターゲットリソース・開始時刻を返す。
    アラームが発生し、根本原因が意図的なフォルトインジェクションである可能性がある場合に呼び出す。

    Returns:
        実行中のFIS実験の詳細（インジェクションされている障害を含む）、
        または実験が実行されていないことを示すメッセージ。
    """
    try:
        resp = _fis().list_experiments()
        experiments = [
            e for e in resp.get("experiments", [])
            if e.get("state", {}).get("status") == "running"
        ]
        if not experiments:
            return "No FIS experiments are currently running."

        lines = ["## Active FIS Experiments"]
        for exp in experiments:
            exp_id = exp.get("id", "unknown")
            template_id = exp.get("experimentTemplateId", "unknown")

            detail_resp = _fis().get_experiment(id=exp_id)
            detail = detail_resp.get("experiment", {})
            state = detail.get("state", {})
            actions = detail.get("actions", {})
            targets = detail.get("targets", {})

            lines.append(f"\n### Experiment: {exp_id}")
            lines.append(f"Template: {template_id}")
            lines.append(f"State: {state.get('status', 'unknown')}")
            lines.append(f"Started: {detail.get('startTime', 'unknown')}")

            if actions:
                lines.append("Actions (faults being injected):")
                for action_id, action in actions.items():
                    lines.append(f"  - {action_id}: {action.get('actionId', 'unknown')}")
                    for k, v in action.get("parameters", {}).items():
                        lines.append(f"    {k}: {v}")

            if targets:
                lines.append("Targets:")
                for target_id, target in targets.items():
                    lines.append(
                        f"  - {target_id}: {target.get('resourceType', 'unknown')}"
                        f" ({json.dumps(target.get('resourceArns', target.get('filters', [])))})"
                    )

        return "\n".join(lines)
    except Exception as e:
        return f"Failed to list FIS experiments: {e}"


@mcp.tool()
def describe_cfn_stack(stack_name: str) -> str:
    """AWS CloudFormationスタックとデプロイ済みリソースを説明する。

    障害が発生しているサービスを支えるインフラコンポーネントを把握するために使用する。
    FaultInjectionStack（fake-api-server LambdaとFISテンプレートを含む）や
    AgoraStackの検査に特に有用。

    Args:
        stack_name: CloudFormationスタック名（例："FaultInjectionStack"、"AgoraStack"）。

    Returns:
        スタックのステータス・作成時刻・全リソースの一覧（リソースタイプ・論理ID・物理ID付き）。
    """
    try:
        stacks_resp = _cfn().describe_stacks(StackName=stack_name)
        stack = stacks_resp["Stacks"][0]

        resources_resp = _cfn().describe_stack_resources(StackName=stack_name)
        resources = resources_resp.get("StackResources", [])

        lines = [
            f"## CloudFormation Stack: {stack['StackName']}",
            f"Status: {stack['StackStatus']}",
            f"Created: {stack.get('CreationTime', 'N/A')}",
            f"Description: {stack.get('Description', '(none)')}",
            "",
            f"Resources ({len(resources)}):",
        ]
        for r in resources:
            physical = r.get("PhysicalResourceId", "(pending)")
            lines.append(
                f"  - [{r['ResourceType']}] {r['LogicalResourceId']}"
                f" → {physical} ({r['ResourceStatus']})"
            )

        return "\n".join(lines)
    except Exception as e:
        return f"Failed to describe CloudFormation stack '{stack_name}': {e}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
