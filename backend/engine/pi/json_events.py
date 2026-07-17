from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

KNOWN_EVENT_TYPES = {
    "agent_start",
    "agent_end",
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
}


class PiProtocolError(ValueError):
    pass


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

    async def accept(self, source: str, line: str) -> None:
        if source != "stdout":
            return
        try:
            self.events.append(parse_event(line))
        except PiProtocolError as exc:
            self.errors.append(exc)
