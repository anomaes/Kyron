from pathlib import Path

import pytest

from backend.engine.pi import write_sandbox
from backend.engine.pi.write_sandbox import (
    WriteSandboxError,
    _write_access_for_abi,
    sandboxed_command,
)


def test_sandboxed_command_wraps_an_argument_array(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.engine.pi.write_sandbox.sys.executable", "/usr/bin/python3")

    assert sandboxed_command(
        ["pi", "--mode", "json", "ship"],
        Path("/worktree"),
        Path("/scratch"),
    ) == [
        "/usr/bin/python3",
        str(Path(write_sandbox.__file__).resolve()),
        "--write-root",
        "/worktree",
        "--write-root",
        "/scratch",
        "--",
        "pi",
        "--mode",
        "json",
        "ship",
    ]


def test_landlock_abi_must_cover_file_truncation() -> None:
    with pytest.raises(WriteSandboxError, match="ABI 3 or newer"):
        _write_access_for_abi(2)
    assert _write_access_for_abi(3) > 0


def test_check_reports_a_supported_landlock_abi(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(write_sandbox, "landlock_abi_version", lambda: 4)
    monkeypatch.setattr(write_sandbox, "restrict_writes_to", lambda roots: None)

    assert write_sandbox.main(["--check"]) == 0
    assert "Landlock ABI 4 is supported" in capsys.readouterr().out
