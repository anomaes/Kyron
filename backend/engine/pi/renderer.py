from __future__ import annotations

from typing import Any

from backend.engine.pi.json_events import event_failure_message


def _tool_result_text(event: dict[str, Any]) -> str | None:
    result = event.get("result")
    if not isinstance(result, dict):
        return None
    content = result.get("content")
    if not isinstance(content, list):
        return None
    messages: list[str] = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            messages.append(text.strip())
    return " ".join(messages) or None


def render_event(event: dict[str, Any]) -> str:
    event_type = event.get("type")
    if event_type == "agent_start":
        return "Pi session started"
    if event_type == "agent_end":
        if failure := event_failure_message(event):
            return f"Pi session failed: {failure}"
        return "Pi session completed"
    if event_type == "message_end":
        if failure := event_failure_message(event):
            return f"Pi request failed: {failure}"
    if event_type == "message_update":
        return "Assistant response streaming"
    if event_type == "tool_execution_start":
        tool = event.get("toolName") or event.get("tool_name") or "tool"
        return f"Running tool: {tool}"
    if event_type == "tool_execution_end":
        tool = event.get("toolName") or event.get("tool_name") or "tool"
        if event.get("isError", event.get("is_error", False)):
            detail = _tool_result_text(event)
            suffix = f": {detail}" if detail else ""
            return f"Tool failed: {tool}{suffix}"
        return f"Completed tool: {tool}"
    if event_type == "auto_retry_start":
        attempt = event.get("attempt", "?")
        maximum = event.get("maxAttempts", event.get("max_attempts", "?"))
        return f"Provider retry {attempt}/{maximum}"
    if event_type == "extension_error":
        return event_failure_message(event) or "Pi extension reported an error"
    return f"Pi event: {event_type or 'unknown'}"
