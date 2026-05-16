from __future__ import annotations

import httpx
from pydantic_settings import BaseSettings
from strands import tool


class _Settings(BaseSettings):
    ticket_service_url: str = ""
    api_key_secret_name: str = "agora/services-api-key"


_s = _Settings()
TICKET_SERVICE_URL = _s.ticket_service_url
_API_KEY_SECRET_NAME = _s.api_key_secret_name


def _get_api_key() -> str:
    """Fetch API key from Secrets Manager (cached per process)."""
    global _API_KEY_CACHE
    if _API_KEY_CACHE:
        return _API_KEY_CACHE
    import boto3
    sm = boto3.client("secretsmanager", region_name="us-east-1")
    _API_KEY_CACHE = sm.get_secret_value(SecretId=_API_KEY_SECRET_NAME)["SecretString"]
    return _API_KEY_CACHE


_API_KEY_CACHE: str = ""


@tool
def create_ticket(
    title: str,
    description: str,
    severity: str,
    category: str,
    resolution: str,
    affected_components: list[str] | None = None,
) -> str:
    """Create an incident ticket in the Ticket Service.

    Args:
        title: Short title for the incident (max 200 chars).
        description: Full description of the incident as reported.
        severity: One of: low, medium, high, critical.
        category: One of: database, network, memory, deploy, performance, security, other.
        resolution: The resolution plan generated for this incident.
        affected_components: Optional list of affected system components.

    Returns:
        The ticket ID of the created ticket, or an error message.
    """
    if not TICKET_SERVICE_URL:
        return "TICKET_SERVICE_URL is not configured — cannot create ticket."

    payload: dict = {
        "title": title,
        "description": description,
        "severity": severity,
        "category": category,
        "resolution": resolution,
        "status": "open",
    }
    if affected_components:
        payload["affected_components"] = affected_components

    try:
        api_key = _get_api_key()
        resp = httpx.post(
            f"{TICKET_SERVICE_URL.rstrip('/')}/tickets",
            json=payload,
            headers={"x-api-key": api_key},
            timeout=15.0,
        )
        resp.raise_for_status()
        ticket = resp.json()
        return ticket.get("ticket_id", str(ticket))
    except Exception as exc:
        return f"Ticket creation failed: {exc}"


@tool
def update_ticket_resolution(ticket_id: str, resolution: str, status: str = "resolved") -> str:
    """Update an existing ticket with a resolution and optionally mark it resolved.

    Args:
        ticket_id: The ID of the ticket to update.
        resolution: The resolution text to add to the ticket.
        status: New ticket status — typically "resolved" or "in_progress".

    Returns:
        Confirmation message or error.
    """
    if not TICKET_SERVICE_URL:
        return "TICKET_SERVICE_URL is not configured — cannot update ticket."

    payload = {"resolution": resolution, "status": status}
    try:
        api_key = _get_api_key()
        resp = httpx.patch(
            f"{TICKET_SERVICE_URL.rstrip('/')}/tickets/{ticket_id}",
            json=payload,
            headers={"x-api-key": api_key},
            timeout=15.0,
        )
        resp.raise_for_status()
        return f"Ticket {ticket_id} updated to status '{status}'."
    except Exception as exc:
        return f"Ticket update failed: {exc}"
