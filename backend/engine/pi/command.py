from __future__ import annotations

import re
from pathlib import Path

from backend.schemas.pi import PiSettings

SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORKTREE_GUARD_PATH = Path(__file__).with_name("worktree_guard.mjs")


def resolve_pi_settings(*scopes: PiSettings) -> PiSettings:
    """Merge least-specific to most-specific settings, one field at a time."""

    values: dict[str, str | None] = {"provider": None, "model": None, "skill": None}
    for scope in scopes:
        for field in values:
            value = getattr(scope, field)
            if value is not None:
                values[field] = value
    return PiSettings.model_validate(values)


def resolve_pi_skill(worktree: Path, configured_path: str) -> tuple[Path, str]:
    """Resolve a repository skill and extract the Pi command name from its frontmatter."""

    root = worktree.resolve()
    requested = (root / configured_path).resolve()
    if not requested.is_relative_to(root):
        raise ValueError("Pi skill path must remain inside the worktree")
    manifest = requested / "SKILL.md" if requested.is_dir() else requested
    manifest = manifest.resolve()
    if not manifest.is_relative_to(root) or not manifest.is_file():
        raise ValueError(f"Pi skill does not exist inside the worktree: {configured_path}")
    lines = manifest.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"Pi skill has no YAML frontmatter: {configured_path}")
    name: str | None = None
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if stripped.startswith("name:"):
            name = stripped.removeprefix("name:").strip().strip("'\"")
    if name is None or SKILL_NAME_PATTERN.fullmatch(name) is None or len(name) > 64:
        raise ValueError(f"Pi skill has an invalid or missing name: {configured_path}")
    return manifest, name


def build_pi_command(
    prompt: str,
    provider: str | None = None,
    model: str | None = None,
    *,
    skill_path: Path | None = None,
    skill_name: str | None = None,
) -> list[str]:
    command = [
        "pi",
        "--mode",
        "json",
        "--no-session",
        "--no-approve",
        "--no-extensions",
        "--extension",
        str(WORKTREE_GUARD_PATH),
    ]
    if provider:
        command.extend(["--provider", provider])
    if model:
        command.extend(["--model", model])
    if skill_path is not None:
        if skill_name is None:
            raise ValueError("Pi skill name is required with a skill path")
        command.extend(["--no-skills", "--skill", str(skill_path)])
        prompt = f"/skill:{skill_name} {prompt}"
    command.append(prompt)
    return command
