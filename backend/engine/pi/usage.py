from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

TOKEN_FIELDS = ("input", "output", "cacheRead", "cacheWrite", "totalTokens")
COST_FIELDS = ("input", "output", "cacheRead", "cacheWrite", "total")


def empty_pi_usage() -> dict[str, Any]:
    return {
        "input": 0,
        "output": 0,
        "cacheRead": 0,
        "cacheWrite": 0,
        "totalTokens": 0,
        "cost": {field: 0.0 for field in COST_FIELDS},
        "requestCount": 0,
    }


def normalize_pi_usage(
    value: object,
    *,
    default_request_count: int = 0,
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None

    normalized = empty_pi_usage()
    found_usage = False
    for field in TOKEN_FIELDS:
        number = _non_negative_number(value.get(field))
        if number is None:
            continue
        normalized[field] = int(number)
        found_usage = True

    cost = value.get("cost")
    if isinstance(cost, Mapping):
        for field in COST_FIELDS:
            number = _non_negative_number(cost.get(field))
            if number is None:
                continue
            normalized["cost"][field] = float(number)
            found_usage = True

    request_count = _non_negative_number(value.get("requestCount"))
    if request_count is not None:
        normalized["requestCount"] = int(request_count)
        found_usage = True
    elif found_usage:
        normalized["requestCount"] = default_request_count

    return normalized if found_usage else None


def add_pi_usage(target: dict[str, Any], usage: object) -> dict[str, Any]:
    normalized = normalize_pi_usage(usage)
    if normalized is None:
        return target
    for field in TOKEN_FIELDS:
        target[field] += normalized[field]
    for field in COST_FIELDS:
        target["cost"][field] += normalized["cost"][field]
    target["requestCount"] += normalized["requestCount"]
    return target


def aggregate_pi_usage_events(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    aggregate = empty_pi_usage()
    for event in events:
        if event.get("type") != "message_end":
            continue
        message = event.get("message")
        if not isinstance(message, Mapping) or message.get("role") != "assistant":
            continue
        usage = normalize_pi_usage(message.get("usage"), default_request_count=1)
        if usage is not None:
            add_pi_usage(aggregate, usage)
    return aggregate


def aggregate_pi_usage_content(content: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for line in content.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and isinstance(event.get("type"), str):
            events.append(event)
    return aggregate_pi_usage_events(events)


def _non_negative_number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value
