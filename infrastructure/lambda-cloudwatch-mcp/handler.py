from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp.client.stdio import StdioServerParameters
from mcp_lambda import BedrockAgentCoreGatewayTargetHandler, StdioServerAdapterRequestHandler

_SERVER_SCRIPT = str(Path(__file__).parent / "run_server.py")

# Lambda の container credentials (AWS_CONTAINER_CREDENTIALS_RELATIVE_URI 等) を
# サブプロセスに確実に継承させるため env を明示的に渡す。
server_params = StdioServerParameters(
    command=sys.executable,
    args=[_SERVER_SCRIPT],
    env=os.environ.copy(),
)

request_handler = StdioServerAdapterRequestHandler(server_params)
event_handler = BedrockAgentCoreGatewayTargetHandler(request_handler)


def handler(event, context):
    return event_handler.handle(event, context)
