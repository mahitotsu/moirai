from __future__ import annotations

import json
import threading
from uuid import uuid4

import boto3
from botocore.config import Config
from common.registry import discover_a2a_agents
from strands import tool

_AGENT_QUALIFIER = "DEFAULT"
_agentcore_client = boto3.client(
    "bedrock-agentcore",
    config=Config(read_timeout=300, connect_timeout=10, retries={"max_attempts": 0}),
)

# Cache agent ARNs per process to avoid repeated Registry lookups
_agent_arn_cache: dict[str, str] = {}
_cache_lock = threading.Lock()


def _find_agent_arn(agent_type: str) -> str | None:
    """Find the runtime ARN for an A2A agent by type tag, with process-level cache."""
    with _cache_lock:
        if agent_type in _agent_arn_cache:
            return _agent_arn_cache[agent_type]
    for agent in discover_a2a_agents():
        if agent.get("agent_type") == agent_type:
            with _cache_lock:
                _agent_arn_cache[agent_type] = agent["runtime_arn"]
            return agent["runtime_arn"]
    return None


def _invoke_a2a_agent(runtime_arn: str, message: str) -> str:
    """Invoke an A2A agent via AgentCore Runtime and return the response text."""
    client = _agentcore_client

    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": message}],
                "messageId": str(uuid4()),
            },
        },
    }).encode()

    resp = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        qualifier=_AGENT_QUALIFIER,
        payload=payload,
        runtimeSessionId=str(uuid4()),
    )

    body = resp["response"].read()
    return _parse_a2a_response(body)


def _parse_a2a_response(body: bytes) -> str:
    """Extract the agent's final text from an A2A response (JSON-RPC or SSE)."""
    content = body.decode("utf-8", errors="replace").strip()

    def _extract_text_from_task(task: dict) -> str:
        # Prefer artifacts over history
        for artifact in task.get("artifacts", []):
            for part in artifact.get("parts", []):
                if part.get("kind") == "text" and part.get("text"):
                    return part["text"]
        for msg in reversed(task.get("history", [])):
            if msg.get("role") == "agent":
                for part in msg.get("parts", []):
                    if part.get("kind") == "text" and part.get("text"):
                        return part["text"]
        return ""

    # Handle SSE format (newline-delimited "data: ..." lines)
    last_text = ""
    for line in content.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            data = json.loads(line[6:].strip())
        except json.JSONDecodeError:
            continue

        # JSON-RPC envelope wrapping a task
        if "result" in data:
            text = _extract_text_from_task(data["result"])
        else:
            text = _extract_text_from_task(data)

        if text:
            last_text = text

    if last_text:
        return last_text

    # Fallback: try to parse the whole body as a single JSON object
    try:
        data = json.loads(content)
        if "result" in data:
            text = _extract_text_from_task(data["result"])
            if text:
                return text
        return data.get("response", data.get("result", "")) or str(data)
    except json.JSONDecodeError:
        pass

    return content or "No response from agent."


@tool
def run_analysis(report_request: str) -> str:
    """Generate an operational analysis report for the IT Service Desk.

    Delegates to the Analysis Agent, which gathers incident statistics,
    Lambda error metrics, and Bedrock usage costs, then saves a structured
    report to the reports store.

    Use this when the user asks for a status report, incident trend analysis,
    cost breakdown, or operational summary.

    Args:
        report_request: Description of the report to generate (e.g.
            "Generate a weekly operational report" or
            "Show me Bedrock costs for the past 7 days").

    Returns:
        A markdown-formatted summary of the generated report, including the
        report ID for future reference.
    """
    arn = _find_agent_arn("analysis")
    if not arn:
        return "Analysis Agent is not available in the Registry."
    try:
        return _invoke_a2a_agent(arn, report_request)
    except Exception as exc:
        return f"Analysis failed: {exc}"


@tool
def run_triage(incident_description: str) -> str:
    """Classify an IT incident by severity and category.

    Delegates to the Triage Agent, which returns a JSON object with:
    severity (low/medium/high/critical), category (database/network/memory/
    deploy/performance/security/other), summary, affected_components, and
    suggested_search_terms.

    Args:
        incident_description: The user's description of the incident.

    Returns:
        JSON string with triage classification, or a fallback classification
        if the Triage Agent is unavailable.
    """
    arn = _find_agent_arn("triage")
    if not arn:
        return json.dumps({
            "severity": "medium",
            "category": "other",
            "summary": incident_description,
            "affected_components": [],
            "suggested_search_terms": [incident_description],
        })
    try:
        return _invoke_a2a_agent(arn, incident_description)
    except Exception as exc:
        return json.dumps({
            "severity": "medium",
            "category": "other",
            "summary": incident_description,
            "affected_components": [],
            "suggested_search_terms": [incident_description],
            "triage_error": str(exc),
        })


@tool
def run_diagnosis(incident_description: str, search_terms: list[str]) -> str:
    """Search community knowledge and past tickets for a technical incident.

    Delegates to the Diagnosis Agent, which searches Stack Overflow, GitHub
    Issues, Wikipedia, AWS Docs, and past incident tickets in parallel using
    the provided search terms.

    Args:
        incident_description: Full description of the incident.
        search_terms: Technical search terms generated by triage to guide the search.

    Returns:
        Diagnosis report combining relevant findings from all knowledge sources.
    """
    arn = _find_agent_arn("diagnosis")
    if not arn:
        return "Diagnosis Agent is not available in the Registry."

    terms_str = ", ".join(search_terms) if search_terms else incident_description
    message = (
        f"Incident: {incident_description}\n\n"
        f"Please search for: {terms_str}"
    )
    try:
        return _invoke_a2a_agent(arn, message)
    except Exception as exc:
        return f"Diagnosis failed: {exc}"


@tool
def run_resolution(
    incident_description: str,
    triage_result: str,
    diagnosis_result: str,
    ticket_id: str = "",
) -> str:
    """Generate a resolution plan and record it in the Ticket Service.

    Delegates to the Resolution Agent, which uses the triage classification
    and diagnosis findings to generate a tailored resolution plan, then
    records it via the Ticket Service. If ticket_id is provided (automated
    flow), updates the existing ticket; otherwise creates a new one.

    Args:
        incident_description: The original incident description from the user.
        triage_result: JSON classification from the Triage Agent.
        diagnosis_result: Knowledge search findings from the Diagnosis Agent.
        ticket_id: Existing ticket ID to update (automated flow). Empty string
            means no ticket exists yet and Resolution should create one.

    Returns:
        Resolution plan text including the ticket ID, or error message.
    """
    arn = _find_agent_arn("resolution")
    if not arn:
        return "Resolution Agent is not available in the Registry."

    if ticket_id:
        ticket_instruction = (
            f"The incident has already been recorded as ticket {ticket_id}. "
            f"Use the ticket update tool to attach your resolution plan to this existing ticket. "
            f"Do NOT create a new ticket."
        )
    else:
        ticket_instruction = "Use `create_ticket` to record this incident and its resolution plan."

    message = (
        f"Incident: {incident_description}\n\n"
        f"Triage:\n{triage_result}\n\n"
        f"Diagnosis:\n{diagnosis_result}\n\n"
        f"{ticket_instruction}"
    )
    try:
        return _invoke_a2a_agent(arn, message)
    except Exception as exc:
        return f"Resolution failed: {exc}"
