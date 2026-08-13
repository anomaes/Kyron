from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

from backend.engine.pi.json_events import PiEventCollector
from backend.engine.process_registry import ProcessRegistry
from backend.engine.process_runner import (
    MAX_STREAM_FRAME_BYTES,
    OUTPUT_TRUNCATION_MARKER,
    ProcessRunner,
    ProcessSpec,
    iter_stream_lines,
)
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
    assert result.stdout_tail.endswith("x" * 18 + "\n")
    assert "secret-value" not in result.stdout_tail
    assert "[REDACTED]" in result.stdout_tail
    assert result.stderr_tail == "err\n"


async def test_process_result_keeps_bounded_redacted_diagnostic_tail(tmp_path: Path) -> None:
    registry = ProcessRegistry()
    runner = ProcessRunner(registry, LogBroadcaster())
    result = await runner.execute(
        ProcessSpec(
            run_id=uuid.uuid4(),
            attempt_id=uuid.uuid4(),
            node_path="root/fail",
            command=[
                sys.executable,
                "-c",
                "import sys; "
                "print('old-output-' + 'x' * 5000, file=sys.stderr); "
                "print('token-value final diagnostic', file=sys.stderr)",
            ],
            cwd=tmp_path,
            environment={},
            output_directory=tmp_path / "tail-output",
            timeout_seconds=5,
            max_preview_bytes=20,
        ),
        secret_values=["token-value"],
    )

    assert len(result.stderr_tail.encode()) <= 4096
    assert result.stderr_tail_truncated
    assert "old-output-" not in result.stderr_tail
    assert "token-value" not in result.stderr_tail
    assert "[REDACTED] final diagnostic" in result.stderr_tail


async def test_stdout_can_be_persisted_and_parsed_without_broadcasting_raw_lines(
    tmp_path: Path,
) -> None:
    run_id = uuid.uuid4()
    broadcaster = LogBroadcaster()
    subscription = broadcaster.subscribe(run_id)
    callback_lines: list[tuple[str, str]] = []

    async def capture(source: str, line: str) -> None:
        callback_lines.append((source, line))

    result = await ProcessRunner(ProcessRegistry(), broadcaster).execute(
        ProcessSpec(
            run_id=run_id,
            attempt_id=uuid.uuid4(),
            node_path="root/prompt",
            command=[
                sys.executable,
                "-c",
                "import sys; print('{\"type\":\"agent_start\"}'); "
                "print('warning', file=sys.stderr)",
            ],
            cwd=tmp_path,
            environment={},
            output_directory=tmp_path / "pi-output",
            timeout_seconds=5,
            max_preview_bytes=100,
            stdout_filename="pi_events.jsonl",
            broadcast_stdout=False,
        ),
        line_callback=capture,
    )

    events = []
    while not subscription.queue.empty():
        events.append(subscription.queue.get_nowait())
    assert result.stdout_path.read_text() == '{"type":"agent_start"}\n'
    assert ("stdout", '{"type":"agent_start"}\n') in callback_lines
    assert [event["source"] for event in events] == ["stderr"]


async def test_oversized_pi_event_is_drained_before_following_tool_error(
    tmp_path: Path,
) -> None:
    collector = PiEventCollector()

    result = await ProcessRunner(ProcessRegistry(), LogBroadcaster(), 0.1).execute(
        ProcessSpec(
            run_id=uuid.uuid4(),
            attempt_id=uuid.uuid4(),
            node_path="root/prompt",
            command=[
                sys.executable,
                "-c",
                (
                    "import json\n"
                    "events = [\n"
                    "  {'type': 'tool_execution_end', 'toolCallId': 'large-read', "
                    "'toolName': 'read', 'result': {'content': [{'type': 'text', "
                    "'text': 'Rückrollschutz ' * 10_000}]}, 'isError': False},\n"
                    "  {'type': 'tool_execution_end', 'toolCallId': 'failed-read', "
                    "'toolName': 'read', 'result': {'content': [{'type': 'text', "
                    "'text': 'document is too large'}]}, 'isError': True},\n"
                    "  {'type': 'agent_end', 'messages': [{'role': 'assistant', "
                    "'content': [{'type': 'text', 'text': 'continued'}], "
                    "'stopReason': 'stop'}], 'willRetry': False},\n"
                    "]\n"
                    "for event in events:\n"
                    "    print(json.dumps(event, ensure_ascii=False), flush=True)\n"
                ),
            ],
            cwd=tmp_path,
            environment={},
            output_directory=tmp_path / "oversized-pi-output",
            timeout_seconds=5,
            max_preview_bytes=100,
            stdout_filename="pi_events.jsonl",
            broadcast_stdout=False,
        ),
        line_callback=collector.accept,
    )

    persisted_events = [
        json.loads(line) for line in result.stdout_path.read_text().splitlines()
    ]
    assert result.exit_code == 0
    assert (
        persisted_events[0]["result"]["content"][0]["text"]
        == "Rückrollschutz " * 10_000
    )
    assert [event["type"] for event in collector.events] == [
        "tool_execution_end",
        "tool_execution_end",
        "agent_end",
    ]
    assert collector.events[1]["isError"]
    assert collector.failure_message is None


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


async def test_stream_framing_bounds_output_without_newlines() -> None:
    stream = asyncio.StreamReader()
    stream.feed_data(b"x" * (MAX_STREAM_FRAME_BYTES * 2 + 17))
    stream.feed_eof()

    frames = [frame async for frame in iter_stream_lines(stream)]

    assert [len(frame) for frame in frames] == [
        MAX_STREAM_FRAME_BYTES,
        MAX_STREAM_FRAME_BYTES,
        17,
    ]


async def test_attempt_output_budget_truncates_combined_streams(tmp_path: Path) -> None:
    runner = ProcessRunner(
        ProcessRegistry(),
        LogBroadcaster(),
        max_attempt_output_bytes=1024,
    )
    result = await runner.execute(
        ProcessSpec(
            run_id=uuid.uuid4(),
            attempt_id=uuid.uuid4(),
            node_path="root/chatty",
            command=[
                sys.executable,
                "-c",
                "import sys; print('x' * 4000); print('y' * 4000, file=sys.stderr)",
            ],
            cwd=tmp_path,
            environment={},
            output_directory=tmp_path / "bounded-output",
            timeout_seconds=5,
            max_preview_bytes=2048,
        )
    )

    persisted = result.stdout_path.read_text() + result.stderr_path.read_text()
    assert result.output_truncated
    assert len(result.stdout_path.read_bytes()) + len(result.stderr_path.read_bytes()) <= 1024
    assert OUTPUT_TRUNCATION_MARKER.strip() in persisted


async def test_stream_drain_timeout_terminates_background_pipe_holder(
    tmp_path: Path,
) -> None:
    runner = ProcessRunner(
        ProcessRegistry(),
        LogBroadcaster(),
        termination_grace_seconds=0.1,
        stream_drain_timeout_seconds=0.1,
    )
    started = time.monotonic()

    result = await runner.execute(
        ProcessSpec(
            run_id=uuid.uuid4(),
            attempt_id=uuid.uuid4(),
            node_path="root/background",
            command=[
                sys.executable,
                "-c",
                (
                    "import subprocess, sys; "
                    "subprocess.Popen([sys.executable, '-c', "
                    "'import time; time.sleep(30)']); print('done')"
                ),
            ],
            cwd=tmp_path,
            environment={},
            output_directory=tmp_path / "background-output",
            timeout_seconds=5,
            max_preview_bytes=100,
        )
    )

    assert time.monotonic() - started < 3
    assert result.exit_code == 0
    assert result.stdout_preview == "done\n"
