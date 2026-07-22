from pathlib import Path

from backend.engine.process_runner import ProcessResult
from backend.engine.waves import _failure_diagnostics


def test_failure_diagnostics_lists_stderr_before_stdout() -> None:
    result = ProcessResult(
        exit_code=1,
        stdout_path=Path("stdout.log"),
        stderr_path=Path("stderr.log"),
        stdout_preview="",
        stderr_preview="",
        stdout_tail="command context\n",
        stderr_tail="specific failure\n",
        stderr_tail_truncated=True,
    )

    assert _failure_diagnostics(result) == (
        "\nstderr:\n[earlier output omitted]\nspecific failure\nstdout:\ncommand context"
    )


def test_failure_diagnostics_explains_empty_output() -> None:
    result = ProcessResult(
        exit_code=1,
        stdout_path=Path("stdout.log"),
        stderr_path=Path("stderr.log"),
        stdout_preview="",
        stderr_preview="",
    )

    assert _failure_diagnostics(result) == "\nNo stdout or stderr was captured."
