from __future__ import annotations

import json
import logging
import threading
import uuid
from typing import Any

import boto3
import registry
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from botocore.config import Config
from pydantic_settings import BaseSettings
from strands import Agent, tool
from strands.models import BedrockModel, CacheConfig

logger = logging.getLogger(__name__)


class _Settings(BaseSettings):
    model_id: str = "us.anthropic.claude-sonnet-4-6"
    system_prompt_arn: str = ""


_settings = _Settings()
if not _settings.system_prompt_arn:
    raise RuntimeError("SYSTEM_PROMPT_ARN must be set")
_SYSTEM_PROMPT = registry.fetch_system_prompt(_settings.system_prompt_arn)

# サブエージェント呼び出しは Diagnosis のナレッジ検索 + LLM 推論で数分かかることがある。
# デフォルトの 60秒 read timeout だと ReadTimeoutError になりゾンビセッションが発生するため
# 300秒に拡大して確実に完了を待つ。
_agentcore = boto3.client(
    "bedrock-agentcore",
    config=Config(read_timeout=300, connect_timeout=10),
)
app = BedrockAgentCoreApp()


# ---------------------------------------------------------------------------
# サブエージェント呼び出しヘルパー
# ---------------------------------------------------------------------------


def _invoke_sub_agent(runtime_arn: str, message: str) -> str:
    session_id = str(uuid.uuid4())
    payload = json.dumps({"message": message}).encode()
    try:
        resp = _agentcore.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            qualifier="DEFAULT",
            payload=payload,
            runtimeSessionId=session_id,
        )
        body: bytes = resp["response"].read()
        try:
            data = json.loads(body)
            return data.get("response", body.decode())
        except Exception:
            return body.decode()
    except Exception:
        # 呼び出し失敗時はセッションを確実に停止してVMスロットを解放する
        try:
            _agentcore.stop_runtime_session(
                agentRuntimeArn=runtime_arn,
                runtimeSessionId=session_id,
            )
            logger.info("stopped session %s after error", session_id)
        except Exception:
            pass
        raise


@tool
def invoke_triage(incident_description: str) -> str:
    """ITインシデントを重要度とカテゴリで分類し、診断用の検索キーワードを生成する。

    Args:
        incident_description: 分類対象のITインシデントの完全な説明。

    Returns:
        重要度、カテゴリ、推奨検索キーワードを含むトリアージ結果。
    """
    arn = registry.get_agent_runtime_arn(registry.TRIAGE_AGENT_RECORD)
    return _invoke_sub_agent(arn, incident_description)


@tool
def invoke_diagnosis(triage_result: str) -> str:
    """コミュニティナレッジ、CloudWatchアラーム、過去チケットを検索してインシデントを診断する。

    Args:
        triage_result: トリアージ分類アウトプット（重要度、カテゴリ、検索キーワード）。

    Returns:
        推定根本原因と関連ナレッジソースを含む診断結果。
    """
    arn = registry.get_agent_runtime_arn(registry.DIAGNOSIS_AGENT_RECORD)
    return _invoke_sub_agent(arn, triage_result)


@tool
def invoke_resolution(diagnosis_result: str, ticket_id: str = "") -> str:
    """解決策を立案し、インシデントチケットを更新（または作成）する。

    Args:
        diagnosis_result: 解決策立案の根拠となる診断結果。
        ticket_id: 更新する既存チケットID。省略すると新規チケットを作成する。

    Returns:
        解決策とチケットの更新または作成の確認。
    """
    arn = registry.get_agent_runtime_arn(registry.RESOLUTION_AGENT_RECORD)
    message = diagnosis_result
    if ticket_id:
        message = f"{diagnosis_result}\n\nExisting ticket ID to update: {ticket_id}"
    return _invoke_sub_agent(arn, message)


# ---------------------------------------------------------------------------
# パイプライン実行 — バックグラウンドスレッドで動作
# ---------------------------------------------------------------------------


def _run_pipeline(task_id: int, prompt: str) -> None:
    try:
        agent = Agent(
            model=BedrockModel(
                model_id=_settings.model_id,
                cache_config=CacheConfig(strategy="auto"),
            ),
            system_prompt=_SYSTEM_PROMPT,
            tools=[invoke_triage, invoke_diagnosis, invoke_resolution],
        )
        agent(prompt)
        logger.info("pipeline completed for task %s", task_id)
    except Exception:
        logger.exception("pipeline failed for task %s", task_id)
    finally:
        app.complete_async_task(task_id)


@app.entrypoint
def invoke(payload: dict[str, Any], context: Any) -> dict[str, str]:
    prompt = payload.get("prompt", payload.get("message", ""))
    # add_async_task でセッションを HealthyBusy に遷移させ、呼び出し元にはすぐ返す。
    # パイプライン（Triage → Diagnosis → Resolution）はバックグラウンドスレッドで継続する。
    task_id = app.add_async_task("pipeline")
    threading.Thread(target=_run_pipeline, args=(task_id, prompt), daemon=True).start()
    return {"response": "診断パイプラインを開始しました。処理はバックグラウンドで継続されます。"}


if __name__ == "__main__":
    app.run()
