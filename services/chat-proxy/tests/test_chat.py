from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_chat_demo_mode(client: TestClient) -> None:
    # AGENT_RUNTIME_ARN unset → repository returns demo response without AWS call
    resp = client.post(
        "/api/chat",
        json={"message": "hello", "userId": "test-user", "sessionId": "test-session"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "response" in data
    assert isinstance(data["response"], str)
    assert len(data["response"]) > 0
