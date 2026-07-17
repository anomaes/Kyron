import pytest

from backend.engine.context import (
    UnresolvedVariableError,
    build_process_environment,
    expand_public_variables,
    output_variables,
)


def test_public_expansion_does_not_include_secret_environment() -> None:
    public = {"TASK": "ship it"}
    secrets = {"API_KEY": "secret"}
    assert expand_public_variables("Task: ${TASK}; shell: $API_KEY", public) == (
        "Task: ship it; shell: $API_KEY"
    )
    with pytest.raises(UnresolvedVariableError):
        expand_public_variables("${API_KEY}", public)
    assert build_process_environment(public, secrets)["API_KEY"] == "secret"


def test_output_variables_are_scoped_by_node_id() -> None:
    values = output_variables("test", 0, "ok", "", "out.log", "err.log")
    assert values["NODE_test_EXIT_CODE"] == 0
    assert values["NODE_test_STDOUT"] == "ok"
