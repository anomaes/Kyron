from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import stat
from pathlib import Path

from backend.engine.context import sanitized_base_environment

MODELS_FILE_NAME = "models.json"
VALIDATOR_PATH = Path(__file__).with_name("models_config_validator.mjs")
VALIDATION_TIMEOUT_SECONDS = 15
VALIDATION_ERROR_BYTES = 8192

_STRING_OR_LINE_COMMENT = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*')
_STRING_OR_TRAILING_COMMA = re.compile(r'"(?:\\.|[^"\\])*"|,(\s*[}\]])')
_SENSITIVE_HEADER_NAME = re.compile(
    r"(?:authorization|auth|api[-_]?key|(?:^|[-_])key(?:$|[-_])|token|secret|credential|"
    r"password|cookie|signature)",
    re.IGNORECASE,
)


class PiModelsConfigError(RuntimeError):
    """Raised when the configured Pi models file cannot be safely staged."""


def _parse_document(content: str, source: Path) -> object:
    without_comments = _STRING_OR_LINE_COMMENT.sub(
        lambda match: match.group(0) if match.group(0).startswith('"') else "", content
    )
    normalized = _STRING_OR_TRAILING_COMMA.sub(
        lambda match: match.group(1) or match.group(0), without_comments
    )
    try:
        return json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise PiModelsConfigError(
            f"The Pi models file at {source} is not valid JSON: {exc}"
        ) from exc


def _environment_names(value: str) -> frozenset[str]:
    names: set[str] = set()
    index = 0
    while index < len(value):
        match = re.match(
            r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))",
            value[index:],
        )
        if match:
            name = match.group(1) or match.group(2)
            assert name is not None
            names.add(name)
            index += len(match.group(0))
        elif value.startswith(("$$", "$!"), index):
            index += 2
        else:
            index += 1
    return frozenset(names)


def _auth_references(document: object) -> frozenset[str]:
    providers = document.get("providers") if isinstance(document, dict) else None
    if not isinstance(providers, dict):
        return frozenset()
    required: set[str] = set()
    for provider_id, provider_value in providers.items():
        if not isinstance(provider_value, dict):
            continue
        locations: list[tuple[str, object, bool]] = [
            (f"providers.{provider_id}.apiKey", provider_value.get("apiKey"), True),
            (f"providers.{provider_id}.headers", provider_value.get("headers"), False),
        ]
        models = provider_value.get("models")
        if isinstance(models, list):
            locations.extend(
                (f"providers.{provider_id}.models[{index}].headers", model.get("headers"), False)
                for index, model in enumerate(models)
                if isinstance(model, dict)
            )
        overrides = provider_value.get("modelOverrides")
        if isinstance(overrides, dict):
            locations.extend(
                (
                    f"providers.{provider_id}.modelOverrides.{model_id}.headers",
                    override.get("headers"),
                    False,
                )
                for model_id, override in overrides.items()
                if isinstance(override, dict)
            )
        for path, value, always_secret in locations:
            if isinstance(value, str):
                required.update(_validate_auth_value(value, path, always_secret))
            elif isinstance(value, dict):
                for header, header_value in value.items():
                    if isinstance(header, str) and isinstance(header_value, str):
                        required.update(
                            _validate_auth_value(
                                header_value,
                                f"{path}.{header}",
                                _SENSITIVE_HEADER_NAME.search(header) is not None,
                            )
                        )
    return frozenset(required)


def _validate_auth_value(value: str, path: str, secret_required: bool) -> frozenset[str]:
    if value.startswith("!"):
        raise PiModelsConfigError(
            f"Pi models field {path} cannot execute a command; use a Kyron credential variable"
        )
    names = _environment_names(value)
    if secret_required and not names:
        raise PiModelsConfigError(
            f"Pi models field {path} must use a Kyron credential variable, not an inline secret"
        )
    return names


def stage_models_config(agent_directory: Path, source: Path | None) -> frozenset[str]:
    """Apply Kyron secret policy and copy models.json into the ephemeral agent directory."""

    if source is None:
        return frozenset()
    try:
        content = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise PiModelsConfigError(f"Cannot read the Pi models file at {source}: {exc}") from exc
    required_secrets = _auth_references(_parse_document(content, source))
    destination = agent_directory / MODELS_FILE_NAME
    destination.write_text(content, encoding="utf-8")
    destination.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return required_secrets


async def validate_models_config(
    agent_directory: Path,
    *,
    pi_executable: Path | None = None,
    node_executable: Path | None = None,
) -> None:
    """Ask the installed Pi runtime to validate models.json without network access."""

    pi_path = pi_executable or _executable("pi")
    node_path = node_executable or _executable("node")
    environment = sanitized_base_environment()
    environment.update(
        {
            "PI_CODING_AGENT_DIR": str(agent_directory),
            "PI_OFFLINE": "1",
        }
    )
    try:
        process = await asyncio.create_subprocess_exec(
            str(node_path),
            str(VALIDATOR_PATH),
            str(pi_path),
            str(agent_directory / MODELS_FILE_NAME),
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=VALIDATION_TIMEOUT_SECONDS
        )
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise PiModelsConfigError("Pi models validation timed out") from exc
    except OSError as exc:
        raise PiModelsConfigError(f"Could not start Pi models validation: {exc}") from exc
    if process.returncode != 0:
        detail = (
            (stderr or stdout)[-VALIDATION_ERROR_BYTES:].decode("utf-8", errors="replace").strip()
        )
        suffix = f": {detail}" if detail else ""
        raise PiModelsConfigError(f"Pi rejected the configured models file{suffix}")


def _executable(name: str) -> Path:
    located = shutil.which(name)
    if located is None:
        raise PiModelsConfigError(f"Cannot validate Pi models file because {name} is not installed")
    return Path(os.path.realpath(located))
