#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from backend.engine.definition_yaml import dump_definition_yaml
from backend.schemas.workflow import WorkflowDefinition


class DuplicateJsonKeyError(ValueError):
    pass


def convert_workflow_json(raw: str) -> str:
    data = json.loads(raw, object_pairs_hook=_mapping_without_duplicate_keys)
    if not isinstance(data, dict):
        raise ValueError("The workflow must be a top-level JSON object")
    WorkflowDefinition.model_validate(data)
    return dump_definition_yaml(data)


def _mapping_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a Kyron JSON workflow and convert it to canonical YAML.",
    )
    parser.add_argument("input", type=Path, help="Path to the JSON workflow")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write YAML to this path instead of stdout",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow an existing output file to be overwritten",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        raw = args.input.read_text(encoding="utf-8")
        serialized = convert_workflow_json(raw)
        if args.output is None:
            sys.stdout.write(serialized)
            return 0
        mode = "w" if args.force else "x"
        with args.output.open(mode, encoding="utf-8") as output:
            output.write(serialized)
    except FileExistsError:
        print(
            f"error: output file already exists: {args.output} "
            "(pass --force to overwrite it)",
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(
            f"error: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}",
            file=sys.stderr,
        )
        return 2
    except (DuplicateJsonKeyError, ValidationError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
