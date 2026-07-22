from pathlib import Path

import pytest

from backend.engine.pi import sandbox
from backend.engine.pi.sandbox import PiSandboxError, sandboxed_command


def test_sandboxed_command_builds_read_only_root_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = tmp_path / "worktree"
    scratch = tmp_path / "scratch"
    worktree.mkdir()
    scratch.mkdir()
    monkeypatch.setattr(sandbox, "BUBBLEWRAP_PATH", Path("/test/bwrap"))

    assert sandboxed_command(["pi", "--mode", "json", "ship"], worktree, scratch) == [
        "/test/bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-user",
        "--unshare-pid",
        "--cap-drop",
        "ALL",
        "--ro-bind",
        "/",
        "/",
        "--tmpfs",
        "/proc",
        "--remount-ro",
        "/proc",
        "--dev",
        "/dev",
        "--bind",
        str(worktree),
        str(worktree),
        "--bind",
        str(scratch),
        str(scratch),
        "--chdir",
        str(worktree),
        "--",
        "pi",
        "--mode",
        "json",
        "ship",
    ]


def test_sandboxed_command_rejects_invalid_write_roots(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    with pytest.raises(PiSandboxError, match="does not exist"):
        sandboxed_command(["pi"], tmp_path / "missing", scratch)
    with pytest.raises(PiSandboxError, match="filesystem root"):
        sandboxed_command(["pi"], Path("/"), scratch)


def test_check_cli_reports_supported_sandbox(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sandbox, "check_sandbox", lambda: None)

    assert sandbox.main(["--check"]) == 0
    assert "Bubblewrap Pi filesystem confinement is supported" in capsys.readouterr().out


def test_check_cli_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> None:
        raise PiSandboxError("user namespaces are blocked")

    monkeypatch.setattr(sandbox, "check_sandbox", fail)

    assert sandbox.main(["--check"]) == 126
