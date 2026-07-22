from pathlib import Path

import pytest

from backend.engine.pi.command import (
    WORKTREE_GUARD_PATH,
    build_pi_command,
    resolve_pi_settings,
    resolve_pi_skill,
)
from backend.engine.pi.json_events import PiEventCollector, PiProtocolError, parse_event
from backend.engine.pi.renderer import render_event
from backend.engine.pi.ui_events import normalize_pi_event, parse_pi_ui_events
from backend.schemas.pi import PiSettings


def test_pi_command_uses_json_noninteractive_mode() -> None:
    assert build_pi_command("ship", "anthropic", "anthropic/model") == [
        "pi",
        "--mode",
        "json",
        "--no-session",
        "--no-approve",
        "--no-extensions",
        "--extension",
        str(WORKTREE_GUARD_PATH),
        "--provider",
        "anthropic",
        "--model",
        "anthropic/model",
        "ship",
    ]


def test_pi_command_explicitly_loads_and_invokes_skill() -> None:
    assert build_pi_command(
        "ship",
        model="anthropic/model",
        skill_path=Path("/worktree/.agents/skills/release/SKILL.md"),
        skill_name="release",
    ) == [
        "pi",
        "--mode",
        "json",
        "--no-session",
        "--no-approve",
        "--no-extensions",
        "--extension",
        str(WORKTREE_GUARD_PATH),
        "--model",
        "anthropic/model",
        "--no-skills",
        "--skill",
        "/worktree/.agents/skills/release/SKILL.md",
        "/skill:release ship",
    ]


def test_pi_worktree_guard_is_packaged_with_the_adapter() -> None:
    assert WORKTREE_GUARD_PATH.is_file()


def test_pi_settings_resolve_field_by_field() -> None:
    resolved = resolve_pi_settings(
        PiSettings(provider="anthropic", model="project-model", skill="project/SKILL.md"),
        PiSettings(model="workflow-model"),
        PiSettings(skill="node/SKILL.md"),
    )
    assert resolved == PiSettings(
        provider="anthropic", model="workflow-model", skill="node/SKILL.md"
    )


def test_repository_skill_is_resolved_and_named(tmp_path: Path) -> None:
    skill = tmp_path / ".agents" / "skills" / "release"
    skill.mkdir(parents=True)
    manifest = skill / "SKILL.md"
    manifest.write_text("---\nname: release\ndescription: Release changes\n---\n# Release\n")

    assert resolve_pi_skill(tmp_path, ".agents/skills/release") == (manifest, "release")


def test_repository_skill_must_exist_inside_worktree(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        resolve_pi_skill(tmp_path, ".agents/skills/missing")

    outside = tmp_path.parent / "outside-skill.md"
    outside.write_text("---\nname: outside\ndescription: Outside\n---\n")
    link = tmp_path / "linked-skill.md"
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="inside the worktree"):
        resolve_pi_skill(tmp_path, "linked-skill.md")


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


async def test_terminal_assistant_error_is_a_pi_failure() -> None:
    collector = PiEventCollector()
    await collector.accept(
        "stdout",
        '{"type":"agent_end","messages":['
        '{"role":"assistant","content":[],"stopReason":"error",'
        '"errorMessage":"401 invalid API key"}],"willRetry":false}\n',
    )

    assert collector.failure_message == "401 invalid API key"
    assert render_event(collector.events[-1]) == "Pi session failed: 401 invalid API key"


async def test_latest_successful_agent_end_supersedes_a_retried_error() -> None:
    collector = PiEventCollector()
    await collector.accept(
        "stdout",
        '{"type":"agent_end","messages":['
        '{"role":"assistant","content":[],"stopReason":"error",'
        '"errorMessage":"provider overloaded"}],"willRetry":true}\n',
    )
    await collector.accept(
        "stdout",
        '{"type":"agent_end","messages":['
        '{"role":"assistant","content":[{"type":"text","text":"done"}],'
        '"stopReason":"stop"}],"willRetry":false}\n',
    )

    assert collector.failure_message is None


async def test_successful_agent_end_supersedes_nonterminal_extension_error() -> None:
    collector = PiEventCollector()
    await collector.accept(
        "stdout",
        '{"type":"extension_error","event":"tool_call",'
        '"error":"temporary extension error"}\n',
    )
    await collector.accept(
        "stdout",
        '{"type":"agent_end","messages":['
        '{"role":"assistant","content":[{"type":"text","text":"done"}],'
        '"stopReason":"stop"}],"willRetry":false}\n',
    )

    assert collector.failure_message is None


def test_failed_tool_result_includes_guard_reason() -> None:
    event = {
        "type": "tool_execution_end",
        "toolName": "write",
        "isError": True,
        "result": {
            "content": [
                {"type": "text", "text": "Pi may only modify files in the worktree"}
            ]
        },
    }

    assert render_event(event) == (
        "Tool failed: write: Pi may only modify files in the worktree"
    )


def test_malformed_json_is_a_protocol_error() -> None:
    with pytest.raises(PiProtocolError):
        parse_event("not-json")


def test_pi_ui_events_preserve_streaming_text_and_tool_details() -> None:
    content = "\n".join(
        [
            '{"type":"message_update","assistantMessageEvent":'
            '{"type":"text_delta","delta":"Checking files"},"message":{}}',
            '{"type":"message_end","message":{"role":"assistant","content":'
            '[{"type":"text","text":"Checking files"}],"stopReason":"toolUse"}}',
            '{"type":"tool_execution_start","toolCallId":"call-1",'
            '"toolName":"read","args":{"path":"backend/main.py"}}',
            '{"type":"tool_execution_end","toolCallId":"call-1",'
            '"toolName":"read","result":{"content":[{"type":"text",'
            '"text":"from fastapi import FastAPI"}]},"isError":false}',
        ]
    )

    events = parse_pi_ui_events(content)

    assert events[0] == {
        "event_index": 1,
        "pi_event_type": "message_update",
        "kind": "assistant_delta",
        "stream": "text",
        "delta": "Checking files",
    }
    assert events[1]["kind"] == "assistant_end"
    assert events[1]["text"] == "Checking files"
    assert events[2]["args"] == {"path": "backend/main.py"}
    assert events[3]["result"]["content"][0]["text"] == "from fastapi import FastAPI"


def test_pi_ui_events_drop_repeated_partial_messages_but_keep_thinking_delta() -> None:
    event = normalize_pi_event(
        {
            "type": "message_update",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "all"}]},
            "assistantMessageEvent": {"type": "thinking_delta", "delta": "Inspecting"},
        },
        4,
    )

    assert event == {
        "event_index": 4,
        "pi_event_type": "message_update",
        "kind": "assistant_delta",
        "stream": "thinking",
        "delta": "Inspecting",
    }


def test_malformed_pi_ui_line_becomes_visible_protocol_error() -> None:
    assert parse_pi_ui_events('{"type":"agent_start"}\nnot-json')[-1] == {
        "event_index": 2,
        "pi_event_type": "protocol_error",
        "kind": "error",
        "message": "Pi emitted malformed JSONL",
    }
