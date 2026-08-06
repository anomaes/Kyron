from __future__ import annotations

import re
from pathlib import Path

import yaml

from backend.schemas.pi import PiSettings

SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKILL_NAME_MAX_LENGTH = 64
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


def _parse_skill_frontmatter(text: str) -> dict[str, object] | None:
    """Extract the YAML frontmatter mapping the way Pi's own skill loader does."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---"):
        return None
    end = normalized.find("\n---", 3)
    if end == -1:
        return None
    try:
        loaded = yaml.safe_load(normalized[4:end])
    except yaml.YAMLError:
        return None
    return loaded if isinstance(loaded, dict) else None


class PiSkillUnavailable(Exception):
    """Raised when Pi would not load the configured skill.

    Pi discards an unloadable skill without reporting it and passes the unexpanded
    `/skill:<name>` text through to the model, so callers report this and run the
    prompt without the skill rather than with a silently inert command.
    """

    def __init__(self, configured_path: str, reason: str) -> None:
        super().__init__(f"Pi skill '{configured_path}' {reason}")
        self.configured_path = configured_path
        self.reason = reason


def resolve_pi_skill(worktree: Path, configured_path: str) -> tuple[Path, str]:
    """Resolve a repository skill and extract the Pi command name from its frontmatter.

    Raises PiSkillUnavailable for every condition Pi rejects, and ValueError for a
    path that escapes the worktree.
    """

    root = worktree.resolve()
    requested = (root / configured_path).resolve()
    if not requested.is_relative_to(root):
        raise ValueError("Pi skill path must remain inside the worktree")
    manifest = requested / "SKILL.md" if requested.is_dir() else requested
    manifest = manifest.resolve()
    if not manifest.is_relative_to(root):
        raise ValueError("Pi skill path must remain inside the worktree")
    if not manifest.is_file():
        raise PiSkillUnavailable(configured_path, "does not exist inside the run worktree")
    frontmatter = _parse_skill_frontmatter(manifest.read_text(encoding="utf-8"))
    if frontmatter is None:
        raise PiSkillUnavailable(configured_path, "has no YAML frontmatter mapping")
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        raise PiSkillUnavailable(
            configured_path, "declares no description, which Pi requires to load a skill"
        )
    # Pi falls back to the containing directory name when frontmatter omits `name`.
    name = frontmatter.get("name") or manifest.parent.name
    if (
        not isinstance(name, str)
        or len(name) > SKILL_NAME_MAX_LENGTH
        or SKILL_NAME_PATTERN.fullmatch(name) is None
    ):
        raise PiSkillUnavailable(configured_path, f"has an invalid Pi command name: {name!r}")
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
