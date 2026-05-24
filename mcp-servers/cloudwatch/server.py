from __future__ import annotations

from awslabs.cloudwatch_mcp_server.server import mcp

mcp.settings.host = "0.0.0.0"
mcp.settings.port = 8000

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
