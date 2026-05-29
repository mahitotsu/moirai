"""
AgentCore Registry ディスカバリーユーティリティ。

エージェントはこのモジュールを使用して、AgentCore Registry（'agora_registry'）に
クエリすることでMCPゲートウェイURLとA2Aエージェントランタイムのarnを取得します。

すべてのルックアップはモジュールレベルでキャッシュされるため、
Registry APIコールはコンテナのライフタイム中に1回のみ発生します。

Example:
    from registry import get_mcp_gateway_url, get_agent_runtime_arn
    from registry import TRIAGE_AGENT_RECORD, DIAGNOSIS_AGENT_RECORD, RESOLUTION_AGENT_RECORD

    url = get_mcp_gateway_url()
    arn = get_agent_runtime_arn(TRIAGE_AGENT_RECORD)
"""

from __future__ import annotations

import json
import logging

import boto3

_bedrock_agent = boto3.client("bedrock-agent")

logger = logging.getLogger(__name__)

REGISTRY_NAME = "agora_registry"
_ACTIVE_STATUSES = {"DRAFT", "APPROVED"}

# Registryレコード名 — registry_catalog_handler.py と一致している必要がある
MCP_GATEWAY_RECORD = "agora-mcp-gateway"
TRIAGE_AGENT_RECORD = "agora-triage-agent"
DIAGNOSIS_AGENT_RECORD = "agora-diagnosis-agent"
RESOLUTION_AGENT_RECORD = "agora-resolution-agent"

_control = boto3.client("bedrock-agentcore-control")

# モジュールレベルキャッシュ: 同一コンテナ内の複数呼び出しにわたって保持される
_cache: dict[str, object] = {}


# ---------------------------------------------------------------------------
# 内部ヘルパー
# ---------------------------------------------------------------------------


def _registry_id() -> str:
    if "_registry_id" not in _cache:
        resp = _control.list_registries()
        for reg in resp.get("registries", []):
            if reg["name"] == REGISTRY_NAME and reg["status"] == "READY":
                _cache["_registry_id"] = reg["registryId"]
                return _cache["_registry_id"]  # type: ignore[return-value]
        raise RuntimeError(f"Registry '{REGISTRY_NAME}' not found or not READY")
    return _cache["_registry_id"]  # type: ignore[return-value]


def _list_all_records(descriptor_type: str) -> list[dict]:
    registry_id = _registry_id()
    records: list[dict] = []
    kwargs: dict = {"registryId": registry_id, "descriptorType": descriptor_type}
    while True:
        resp = _control.list_registry_records(**kwargs)
        records.extend(resp.get("registryRecords", []))
        token = resp.get("nextToken")
        if not token:
            break
        kwargs["nextToken"] = token
    return records


def _get_mcp_inline(record: dict) -> dict | None:
    try:
        detail = _control.get_registry_record(
            registryId=_registry_id(), recordId=record["recordId"]
        )
        descriptors = detail.get("descriptors", {})
        raw = descriptors.get("mcp", {}).get("server", {}).get("inlineContent", "{}")
        return json.loads(raw)
    except Exception:
        return None


