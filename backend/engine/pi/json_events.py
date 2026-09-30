from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from backend.engine.pi.model_identity import aggregate_pi_models_events, merge_pi_models
from backend.engine.pi.usage import add_pi_usage, aggregate_pi_usage_events, empty_pi_usage

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
        return error_message.strip()[:4096]
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
            return f"Pi extension failed: {error.strip()[:4096]}"
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
    usage: dict[str, Any] = field(default_factory=empty_pi_usage)
    models: list[dict[str, Any]] = field(default_factory=list)
    error_count: int = 0
    line_count: int = 0
    _agent_end_seen: bool = False
    _agent_failure: str | None = None
    _other_failure: str | None = None

    async def accept(self, source: str, line: str) -> dict[str, Any] | None:
        if source != "stdout":
            return None
        self.line_count += 1
        try:
            event = parse_event(line)
        except PiProtocolError:
            self.error_count += 1
            return None
        add_pi_usage(self.usage, aggregate_pi_usage_events((event,)))
        merge_pi_models(self.models, aggregate_pi_models_events((event,)))
        if event.get("type") == "agent_end":
            self._agent_end_seen = True
            self._agent_failure = event_failure_message(event)
        elif failure := event_failure_message(event):
            self._other_failure = failure
        return event

    @property
    def failure_message(self) -> str | None:
        return self._agent_failure if self._agent_end_seen else self._other_failure
