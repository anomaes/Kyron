from __future__ import annotations

import sys
import uuid
from pathlib import Path

from backend.engine.process_registry import ProcessRegistry
from backend.engine.process_runner import ProcessRunner, ProcessSpec
from backend.services.log_broadcaster import LogBroadcaster


async def test_process_output_is_bounded_redacted_and_persisted(tmp_path: Path) -> None:
    run_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    runner = ProcessRunner(ProcessRegistry(), LogBroadcaster(), 0.1)
    result = await runner.execute(
        ProcessSpec(
            run_id=run_id,
            attempt_id=attempt_id,
            node_path="root/node",
            command=[
                sys.executable,
                "-c",
                "import sys; print('secret-value ' + 'x' * 100); print('err', file=sys.stderr)",
            ],
            cwd=tmp_path,
            environment={},
            output_directory=tmp_path / "output",
            timeout_seconds=5,
            max_preview_bytes=20,
        ),
        secret_values=["secret-value"],
    )
    assert result.exit_code == 0
    assert len(result.stdout_preview.encode()) <= 20
    assert "secret-value" not in result.stdout_path.read_text()
    assert "[REDACTED]" in result.stdout_path.read_text()
    assert result.stderr_path.read_text() == "err\n"


async def test_timeout_terminates_the_process_group(tmp_path: Path) -> None:
    runner = ProcessRunner(ProcessRegistry(), LogBroadcaster(), 0.1)
    result = await runner.execute(
        ProcessSpec(
            run_id=uuid.uuid4(),
            attempt_id=uuid.uuid4(),
            node_path="root/slow",
            command=[sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
            environment={},
            output_directory=tmp_path / "timeout",
            timeout_seconds=1,
            max_preview_bytes=100,
        )
    )
    assert result.timed_out
    assert result.exit_code != 0
