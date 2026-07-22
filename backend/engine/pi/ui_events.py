from __future__ import annotations

from typing import Any

from backend.engine.pi.json_events import PiProtocolError, event_failure_message, parse_event
from backend.engine.pi.renderer import render_event


def _message_content(message: object, content_type: str) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != content_type:
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def normalize_pi_event(event: dict[str, Any], event_index: int) -> dict[str, Any] | None:
    """Translate Pi's versioned JSON protocol into Kyron's stable UI contract."""

    event_type = event.get("type")
    base: dict[str, Any] = {"event_index": event_index, "pi_event_type": event_type}

    if event_type == "message_update":
        update = event.get("assistantMessageEvent", event.get("assistant_message_event"))
        if not isinstance(update, dict):
            return None
        update_type = update.get("type")
        if update_type not in {"text_delta", "thinking_delta"}:
            return None
        delta = update.get("delta")
        if not isinstance(delta, str) or not delta:
            return None
        return {
            **base,
            "kind": "assistant_delta",
            "stream": "thinking" if update_type == "thinking_delta" else "text",
            "delta": delta,
        }

    if event_type == "message_end":
        message = event.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return None
        return {
            **base,
            "kind": "assistant_end",
            "text": _message_content(message, "text"),
            "thinking": _message_content(message, "thinking"),
            "stop_reason": message.get("stopReason", message.get("stop_reason")),
            "error": event_failure_message(event),
            "usage": message.get("usage"),
        }

    if event_type == "tool_execution_start":
        return {
            **base,
            "kind": "tool_start",
            "tool_call_id": event.get("toolCallId", event.get("tool_call_id")),
            "tool_name": event.get("toolName", event.get("tool_name")) or "tool",
            "args": event.get("args"),
        }

    if event_type == "tool_execution_update":
        return {
            **base,
            "kind": "tool_update",
            "tool_call_id": event.get("toolCallId", event.get("tool_call_id")),
            "tool_name": event.get("toolName", event.get("tool_name")) or "tool",
            "partial_result": event.get("partialResult", event.get("partial_result")),
        }

    if event_type == "tool_execution_end":
        return {
            **base,
            "kind": "tool_end",
            "tool_call_id": event.get("toolCallId", event.get("tool_call_id")),
            "tool_name": event.get("toolName", event.get("tool_name")) or "tool",
            "result": event.get("result"),
            "is_error": bool(event.get("isError", event.get("is_error", False))),
        }

    if event_type in {"turn_start", "turn_end", "message_start", "queue_update"}:
        return None

    if event_type == "session":
        return {
            **base,
            "kind": "lifecycle",
            "message": f"Pi session {event.get('id', '')}".strip(),
        }

    if event_type == "compaction_start":
        return {**base, "kind": "lifecycle", "message": "Compacting conversation context"}

    if event_type == "compaction_end":
        message = "Conversation context compacted"
        if event.get("aborted"):
            message = "Conversation compaction aborted"
        if event.get("errorMessage", event.get("error_message")):
            message += f": {event.get('errorMessage', event.get('error_message'))}"
        return {**base, "kind": "lifecycle", "message": message}

    if event_type == "auto_retry_end":
        success = bool(event.get("success"))
        final_error = event.get("finalError", event.get("final_error", "unknown error"))
        return {
            **base,
            "kind": "lifecycle" if success else "error",
            "message": "Provider retry succeeded"
            if success
            else f"Provider retry failed: {final_error}",
        }

    if event_type in {
        "agent_start",
        "agent_end",
        "agent_settled",
        "auto_retry_start",
        "extension_error",
    }:
        failure = event_failure_message(event)
        return {
            **base,
            "kind": "error" if failure else "lifecycle",
            "message": render_event(event),
        }

    return {
        **base,
        "kind": "lifecycle",
        "message": f"Pi event: {event_type or 'unknown'}",
    }


def parse_pi_ui_events(content: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for event_index, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = parse_event(line)
        except PiProtocolError:
            events.append(
                {
                    "event_index": event_index,
                    "pi_event_type": "protocol_error",
                    "kind": "error",
                    "message": "Pi emitted malformed JSONL",
                }
            )
            continue
        normalized = normalize_pi_event(event, event_index)
        if normalized is not None:
            events.append(normalized)
    return events
