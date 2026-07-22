from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

KNOWN_EVENT_TYPES = {
    "session",
    "agent_start",
    "agent_end",
    "agent_settled",
    "turn_start",
    "turn_end",
    "message_start",
    "message_update",
    "message_end",
    "tool_execution_start",
    "tool_execution_update",
    "tool_execution_end",
    "auto_retry_start",
    "auto_retry_end",
    "extension_error",
    "queue_update",
    "compaction_start",
    "compaction_end",
}


class PiProtocolError(ValueError):
    pass


def _assistant_failure(message: object) -> str | None:
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None
    stop_reason = message.get("stopReason", message.get("stop_reason"))
    if stop_reason not in {"error", "aborted"}:
        return None
    error_message = message.get("errorMessage", message.get("error_message"))
    if isinstance(error_message, str) and error_message.strip():
        return error_message.strip()
    return f"Pi request ended with stop reason {stop_reason}"


def event_failure_message(event: dict[str, Any]) -> str | None:
    """Return a terminal Pi failure carried by an otherwise valid JSON event."""

    event_type = event.get("type")
    if event_type in {"message_end", "turn_end"}:
        return _assistant_failure(event.get("message"))
    if event_type == "agent_end":
        messages = event.get("messages")
        if not isinstance(messages, list):
            return None
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "assistant":
                return _assistant_failure(message)
        return None
    if event_type == "extension_error":
        error = event.get("error")
        if isinstance(error, str) and error.strip():
            return f"Pi extension failed: {error.strip()}"
        return "Pi extension failed"
    return None


def parse_event(line: str) -> dict[str, Any]:
    try:
        event = json.loads(line)
    except json.JSONDecodeError as exc:
        raise PiProtocolError("Pi emitted malformed JSONL") from exc
    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
        raise PiProtocolError("Pi event is missing a string type")
    return event


@dataclass(slots=True)
class PiEventCollector:
    events: list[dict[str, Any]] = field(default_factory=list)
    errors: list[PiProtocolError] = field(default_factory=list)
    line_count: int = 0

    async def accept(self, source: str, line: str) -> None:
        if source != "stdout":
            return
        self.line_count += 1
        try:
            self.events.append(parse_event(line))
        except PiProtocolError as exc:
            self.errors.append(exc)

    @property
    def failure_message(self) -> str | None:
        # Pi can emit a failed agent_end and retry. Only the latest agent result is terminal.
        for event in reversed(self.events):
            if event.get("type") == "agent_end":
                return event_failure_message(event)

        # Retain compatibility with event streams that end after a turn or message event.
        for event in reversed(self.events):
            failure = event_failure_message(event)
            if failure is not None:
                return failure
        return None
