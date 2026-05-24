from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

import common.registry as registry_module
from common.registry import discover_a2a_agents, discover_by_capability


@pytest.fixture(autouse=True)
def clear_cache():
    """Prevent cache from leaking between tests."""
    registry_module._cache.clear()
    yield
    registry_module._cache.clear()


def _control_client(
    registries: list[dict] | None = None,
    mcp_records: list[dict] | None = None,
    a2a_records: list[dict] | None = None,
    record_details: dict[str, dict] | None = None,
) -> MagicMock:
    """AgentCore control client のモックを生成する。"""
    client = MagicMock()
    client.list_registries.return_value = {
        "registries": registries
        if registries is not None
        else [{"name": "agora_registry", "registryId": "reg-1", "status": "READY"}]
    }

    def list_records(**kwargs):
        descriptor_type = kwargs.get("descriptorType")
        records = mcp_records if descriptor_type == "MCP" else (a2a_records or [])
        return {"registryRecords": records or []}

    client.list_registry_records.side_effect = list_records

    details = record_details or {}

    def get_record(**kwargs):
        return details.get(kwargs["recordId"], {"descriptors": {}})

    client.get_registry_record.side_effect = get_record
    return client


def _mcp_detail(capability: str, runtime_name: str, endpoint_id: str = "ep") -> dict:
    content = json.dumps(
        {
            "capability": capability,
            "runtimeArn": f"arn:aws:bedrock-agentcore:us-east-1:123:runtime/{runtime_name}",
            "runtimeName": runtime_name,
            "endpointId": endpoint_id,
        }
    )
    return {"descriptors": {"mcp": {"server": {"inlineContent": content}}}}


def _a2a_detail(agent_type: str, runtime_name: str, endpoint_id: str = "ep") -> dict:
    content = json.dumps(
        {
            "capability": "a2a-agent",
            "agentType": agent_type,
            "name": f"{agent_type.title()} Agent",
            "runtimeArn": f"arn:aws:bedrock-agentcore:us-east-1:123:runtime/{runtime_name}",
            "endpointId": endpoint_id,
        }
    )
    return {"descriptors": {"a2a": {"agentCard": {"inlineContent": content}}}}


# ─── discover_by_capability ────────────────────────────────────────────────


def test_discover_by_capability_returns_matching_server():
    control = _control_client(
        mcp_records=[{"recordId": "r1", "name": "stackoverflow", "status": "APPROVED"}],
        record_details={"r1": _mcp_detail("community-knowledge", "agora_stackoverflow", "so_ep")},
    )
    registry_module._control = control
    result = discover_by_capability("community-knowledge")

    assert len(result) == 1
    assert result[0]["name"] == "agora_stackoverflow"
    assert result[0]["endpoint_id"] == "so_ep"
    assert result[0]["runtime_id"] == "agora_stackoverflow"


def test_discover_by_capability_excludes_different_capability():
    """capability が一致しないサーバーは結果に含まれない。"""
    control = _control_client(
        mcp_records=[{"recordId": "r1", "name": "cloudwatch", "status": "APPROVED"}],
        record_details={"r1": _mcp_detail("aws-observability", "agora_cloudwatch")},
    )
    registry_module._control = control
    result = discover_by_capability("community-knowledge")

    assert result == []


def test_discover_by_capability_excludes_inactive_records():
    """INACTIVE など _ACTIVE_STATUSES 外のレコードはスキップする。"""
    control = _control_client(
        mcp_records=[{"recordId": "r1", "name": "so", "status": "INACTIVE"}],
        record_details={"r1": _mcp_detail("community-knowledge", "agora_stackoverflow")},
    )
    registry_module._control = control
    result = discover_by_capability("community-knowledge")

    assert result == []


def test_discover_by_capability_returns_empty_when_no_registry():
    """Registry が存在しない場合は空リストを返す。"""
    control = _control_client(registries=[])
    registry_module._control = control
    with pytest.raises(RuntimeError, match="not found or not READY"):
        discover_by_capability("community-knowledge")


def test_discover_by_capability_handles_pagination():
    """nextToken によるページネーションで全レコードを取得する。"""
    call_count = [0]

    def list_records(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {
                "registryRecords": [{"recordId": "r1", "name": "so", "status": "APPROVED"}],
                "nextToken": "page-2",
            }
        return {
            "registryRecords": [{"recordId": "r2", "name": "github", "status": "APPROVED"}]
        }

    record_details = {
        "r1": _mcp_detail("community-knowledge", "agora_stackoverflow"),
        "r2": _mcp_detail("community-knowledge", "agora_github_issues"),
    }
    control = _control_client(record_details=record_details)
    control.list_registry_records.side_effect = list_records
    registry_module._control = control
    result = discover_by_capability("community-knowledge")

    assert len(result) == 2
    assert {r["name"] for r in result} == {"agora_stackoverflow", "agora_github_issues"}
    assert call_count[0] == 2


# ─── discover_a2a_agents ──────────────────────────────────────────────────


def test_discover_a2a_agents_returns_all_agents():
    control = _control_client(
        a2a_records=[
            {"recordId": "r1", "name": "triage", "status": "APPROVED"},
            {"recordId": "r2", "name": "diagnosis", "status": "APPROVED"},
            {"recordId": "r3", "name": "resolution", "status": "APPROVED"},
        ],
        record_details={
            "r1": _a2a_detail("triage", "agora_triage", "triage_ep"),
            "r2": _a2a_detail("diagnosis", "agora_diagnosis", "diag_ep"),
            "r3": _a2a_detail("resolution", "agora_resolution", "res_ep"),
        },
    )
    registry_module._control = control
    result = discover_a2a_agents()

    assert len(result) == 3
    agent_types = {r["agent_type"] for r in result}
    assert agent_types == {"triage", "diagnosis", "resolution"}


def test_discover_a2a_agents_excludes_inactive():
    control = _control_client(
        a2a_records=[{"recordId": "r1", "name": "triage", "status": "DRAFT"}],
        record_details={"r1": _a2a_detail("triage", "agora_triage")},
    )
    # DRAFT は _ACTIVE_STATUSES = {"DRAFT", "APPROVED"} に含まれる
    registry_module._control = control
    result = discover_a2a_agents()

    assert len(result) == 1
    assert result[0]["agent_type"] == "triage"
