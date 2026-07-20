from pathlib import Path

import pytest

from backend.engine.pi.command import build_pi_command, resolve_pi_settings, resolve_pi_skill
from backend.engine.pi.json_events import PiEventCollector, PiProtocolError, parse_event
from backend.engine.pi.renderer import render_event
from backend.schemas.pi import PiSettings


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
        "--model",
        "anthropic/model",
        "--no-skills",
        "--skill",
        "/worktree/.agents/skills/release/SKILL.md",
        "/skill:release ship",
    ]


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


def test_malformed_json_is_a_protocol_error() -> None:
    with pytest.raises(PiProtocolError):
        parse_event("not-json")
