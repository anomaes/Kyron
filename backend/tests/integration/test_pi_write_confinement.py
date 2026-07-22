from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from backend.engine.pi.write_sandbox import sandboxed_command

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Landlock is Linux-only")


async def test_pi_write_sandbox_allows_only_worktree_and_scratch_writes(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    scratch = tmp_path / "scratch"
    outside = tmp_path / "outside"
    worktree.mkdir()
    scratch.mkdir()
    outside.mkdir()
    outside_file = outside / "existing.txt"
    outside_file.write_text("preserve me")

    script = """
import os
import pathlib
import subprocess
import sys

worktree = pathlib.Path(sys.argv[1])
scratch = pathlib.Path(sys.argv[2])
outside = pathlib.Path(sys.argv[3])
outside_file = outside / "existing.txt"

assert outside_file.read_text() == "preserve me"
(worktree / "allowed.txt").write_text("worktree")
(scratch / "allowed.txt").write_text("scratch")

for operation in (
    lambda: (outside / "new.txt").write_text("blocked"),
    lambda: outside_file.write_text("blocked"),
    lambda: outside_file.unlink(),
    lambda: outside_file.rename(worktree / "moved.txt"),
    lambda: os.link(outside_file, worktree / "linked.txt"),
    lambda: os.open(outside_file, os.O_RDONLY | os.O_TRUNC),
):
    try:
        operation()
    except PermissionError:
        pass
    else:
        raise AssertionError("out-of-worktree mutation unexpectedly succeeded")

link = worktree / "outside-link"
link.symlink_to(outside_file)
try:
    link.write_text("blocked")
except PermissionError:
    pass
else:
    raise AssertionError("symlink escape unexpectedly succeeded")

shell = subprocess.run(
    ["/bin/sh", "-c", 'printf blocked > "$1"', "sh", str(outside_file)],
    check=False,
)
assert shell.returncode != 0
assert outside_file.read_text() == "preserve me"
"""
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    command = sandboxed_command(
        [sys.executable, "-c", script, str(worktree), str(scratch), str(outside)],
        worktree,
        scratch,
    )
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=worktree,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    assert process.returncode == 0, (stdout + stderr).decode(errors="replace")
    assert (worktree / "allowed.txt").read_text() == "worktree"
    assert (scratch / "allowed.txt").read_text() == "scratch"
    assert outside_file.read_text() == "preserve me"
