from __future__ import annotations

import json
import uuid
from typing import Any


class AgentRepository:
    """Wraps boto3 bedrock-agentcore to invoke the Gateway Agent runtime."""

    def __init__(self, client: Any, runtime_arn: str) -> None:
        self._client = client
        self._runtime_arn = runtime_arn

    def invoke(self, message: str, user_id: str, session_id: str) -> str:
        """Send a message to the Gateway Agent and return the text response."""
        if not self._runtime_arn:
            return (
                "[Demo mode] エージェントが未設定です。\n"
                "AGENT_RUNTIME_ARN 環境変数に Gateway Agent の ARN を設定し、"
                "CDK を再デプロイしてください。"
            )

        payload = json.dumps({"prompt": message, "user_id": user_id}).encode()
        resp = self._client.invoke_agent_runtime(
            agentRuntimeArn=self._runtime_arn,
            qualifier="DEFAULT",
            payload=payload,
            runtimeSessionId=session_id or str(uuid.uuid4()),
        )
        body: bytes = resp["response"].read()
        try:
            data: dict = json.loads(body)
            return str(data.get("response", data))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return body.decode("utf-8", errors="replace")
