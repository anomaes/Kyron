from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ASKPASS_PROGRAM = """#!/bin/sh
case "$1" in
  *sername*) printf '%s\\n' "$KYRON_GIT_USERNAME" ;;
  *) printf '%s\\n' "$KYRON_GIT_PASSWORD" ;;
esac
"""


@contextmanager
def temporary_git_askpass(username: str, password: str) -> Iterator[dict[str, str]]:
    file_descriptor, raw_path = tempfile.mkstemp(prefix="kyron-askpass-")
    path = Path(raw_path)
    try:
        os.write(file_descriptor, ASKPASS_PROGRAM.encode())
        os.close(file_descriptor)
        file_descriptor = -1
        path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        yield {
            "GIT_ASKPASS": str(path),
            "GIT_TERMINAL_PROMPT": "0",
            "KYRON_GIT_USERNAME": username,
            "KYRON_GIT_PASSWORD": password,
        }
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        path.unlink(missing_ok=True)
