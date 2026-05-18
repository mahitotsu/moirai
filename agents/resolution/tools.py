from __future__ import annotations

import json

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic_settings import BaseSettings
from strands import tool


class _Settings(BaseSettings):
    gateway_url: str = ""


GATEWAY_URL = _Settings().gateway_url


async def _call_gateway(tool_name: str, arguments: dict) -> str:
    """Call a tool on the AgentCore Gateway via MCP streamable_http transport."""
    async with streamablehttp_client(GATEWAY_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
    texts = [c.text for c in result.content if hasattr(c, "text")]
    return " ".join(texts) if texts else str(result)


@tool
async def create_ticket(
    title: str,
    description: str,
    severity: str,
    category: str,
    resolution: str,
    affected_components: list[str] | None = None,
) -> str:
    """Create an incident ticket and attach the resolution plan via AgentCore Gateway.

    Internally performs two Gateway calls: POST /tickets (create) then
    PATCH /tickets/{id} (attach resolution). Returns the new ticket ID.

    Args:
        title: Short title for the incident (max 200 chars).
        description: Full description of the incident as reported.
        severity: One of: low, medium, high, critical.
        category: One of: database, network, memory, deploy, performance, security, other.
        resolution: The resolution plan generated for this incident.
        affected_components: Ignored (not yet supported by the Ticket Service schema).

    Returns:
        The ticket ID of the created ticket, or an error message.
    """
    if not GATEWAY_URL:
        return "GATEWAY_URL is not configured — cannot create ticket."
    try:
        raw = await _call_gateway(
            "create_ticket_tickets_post",
            {
                "title": title,
                "description": description,
                "severity": severity,
                "category": category,
            },
        )
        ticket = json.loads(raw)
        ticket_id = ticket.get("ticket_id")
        if not ticket_id:
            return f"Ticket creation returned unexpected response: {raw}"

        await _call_gateway(
            "update_ticket_tickets__ticket_id__patch",
            {"ticket_id": ticket_id, "resolution": resolution, "status": "open"},
        )
        return ticket_id
    except Exception as exc:
        return f"Ticket creation failed: {exc}"


@tool
async def update_ticket_resolution(
    ticket_id: str, resolution: str, status: str = "resolved"
) -> str:
    """Update an existing ticket with a resolution and optionally mark it resolved.

    Args:
        ticket_id: The ID of the ticket to update.
        resolution: The resolution text to add to the ticket.
        status: New ticket status — typically "resolved" or "in_progress".

    Returns:
        Confirmation message or error.
    """
    if not GATEWAY_URL:
        return "GATEWAY_URL is not configured — cannot update ticket."
    try:
        await _call_gateway(
            "update_ticket_tickets__ticket_id__patch",
            {"ticket_id": ticket_id, "resolution": resolution, "status": status},
        )
        return f"Ticket {ticket_id} updated to status '{status}'."
    except Exception as exc:
        return f"Ticket update failed: {exc}"
