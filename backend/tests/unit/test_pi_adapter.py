import pytest

from backend.engine.pi.command import build_pi_command
from backend.engine.pi.json_events import PiEventCollector, PiProtocolError, parse_event
from backend.engine.pi.renderer import render_event


def test_pi_command_uses_json_noninteractive_mode() -> None:
    assert build_pi_command("ship", "anthropic", "anthropic/model") == [
        "pi",
        "--mode",
        "json",
        "--no-session",
        "--no-approve",
        "--provider",
        "anthropic",
        "--model",
        "anthropic/model",
        "ship",
    ]


async def test_known_and_unknown_events_are_preserved() -> None:
    collector = PiEventCollector()
    await collector.accept("stdout", '{"type":"agent_start"}\n')
    await collector.accept("stdout", '{"type":"future_event","value":1}\n')
    assert [event["type"] for event in collector.events] == [
        "agent_start",
        "future_event",
    ]
    assert render_event(collector.events[0]) == "Pi session started"
    assert render_event(collector.events[1]) == "Pi event: future_event"


def test_malformed_json_is_a_protocol_error() -> None:
    with pytest.raises(PiProtocolError):
        parse_event("not-json")
