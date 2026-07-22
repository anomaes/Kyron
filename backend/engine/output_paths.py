from __future__ import annotations

from pathlib import Path


def safe_node_path(node_path: str) -> str:
    return "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in node_path
    )


def node_attempt_directory(run_data: Path, node_path: str, attempt_number: int) -> Path:
    if attempt_number < 1:
        raise ValueError("Attempt number must be positive")
    return run_data / "outputs" / safe_node_path(node_path) / f"attempt-{attempt_number}"
