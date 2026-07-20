from pathlib import Path

from backend.config import Settings
from backend.services.storage_metrics import measure_storage_roots, prometheus_storage_metrics


def test_storage_metrics_measure_roots_and_render_prometheus(tmp_path: Path) -> None:
    worktrees = tmp_path / "worktrees"
    run_data = tmp_path / "run-data"
    worktrees.mkdir()
    run_data.mkdir()
    (worktrees / "tracked.bin").write_bytes(b"1234")
    (run_data / "stdout.log").write_bytes(b"123456")
    configured = Settings(
        _env_file=None,
        WORKTREE_BASE_PATH=worktrees,
        RUN_DATA_BASE_PATH=run_data,
        WORKTREE_USAGE_WARNING_BYTES=4,
        RUN_DATA_USAGE_WARNING_BYTES=100,
        FILESYSTEM_USAGE_WARNING_PERCENT=100,
    )

    usages = measure_storage_roots(configured)
    by_name = {usage.name: usage for usage in usages}
    rendered = prometheus_storage_metrics(usages)

    assert by_name["worktrees"].bytes == 4
    assert by_name["worktrees"].root_warning is True
    assert by_name["run_data"].bytes == 6
    assert by_name["run_data"].root_warning is False
    assert 'kyron_storage_root_bytes{root="worktrees"} 4' in rendered
    assert 'kyron_storage_root_warning{root="worktrees"} 1' in rendered
