from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

BUBBLEWRAP_PATH = Path("/usr/bin/bwrap")


class PiSandboxError(RuntimeError):
    """Raised when Pi's filesystem sandbox cannot be established."""


def _directory(path: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PiSandboxError(f"{label} does not exist: {path}") from exc
    if not resolved.is_dir():
        raise PiSandboxError(f"{label} is not a directory: {path}")
    if resolved == Path("/"):
        raise PiSandboxError(f"{label} must not be the filesystem root")
    return resolved


def sandboxed_command(
    command: Sequence[str],
    worktree: Path,
    scratch: Path,
) -> list[str]:
    """Wrap a command in Pi's read-only-root Bubblewrap sandbox."""

    if not command:
        raise PiSandboxError("Pi sandbox command must not be empty")
    resolved_worktree = _directory(worktree, "Pi worktree")
    resolved_scratch = _directory(scratch, "Pi scratch directory")
    return [
        str(BUBBLEWRAP_PATH),
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
        str(resolved_worktree),
        str(resolved_worktree),
        "--bind",
        str(resolved_scratch),
        str(resolved_scratch),
        "--chdir",
        str(resolved_worktree),
        "--",
        *command,
    ]


def check_sandbox() -> None:
    """Exercise the complete sandbox primitive used by Prompt nodes."""

    if not BUBBLEWRAP_PATH.is_file() or not os.access(BUBBLEWRAP_PATH, os.X_OK):
        raise PiSandboxError(f"Bubblewrap is not executable at {BUBBLEWRAP_PATH}")

    with TemporaryDirectory(prefix="kyron-bwrap-check-") as root_name:
        root = Path(root_name)
        worktree = root / "worktree"
        scratch = root / "scratch"
        outside = root / "outside"
        worktree.mkdir()
        scratch.mkdir()
        outside.mkdir()
        outside_file = outside / "existing.txt"
        outside_file.write_text("preserve", encoding="utf-8")

        script = """
import os
import pathlib
import subprocess
import sys

worktree = pathlib.Path(sys.argv[1])
scratch = pathlib.Path(sys.argv[2])
outside = pathlib.Path(sys.argv[3])
outside_file = outside / "existing.txt"

assert outside_file.read_text() == "preserve"
assert not any(pathlib.Path("/proc").iterdir())
(worktree / "worktree.txt").write_text("allowed")
(scratch / "scratch.txt").write_text("allowed")

for operation in (
    lambda: (outside / "new.txt").write_text("blocked"),
    lambda: outside_file.write_text("blocked"),
    lambda: outside_file.unlink(),
    lambda: outside_file.rename(worktree / "moved.txt"),
    lambda: os.link(outside_file, worktree / "hardlink.txt"),
    lambda: os.open(outside_file, os.O_RDONLY | os.O_TRUNC),
    lambda: outside_file.chmod(0o600),
    lambda: outside_file.touch(),
):
    try:
        operation()
    except OSError:
        pass
    else:
        raise AssertionError("out-of-worktree mutation unexpectedly succeeded")

link = worktree / "outside-link"
link.symlink_to(outside_file)
try:
    link.write_text("blocked")
except OSError:
    pass
else:
    raise AssertionError("symlink escape unexpectedly succeeded")

child = subprocess.run(
    ["/bin/sh", "-c", 'printf blocked > "$1"', "sh", str(outside_file)],
    check=False,
)
assert child.returncode != 0
assert outside_file.read_text() == "preserve"
"""
        result = subprocess.run(  # noqa: S603
            sandboxed_command(
                [sys.executable, "-c", script, str(worktree), str(scratch), str(outside)],
                worktree,
                scratch,
            ),
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            suffix = f": {detail[-1000:]}" if detail else ""
            raise PiSandboxError(f"Bubblewrap confinement check failed{suffix}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the Pi Bubblewrap sandbox")
    parser.add_argument("--check", action="store_true", help="run the sandbox preflight")
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("--check is required")
    try:
        check_sandbox()
    except PiSandboxError as exc:
        print(f"Kyron Pi sandbox unavailable: {exc}", file=sys.stderr)
        return 126
    print("Bubblewrap Pi filesystem confinement is supported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