def _get_a2a_inline(record: dict) -> dict | None:
    try:
        detail = _control.get_registry_record(
            registryId=_registry_id(), recordId=record["recordId"]
        )
        descriptors = detail.get("descriptors", {})
        raw = descriptors.get("a2a", {}).get("agentCard", {}).get("inlineContent", "{}")
        return json.loads(raw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------


def get_mcp_gateway_url() -> str:
    """MCPゲートウェイURLを返す。初回呼び出し時にRegistryから取得し、以降はキャッシュを使用。"""
    cache_key = "mcp_gateway_url"
    if cache_key not in _cache:
        for rec in _list_all_records("MCP"):
            if rec["name"] == MCP_GATEWAY_RECORD:
                content = _get_mcp_inline(rec)
                if content:
                    url = content.get("url", "")
                    if url:
                        _cache[cache_key] = url
                        logger.info("Discovered MCP Gateway URL from Registry")
                        return url  # type: ignore[return-value]
        raise RuntimeError(f"Registry record '{MCP_GATEWAY_RECORD}' not found or URL missing")
    return _cache[cache_key]  # type: ignore[return-value]


def get_agent_runtime_arn(record_name: str) -> str:
    """登録済みエージェントのruntimeArnを返す。初回呼び出し時にRegistryから取得。"""
    cache_key = f"arn:{record_name}"
    if cache_key not in _cache:
        for rec in _list_all_records("A2A"):
            if rec["name"] == record_name:
                content = _get_a2a_inline(rec)
                if content:
                    arn = content.get("runtimeArn", "")
                    if arn:
                        _cache[cache_key] = arn
                        logger.info("Discovered runtime ARN for '%s' from Registry", record_name)
                        return arn  # type: ignore[return-value]
        raise RuntimeError(f"Registry record '{record_name}' not found or runtimeArn missing")
    return _cache[cache_key]  # type: ignore[return-value]


def discover_by_capability(capability: str) -> list[dict]:
    """指定したcapabilityタグを持つすべてのMCPサーバーを返す。

    各エントリには name、runtime_arn、runtime_id、endpoint_id が含まれる。
    """
    results: list[dict] = []
    for rec in _list_all_records("MCP"):
        if rec.get("status") not in _ACTIVE_STATUSES:
            continue
        content = _get_mcp_inline(rec)
        if not content or content.get("capability") != capability:
            continue
        runtime_arn = content.get("runtimeArn", "")
        results.append({
            "name": content.get("runtimeName", rec["name"]),
            "runtime_arn": runtime_arn,
            "runtime_id": runtime_arn.split("/")[-1] if runtime_arn else "",
            "endpoint_id": content.get("endpointId", ""),
        })
    return results


def fetch_system_prompt(arn: str) -> str:
    """ARNを指定してBedrock Prompt ManagementからプロンプトテキストをFetchする。

    デフォルトバリアントのテキストテンプレートを取得する。失敗時はRuntimeErrorを送出。
    モジュールレベルのキャッシュによりコンテナのライフタイム中に最大1回のAPIコール。
    """
    cache_key = f"prompt:{arn}"
    if cache_key not in _cache:
        resp = _bedrock_agent.get_prompt(promptIdentifier=arn)
        variants = resp.get("variants", [])
        if not variants:
            raise RuntimeError(f"No variants found for prompt ARN: {arn}")
        text = variants[0]["templateConfiguration"]["text"]["text"]
        _cache[cache_key] = text
        logger.info("Fetched system prompt from Bedrock Prompt Management: %s", arn)
    return _cache[cache_key]  # type: ignore[return-value]


def discover_skills(skill_names: list[str]) -> list:
    """Registryから指定したスキル名のStrands Skillオブジェクトを返す。

    "agora-{skill_name}" に一致するAGENT_SKILLSレコードを検索する。
    結果はモジュールレベルでキャッシュされる。コンテナのライフタイム中に1回呼び出すこと。
    """
    from strands import Skill

    cache_key = f"skills:{','.join(sorted(skill_names))}"
    if cache_key in _cache:
        return _cache[cache_key]  # type: ignore[return-value]

    results: list = []
    name_set = {f"agora-{n}" for n in skill_names}
    for rec in _list_all_records("AGENT_SKILLS"):
        if rec.get("name") not in name_set:
            continue
        if rec.get("status") not in _ACTIVE_STATUSES:
            logger.warning("Skill record '%s' not in active status — skipping", rec.get("name"))
            continue
        try:
            detail = _control.get_registry_record(
                registryId=_registry_id(), recordId=rec["recordId"]
            )
            skill_md = (
                detail.get("descriptors", {})
                .get("agentSkills", {})
                .get("skillMd", {})
            )
            markdown = skill_md.get("inlineContent", "") if isinstance(skill_md, dict) else skill_md
            if markdown:
                results.append(Skill.from_content(markdown))
                logger.info("Loaded skill '%s' from Registry", rec["name"])
        except Exception:
            logger.exception("Failed to load skill '%s'", rec.get("name"))

    _cache[cache_key] = results
    return results


def get_registry_mcp_url() -> str:
    """Registry MCP エンドポイント URL を返す。IAM SigV4 認証が必要。"""
    session = boto3.session.Session()
    region = session.region_name or "us-east-1"
    return f"https://bedrock-agentcore.{region}.amazonaws.com/registry/{_registry_id()}/mcp"


def fetch_skill_by_name(name: str) -> object | None:
    """スキル名で Skill オブジェクトを取得する。name は 'api-error-diagnosis-runbook' 形式。

    Registry から SKILL.md 本文を取得して Skill.from_content() で返す。
    見つからない場合は None を返す。
    """
    from strands import Skill

    record_name = f"agora-{name}"
    cache_key = f"skill:{record_name}"
    if cache_key in _cache:
        return _cache[cache_key]

    for rec in _list_all_records("AGENT_SKILLS"):
        if rec.get("name") != record_name:
            continue
        if rec.get("status") not in _ACTIVE_STATUSES:
            logger.warning("Skill record '%s' not in active status — skipping", record_name)
            continue
        try:
            detail = _control.get_registry_record(
                registryId=_registry_id(), recordId=rec["recordId"]
            )
            skill_md_obj = detail.get("descriptors", {}).get("agentSkills", {}).get("skillMd", {})
            markdown = (
                skill_md_obj.get("inlineContent", "")
                if isinstance(skill_md_obj, dict)
                else skill_md_obj
            )
            if markdown:
                skill = Skill.from_content(markdown)
                _cache[cache_key] = skill
                logger.info("Fetched skill '%s' from Registry", record_name)
                return skill
        except Exception:
            logger.exception("Failed to fetch skill '%s'", record_name)

    logger.warning("Skill '%s' not found in Registry", record_name)
    return None


def discover_a2a_agents() -> list[dict]:
    """capability='a2a-agent' を持つすべてのA2Aエージェントを返す。

    各エントリには name、agent_type、runtime_arn、runtime_id、endpoint_id が含まれる。
    """
    results: list[dict] = []
    for rec in _list_all_records("A2A"):
        if rec.get("status") not in _ACTIVE_STATUSES:
            continue
        content = _get_a2a_inline(rec)
        if not content or content.get("capability") != "a2a-agent":
            continue
        runtime_arn = content.get("runtimeArn", "")
        results.append({
            "name": content.get("name", rec["name"]),
            "agent_type": content.get("agentType", "unknown"),
            "runtime_arn": runtime_arn,
            "runtime_id": runtime_arn.split("/")[-1] if runtime_arn else "",
            "endpoint_id": content.get("endpointId", ""),
        })
    return results
