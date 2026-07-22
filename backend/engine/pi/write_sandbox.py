from __future__ import annotations

import argparse
import ctypes
import errno
import os
import platform
import sys
from collections.abc import Sequence
from pathlib import Path

LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_RULE_PATH_BENEATH = 1
PR_SET_NO_NEW_PRIVS = 38

LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12
LANDLOCK_ACCESS_FS_REFER = 1 << 13
LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14

_BASE_WRITE_ACCESS = (
    LANDLOCK_ACCESS_FS_WRITE_FILE
    | LANDLOCK_ACCESS_FS_REMOVE_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_FILE
    | LANDLOCK_ACCESS_FS_MAKE_CHAR
    | LANDLOCK_ACCESS_FS_MAKE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_REG
    | LANDLOCK_ACCESS_FS_MAKE_SOCK
    | LANDLOCK_ACCESS_FS_MAKE_FIFO
    | LANDLOCK_ACCESS_FS_MAKE_BLOCK
    | LANDLOCK_ACCESS_FS_MAKE_SYM
)
_MINIMUM_LANDLOCK_ABI = 3
_LANDLOCK_SYSCALLS = {
    "aarch64": (444, 445, 446),
    "arm64": (444, 445, 446),
    "riscv64": (444, 445, 446),
    "x86_64": (444, 445, 446),
    "amd64": (444, 445, 446),
}


class WriteSandboxError(RuntimeError):
    """Raised when the Pi write-confinement boundary cannot be enforced."""


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


def _libc() -> ctypes.CDLL:
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    library.prctl.restype = ctypes.c_int
    return library


def _syscall_numbers() -> tuple[int, int, int]:
    if sys.platform != "linux":
        raise WriteSandboxError("Pi write confinement requires Linux")
    machine = platform.machine().lower()
    try:
        return _LANDLOCK_SYSCALLS[machine]
    except KeyError as exc:
        raise WriteSandboxError(
            f"Pi write confinement does not support Linux architecture {machine!r}"
        ) from exc


def _checked_result(result: int, operation: str) -> int:
    if result >= 0:
        return result
    error_number = ctypes.get_errno()
    detail = os.strerror(error_number) if error_number else "unknown error"
    raise WriteSandboxError(f"{operation} failed: {detail}")


def landlock_abi_version() -> int:
    create_ruleset, _, _ = _syscall_numbers()
    library = _libc()
    ctypes.set_errno(0)
    result = library.syscall(
        ctypes.c_long(create_ruleset),
        ctypes.c_void_p(),
        ctypes.c_size_t(0),
        ctypes.c_uint(LANDLOCK_CREATE_RULESET_VERSION),
    )
    if result < 0 and ctypes.get_errno() in {errno.ENOSYS, errno.EOPNOTSUPP}:
        raise WriteSandboxError("Landlock is unavailable or disabled on the host kernel")
    return _checked_result(int(result), "Landlock ABI query")


def _write_access_for_abi(abi_version: int) -> int:
    if abi_version < _MINIMUM_LANDLOCK_ABI:
        raise WriteSandboxError(
            "Landlock ABI 3 or newer is required to prevent out-of-worktree truncation "
            f"(host provides ABI {abi_version})"
        )
    return _BASE_WRITE_ACCESS | LANDLOCK_ACCESS_FS_REFER | LANDLOCK_ACCESS_FS_TRUNCATE


def _add_path_rule(
    library: ctypes.CDLL,
    add_rule_number: int,
    ruleset_fd: int,
    path: Path,
    allowed_access: int,
) -> None:
    open_flags = os.O_CLOEXEC | int(os.__dict__["O_PATH"])
    path_fd = os.open(path, open_flags)
    try:
        attr = _PathBeneathAttr(allowed_access=allowed_access, parent_fd=path_fd)
        ctypes.set_errno(0)
        result = library.syscall(
            ctypes.c_long(add_rule_number),
            ctypes.c_int(ruleset_fd),
            ctypes.c_int(LANDLOCK_RULE_PATH_BENEATH),
            ctypes.byref(attr),
            ctypes.c_uint(0),
        )
        _checked_result(int(result), f"Landlock rule for {path}")
    finally:
        os.close(path_fd)


