from __future__ import annotations

from typing import Any


def render_event(event: dict[str, Any]) -> str:
    event_type = event.get("type")
    if event_type == "agent_start":
        return "Pi session started"
    if event_type == "agent_end":
        return "Pi session completed"
    if event_type == "message_update":
        return "Assistant response streaming"
    if event_type == "tool_execution_start":
        tool = event.get("toolName") or event.get("tool_name") or "tool"
        return f"Running tool: {tool}"
    if event_type == "auto_retry_start":
        attempt = event.get("attempt", "?")
        maximum = event.get("maxAttempts", event.get("max_attempts", "?"))
        return f"Provider retry {attempt}/{maximum}"
    if event_type == "extension_error":
        return "Pi extension reported an error"
    return f"Pi event: {event_type or 'unknown'}"
