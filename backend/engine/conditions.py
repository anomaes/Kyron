from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.schemas.workflow import (
    EdgeCondition,
    ExitCodeCondition,
    FileExistsCondition,
    OutputContainsCondition,
    VariableCondition,
)


def compare(left: Any, operator: str, right: Any) -> bool:
    if operator == "equals":
        return bool(left == right)
    if operator == "not_equals":
        return bool(left != right)
    if operator == "greater_than":
        return bool(left > right)
    if operator == "greater_than_or_equal":
        return bool(left >= right)
    if operator == "less_than":
        return bool(left < right)
    if operator == "less_than_or_equal":
        return bool(left <= right)
    raise ValueError(f"Unknown condition operator '{operator}'")


def safe_worktree_path(worktree: Path, relative: str) -> Path:
    candidate = (worktree / relative).resolve()
    root = worktree.resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("Condition path escapes the worktree")
    return candidate


def evaluate_condition(
    condition: EdgeCondition | None,
    *,
    exit_code: int,
    stdout: str,
    stderr: str,
    public_context: dict[str, Any],
    worktree: Path,
) -> tuple[bool, str | None]:
    if condition is None:
        return True, None
    if isinstance(condition, ExitCodeCondition):
        return compare(exit_code, condition.operator, condition.value), str(exit_code)
    if isinstance(condition, OutputContainsCondition):
        streams = {"stdout": stdout, "stderr": stderr, "combined": stdout + stderr}
        value = streams[condition.stream]
        return condition.value in value, condition.value
    if isinstance(condition, FileExistsCondition):
        path = safe_worktree_path(worktree, condition.value)
        return path.exists(), condition.value
    if isinstance(condition, VariableCondition):
        if condition.name not in public_context:
            raise ValueError(f"Condition variable '{condition.name}' is not defined")
        value = public_context[condition.name]
        return compare(str(value), condition.operator, str(condition.value)), str(value)
    raise ValueError("Unknown condition type")