def restrict_writes_to(roots: Sequence[Path]) -> None:
    """Restrict this process and its descendants to writing beneath ``roots``."""

    resolved_roots: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve(strict=True)
        except OSError as exc:
            raise WriteSandboxError(f"Pi write root is unavailable: {root}") from exc
        if not resolved.is_dir():
            raise WriteSandboxError(f"Pi write root is not a directory: {resolved}")
        if resolved not in resolved_roots:
            resolved_roots.append(resolved)
    if not resolved_roots:
        raise WriteSandboxError("At least one Pi write root is required")

    abi_version = landlock_abi_version()
    write_access = _write_access_for_abi(abi_version)
    create_ruleset, add_rule, restrict_self = _syscall_numbers()
    library = _libc()
    ruleset_attr = _RulesetAttr(handled_access_fs=write_access)
    ctypes.set_errno(0)
    ruleset_fd = _checked_result(
        int(
            library.syscall(
                ctypes.c_long(create_ruleset),
                ctypes.byref(ruleset_attr),
                ctypes.c_size_t(ctypes.sizeof(ruleset_attr)),
                ctypes.c_uint(0),
            )
        ),
        "Landlock ruleset creation",
    )
    try:
        for root in resolved_roots:
            _add_path_rule(library, add_rule, ruleset_fd, root, write_access)
        null_device = Path("/dev/null")
        if null_device.exists():
            _add_path_rule(
                library,
                add_rule,
                ruleset_fd,
                null_device,
                LANDLOCK_ACCESS_FS_WRITE_FILE,
            )

        ctypes.set_errno(0)
        no_new_privileges = library.prctl(
            ctypes.c_int(PR_SET_NO_NEW_PRIVS),
            ctypes.c_ulong(1),
            ctypes.c_ulong(0),
            ctypes.c_ulong(0),
            ctypes.c_ulong(0),
        )
        _checked_result(int(no_new_privileges), "PR_SET_NO_NEW_PRIVS")

        ctypes.set_errno(0)
        result = library.syscall(
            ctypes.c_long(restrict_self),
            ctypes.c_int(ruleset_fd),
            ctypes.c_uint(0),
        )
        _checked_result(int(result), "Landlock enforcement")
    finally:
        os.close(ruleset_fd)


def sandboxed_command(command: Sequence[str], *write_roots: Path) -> list[str]:
    if not command:
        raise ValueError("Sandboxed command cannot be empty")
    if not write_roots:
        raise ValueError("Sandboxed command requires a write root")
    result = [sys.executable, str(Path(__file__).resolve())]
    for root in write_roots:
        result.extend(["--write-root", str(root)])
    return [*result, "--", *command]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Pi with write access confined to roots")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify that the host provides the required Landlock ABI",
    )
    parser.add_argument("--write-root", action="append", default=[], type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    command: list[str] = list(arguments.command)
    if command and command[0] == "--":
        command.pop(0)
    if arguments.check:
        try:
            abi_version = landlock_abi_version()
            _write_access_for_abi(abi_version)
            restrict_writes_to([Path.cwd()])
        except WriteSandboxError as exc:
            print(f"Kyron Pi write sandbox: {exc}", file=sys.stderr)
            return 126
        print(f"Kyron Pi write sandbox: Landlock ABI {abi_version} is supported")
        return 0
    if not arguments.write_root:
        parser.error("at least one --write-root is required")
    if not command:
        parser.error("a command is required after --")
    try:
        restrict_writes_to(arguments.write_root)
        os.execvpe(command[0], command, os.environ)  # noqa: S606 - argument array, no shell
    except (OSError, WriteSandboxError) as exc:
        print(f"Kyron Pi write sandbox: {exc}", file=sys.stderr)
        return 126
    return 126


if __name__ == "__main__":
    raise SystemExit(main())
