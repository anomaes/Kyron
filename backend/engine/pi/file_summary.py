from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.engine.pi.json_events import PiProtocolError, parse_event
from backend.engine.pi.model_identity import aggregate_pi_models_events, merge_pi_models
from backend.engine.pi.usage import add_pi_usage, aggregate_pi_usage_events, empty_pi_usage


def summarize_pi_file(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read the durable JSONL once, retaining only usage and model totals."""
    usage = empty_pi_usage()
    models: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as source:
        for line in source:
            try:
                event = parse_event(line)
            except PiProtocolError:
                continue
            add_pi_usage(usage, aggregate_pi_usage_events((event,)))
            merge_pi_models(models, aggregate_pi_models_events((event,)))
    return usage, models
