from __future__ import annotations

import uuid
from typing import Any

from backend.engine.pi.json_events import PiEventCollector
from backend.engine.pi.model_identity import normalize_pi_models
from backend.engine.pi.usage import normalize_pi_usage

_active: dict[uuid.UUID, PiEventCollector] = {}


def register(attempt_id: uuid.UUID, collector: PiEventCollector) -> None:
    _active[attempt_id] = collector


def unregister(attempt_id: uuid.UUID) -> None:
    _active.pop(attempt_id, None)


def snapshot(attempt_id: uuid.UUID) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    collector = _active.get(attempt_id)
    if collector is None:
        return None
    return normalize_pi_usage(collector.usage) or {}, normalize_pi_models(collector.models)
