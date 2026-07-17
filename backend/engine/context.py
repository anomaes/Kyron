from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

VARIABLE_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class UnresolvedVariableError(ValueError):
    pass


def expand_public_variables(template: str, context: Mapping[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in context:
            raise UnresolvedVariableError(f"Public variable '{name}' is not defined")
        return str(context[name])

    return VARIABLE_PATTERN.sub(replace, template)


def sanitized_base_environment() -> dict[str, str]:
    allowed = (
        "PATH",
        "LANG",
        "LC_ALL",
        "HOME",
        "TMPDIR",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NODE_EXTRA_CA_CERTS",
    )
    return {key: value for key in allowed if (value := os.environ.get(key)) is not None}


def build_process_environment(
    public_context: Mapping[str, Any], secrets: Mapping[str, str]
) -> dict[str, str]:
    environment = sanitized_base_environment()
    environment.update({key: str(value) for key, value in public_context.items()})
    environment.update(secrets)
    return environment


def output_variables(
    node_id: str,
    exit_code: int,
    stdout: str,
    stderr: str,
    stdout_path: str,
    stderr_path: str,
) -> dict[str, str | int]:
    prefix = f"NODE_{node_id}"
    return {
        f"{prefix}_EXIT_CODE": exit_code,
        f"{prefix}_STDOUT": stdout,
        f"{prefix}_STDERR": stderr,
        f"{prefix}_STDOUT_PATH": stdout_path,
        f"{prefix}_STDERR_PATH": stderr_path,
    }
