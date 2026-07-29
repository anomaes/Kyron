from __future__ import annotations

from typing import Any

import pytest

from backend.engine.pi.usage import (
    aggregate_pi_usage_content,
    aggregate_pi_usage_events,
)


def usage(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_write: int = 0,
    cost: float = 0,
) -> dict[str, object]:
    return {
        "input": input_tokens,
        "output": output_tokens,
        "cacheRead": cache_read,
        "cacheWrite": cache_write,
        "totalTokens": input_tokens + output_tokens + cache_read + cache_write,
        "cost": {
            "input": 0,
            "output": cost,
            "cacheRead": 0,
            "cacheWrite": 0,
            "total": cost,
        },
    }


def test_aggregate_counts_every_assistant_model_call_including_tool_only_turns() -> None:
    events: list[dict[str, Any]] = [
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "read"}],
                "usage": usage(input_tokens=100, output_tokens=20, cache_read=50, cost=0.1),
            },
        },
        {"type": "tool_execution_end", "usage": usage(input_tokens=999, output_tokens=999)},
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Done"}],
                "usage": usage(input_tokens=200, output_tokens=30, cache_write=10, cost=0.2),
            },
        },
        {
            "type": "agent_end",
            "messages": [
                {
                    "role": "assistant",
                    "usage": usage(input_tokens=200, output_tokens=30),
                }
            ],
        },
    ]

    aggregate = aggregate_pi_usage_events(events)

    assert aggregate["input"] == 300
    assert aggregate["output"] == 50
    assert aggregate["cacheRead"] == 50
    assert aggregate["cacheWrite"] == 10
    assert aggregate["totalTokens"] == 410
    assert aggregate["requestCount"] == 2
    assert aggregate["cost"]["total"] == pytest.approx(0.3)


def test_content_aggregation_ignores_malformed_and_non_assistant_events() -> None:
    content = "\n".join(
        [
            "not-json",
            '{"type":"message_end","message":{"role":"user","usage":{"totalTokens":999}}}',
            '{"type":"message_end","message":{"role":"assistant","usage":'
            '{"input":12,"output":3,"cacheRead":0,"cacheWrite":0,'
            '"totalTokens":15,"cost":{"total":0.004}}}}',
        ]
    )

    aggregate = aggregate_pi_usage_content(content)

    assert aggregate["totalTokens"] == 15
    assert aggregate["requestCount"] == 1
    assert aggregate["cost"]["total"] == 0.004
