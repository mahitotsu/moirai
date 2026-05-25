from __future__ import annotations

import sys
from pathlib import Path

from mcp.client.stdio import StdioServerParameters
from mcp_lambda import BedrockAgentCoreGatewayTargetHandler, StdioServerAdapterRequestHandler

_SERVER_SCRIPT = str(Path(__file__).parent / "run_server.py")

server_params = StdioServerParameters(
    command=sys.executable,
    args=[_SERVER_SCRIPT],
)

request_handler = StdioServerAdapterRequestHandler(server_params)
event_handler = BedrockAgentCoreGatewayTargetHandler(request_handler)


def handler(event, context):
    return event_handler.handle(event, context)
