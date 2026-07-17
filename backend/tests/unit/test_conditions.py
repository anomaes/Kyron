from pathlib import Path

import pytest
from pydantic import TypeAdapter

from backend.engine.conditions import evaluate_condition, safe_worktree_path
from backend.schemas.workflow import EdgeCondition

adapter: TypeAdapter[EdgeCondition] = TypeAdapter(EdgeCondition)


def test_exit_output_file_and_variable_conditions(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text("{}")
    exit_condition = adapter.validate_python(
        {"type": "exit_code", "operator": "equals", "value": 0}
    )
    output_condition = adapter.validate_python(
        {"type": "output_contains", "value": "SUCCESS", "stream": "combined"}
    )
    file_condition = adapter.validate_python({"type": "file_exists", "value": "report.json"})
    variable_condition = adapter.validate_python(
        {"type": "variable", "name": "STATUS", "operator": "equals", "value": "ok"}
    )

    def evaluate(condition: EdgeCondition) -> bool:
        return evaluate_condition(
            condition,
            exit_code=0,
            stdout="SUCCESS\n",
            stderr="",
            public_context={"STATUS": "ok"},
            worktree=tmp_path,
        )[0]

    assert evaluate(exit_condition)
    assert evaluate(output_condition)
    assert evaluate(file_condition)
    assert evaluate(variable_condition)


def test_condition_path_escape_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        safe_worktree_path(tmp_path, "../outside")
