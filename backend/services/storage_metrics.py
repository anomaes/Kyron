from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from backend.config import Settings


@dataclass(frozen=True, slots=True)
class StorageRootUsage:
    name: str
    path: Path
    bytes: int
    files: int
    filesystem_capacity_bytes: int
    filesystem_used_bytes: int
    filesystem_free_bytes: int
    filesystem_used_percent: float
    root_warning: bool
    filesystem_warning: bool


def measure_storage_roots(settings: Settings) -> list[StorageRootUsage]:
    roots = (
        ("worktrees", settings.WORKTREE_BASE_PATH, settings.WORKTREE_USAGE_WARNING_BYTES),
        ("run_data", settings.RUN_DATA_BASE_PATH, settings.RUN_DATA_USAGE_WARNING_BYTES),
    )
    return [
        _measure_root(
            name,
            path,
            warning_bytes,
            settings.FILESYSTEM_USAGE_WARNING_PERCENT,
        )
        for name, path, warning_bytes in roots
    ]


def prometheus_storage_metrics(usages: list[StorageRootUsage]) -> str:
    lines = [
        "# HELP kyron_storage_root_bytes Bytes stored beneath a Kyron resource root.",
        "# TYPE kyron_storage_root_bytes gauge",
    ]
    lines.extend(
        f'kyron_storage_root_bytes{{root="{usage.name}"}} {usage.bytes}'
        for usage in usages
    )
    lines.extend(
        [
            "# HELP kyron_storage_root_files Files stored beneath a Kyron resource root.",
            "# TYPE kyron_storage_root_files gauge",
        ]
    )
    lines.extend(
        f'kyron_storage_root_files{{root="{usage.name}"}} {usage.files}'
        for usage in usages
    )
    for metric, help_text, attribute in (
        ("filesystem_capacity_bytes", "Filesystem capacity in bytes.", "filesystem_capacity_bytes"),
        ("filesystem_used_bytes", "Filesystem used space in bytes.", "filesystem_used_bytes"),
        ("filesystem_free_bytes", "Filesystem free space in bytes.", "filesystem_free_bytes"),
        (
            "filesystem_used_percent",
            "Filesystem utilization percentage.",
            "filesystem_used_percent",
        ),
    ):
        lines.extend(
            [
                f"# HELP kyron_storage_{metric} {help_text}",
                f"# TYPE kyron_storage_{metric} gauge",
            ]
        )
        lines.extend(
            f'kyron_storage_{metric}{{root="{usage.name}"}} {getattr(usage, attribute)}'
            for usage in usages
        )
    lines.extend(
        [
            "# HELP kyron_storage_root_warning Whether a root exceeds its byte threshold.",
            "# TYPE kyron_storage_root_warning gauge",
        ]
    )
    lines.extend(
        f'kyron_storage_root_warning{{root="{usage.name}"}} {int(usage.root_warning)}'
        for usage in usages
    )
    lines.extend(
        [
            "# HELP kyron_storage_filesystem_warning "
            "Whether filesystem usage exceeds its threshold.",
            "# TYPE kyron_storage_filesystem_warning gauge",
        ]
    )
    lines.extend(
        f'kyron_storage_filesystem_warning{{root="{usage.name}"}} '
        f"{int(usage.filesystem_warning)}"
        for usage in usages
    )
    return "\n".join(lines) + "\n"


def newest_tree_mtime(path: Path) -> float:
    newest = path.stat(follow_symlinks=False).st_mtime
    for root, directories, files in os.walk(path, followlinks=False):
        for name in (*directories, *files):
            candidate = Path(root) / name
            try:
                newest = max(newest, candidate.stat(follow_symlinks=False).st_mtime)
            except FileNotFoundError:
                continue
    return newest


def _measure_root(
    name: str, path: Path, warning_bytes: int, filesystem_warning_percent: int
) -> StorageRootUsage:
    stored_bytes, files = _tree_usage(path)
    disk = shutil.disk_usage(_nearest_existing_path(path))
    used_percent = (disk.used / disk.total * 100) if disk.total else 0.0
    return StorageRootUsage(
        name=name,
        path=path,
        bytes=stored_bytes,
        files=files,
        filesystem_capacity_bytes=disk.total,
        filesystem_used_bytes=disk.used,
        filesystem_free_bytes=disk.free,
        filesystem_used_percent=used_percent,
        root_warning=warning_bytes > 0 and stored_bytes >= warning_bytes,
        filesystem_warning=used_percent >= filesystem_warning_percent,
    )


def _tree_usage(path: Path) -> tuple[int, int]:
    if not path.is_dir():
        return 0, 0
    total = 0
    files = 0
    for root, _, names in os.walk(path, followlinks=False):
        for name in names:
            candidate = Path(root) / name
            try:
                if candidate.is_symlink():
                    continue
                total += candidate.stat(follow_symlinks=False).st_size
                files += 1
            except FileNotFoundError:
                continue
    return total, files


def _nearest_existing_path(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            return Path("/")
        candidate = parent
    return candidate
