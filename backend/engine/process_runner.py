from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiofiles

from backend.engine.process_registry import ProcessRegistry, terminate_process_group
from backend.services.crypto import SecretRedactor
from backend.services.log_broadcaster import LogBroadcaster

logger = logging.getLogger(__name__)

LineCallback = Callable[[str, str], Awaitable[None]]
DIAGNOSTIC_TAIL_BYTES = 4096
STREAM_READ_CHUNK_BYTES = 64 * 1024
MAX_STREAM_FRAME_BYTES = 1 << 20
DEFAULT_MAX_ATTEMPT_OUTPUT_BYTES = 100 * 1024 * 1024
DEFAULT_STREAM_DRAIN_TIMEOUT_SECONDS = 30.0
OUTPUT_TRUNCATION_MARKER = "\n[Kyron output truncated: attempt byte limit reached]\n"


async def iter_stream_lines(stream: asyncio.StreamReader) -> AsyncIterator[bytes]:
    """Frame lines from fixed-size reads without StreamReader's per-line limit."""

    pending = bytearray()
    while chunk := await stream.read(STREAM_READ_CHUNK_BYTES):
        pending.extend(chunk)
        while (newline := pending.find(b"\n")) >= 0:
            line_end = newline + 1
            yield bytes(pending[:line_end])
            del pending[:line_end]
        while len(pending) >= MAX_STREAM_FRAME_BYTES:
            yield bytes(pending[:MAX_STREAM_FRAME_BYTES])
            del pending[:MAX_STREAM_FRAME_BYTES]
    if pending:
        yield bytes(pending)


async def wait_for_process_exit(process: asyncio.subprocess.Process) -> None:
    """Wait for the direct child without waiting for inherited pipe handles to close."""
    exited = asyncio.Event()
    loop = asyncio.get_running_loop()

    def check_returncode() -> None:
        if process.returncode is None:
            loop.call_later(0.01, check_returncode)
        else:
            exited.set()

    check_returncode()
    await exited.wait()


@dataclass(slots=True)
class ProcessSpec:
    run_id: uuid.UUID
    attempt_id: uuid.UUID
    node_path: str
    command: Sequence[str]
    cwd: Path
    environment: dict[str, str]
    output_directory: Path
    timeout_seconds: int
    max_preview_bytes: int
    stdout_filename: str = "stdout.log"
    stderr_filename: str = "stderr.log"
    broadcast_stdout: bool = True


@dataclass(slots=True)
class ProcessResult:
    exit_code: int
    stdout_path: Path
    stderr_path: Path
    stdout_preview: str
    stderr_preview: str
    stdout_tail: str = ""
    stderr_tail: str = ""
    stdout_tail_truncated: bool = False
    stderr_tail_truncated: bool = False
    timed_out: bool = False
    cancelled: bool = False
    output_truncated: bool = False
    pi_usage: dict[str, Any] | None = None
    pi_models: list[dict[str, Any]] | None = None
    pi_skill_warning: str | None = None


class BoundedPreview:
    def __init__(self, maximum_bytes: int) -> None:
        self.maximum_bytes = maximum_bytes
        self._content = bytearray()

    def append(self, text: str) -> None:
        remaining = self.maximum_bytes - len(self._content)
        if remaining <= 0:
            return
        self._content.extend(text.encode("utf-8")[:remaining])

    @property
    def text(self) -> str:
        return self._content.decode("utf-8", errors="replace")


class BoundedTail:
    def __init__(self, maximum_bytes: int) -> None:
        self.maximum_bytes = maximum_bytes
        self._content = bytearray()
        self.truncated = False

    def append(self, text: str) -> None:
        self._content.extend(text.encode("utf-8"))
        if len(self._content) > self.maximum_bytes:
            del self._content[: len(self._content) - self.maximum_bytes]
            self.truncated = True

    @property
    def text(self) -> str:
        return self._content.decode("utf-8", errors="replace")


class AttemptOutputBudget:
    def __init__(self, maximum_bytes: int) -> None:
        self.maximum_bytes = maximum_bytes
        self.written_bytes = 0
        self.truncated = False
        self._lock = asyncio.Lock()

    async def take(self, text: str) -> str:
        encoded = text.encode("utf-8")
        async with self._lock:
            remaining = self.maximum_bytes - self.written_bytes
            if len(encoded) <= remaining:
                self.written_bytes += len(encoded)
                return text
            if self.truncated or remaining <= 0:
                self.truncated = True
                return ""
            marker = OUTPUT_TRUNCATION_MARKER.encode("utf-8")
            content_bytes = max(0, remaining - len(marker))
            bounded = encoded[:content_bytes].decode("utf-8", errors="ignore")
            result = bounded + OUTPUT_TRUNCATION_MARKER
            result_bytes = result.encode("utf-8")[:remaining]
            self.written_bytes += len(result_bytes)
            self.truncated = True
            return result_bytes.decode("utf-8", errors="ignore")


class ProcessRunner:
    def __init__(
        self,
        registry: ProcessRegistry,
        broadcaster: LogBroadcaster,
        termination_grace_seconds: float = 10,
        max_attempt_output_bytes: int = DEFAULT_MAX_ATTEMPT_OUTPUT_BYTES,
        stream_drain_timeout_seconds: float = DEFAULT_STREAM_DRAIN_TIMEOUT_SECONDS,
    ) -> None:
        self.registry = registry
        self.broadcaster = broadcaster
        self.termination_grace_seconds = termination_grace_seconds
        self.max_attempt_output_bytes = max_attempt_output_bytes
        self.stream_drain_timeout_seconds = stream_drain_timeout_seconds

    async def execute(
        self,
        spec: ProcessSpec,
        *,
        secret_values: Sequence[str] = (),
        line_callback: LineCallback | None = None,
    ) -> ProcessResult:
        spec.output_directory.mkdir(parents=True, exist_ok=True)
        stdout_path = spec.output_directory / spec.stdout_filename
        stderr_path = spec.output_directory / spec.stderr_filename
        stdout_preview = BoundedPreview(spec.max_preview_bytes)
        stderr_preview = BoundedPreview(spec.max_preview_bytes)
        stdout_tail = BoundedTail(DIAGNOSTIC_TAIL_BYTES)
        stderr_tail = BoundedTail(DIAGNOSTIC_TAIL_BYTES)
        output_budget = AttemptOutputBudget(self.max_attempt_output_bytes)
        redactor = SecretRedactor(secret_values)
        logger.debug(
            "Starting node process (run=%s, attempt=%s, node_path=%s, timeout_seconds=%s)",
            spec.run_id,
            spec.attempt_id,
            spec.node_path,
            spec.timeout_seconds,
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *spec.command,
                cwd=spec.cwd,
                env=spec.environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except Exception as exc:
            redactor.clear()
            logger.exception(
                "Could not start node process (run=%s, attempt=%s, node_path=%s): %s",
                spec.run_id,
                spec.attempt_id,
                spec.node_path,
                exc,
            )
            raise
        pgid = os.getpgid(process.pid)
        await self.registry.register(spec.run_id, spec.attempt_id, pgid)

        async def copy_stream(
            stream: asyncio.StreamReader,
            path: Path,
            source: str,
            preview: BoundedPreview,
            tail: BoundedTail,
        ) -> None:
            async with aiofiles.open(path, "w", encoding="utf-8") as output:
                async for chunk in iter_stream_lines(stream):
                    text = redactor.redact(chunk.decode("utf-8", errors="replace"))
                    text = await output_budget.take(text)
                    if not text:
                        continue
                    await output.write(text)
                    preview.append(text)
                    tail.append(text)
                    if source != "stdout" or spec.broadcast_stdout:
                        await self.broadcaster.publish(
                            spec.run_id,
                            {
                                "type": "process_output",
                                "node_path": spec.node_path,
                                "attempt_id": str(spec.attempt_id),
                                "source": source,
                                "line": text.rstrip("\n"),
                            },
                        )
                    if line_callback:
                        await line_callback(source, text)

        assert process.stdout is not None
        assert process.stderr is not None
        stdout_task = asyncio.create_task(
            copy_stream(process.stdout, stdout_path, "stdout", stdout_preview, stdout_tail)
        )
        stderr_task = asyncio.create_task(
            copy_stream(process.stderr, stderr_path, "stderr", stderr_preview, stderr_tail)
        )
        timed_out = False
        cancelled = False
        try:
            try:
                await asyncio.wait_for(
                    wait_for_process_exit(process), timeout=spec.timeout_seconds
                )
            except TimeoutError:
                timed_out = True
                logger.warning(
                    "Node process timed out; terminating process group "
                    "(run=%s, attempt=%s, node_path=%s, timeout_seconds=%s)",
                    spec.run_id,
                    spec.attempt_id,
                    spec.node_path,
                    spec.timeout_seconds,
                )
                await terminate_process_group(pgid, self.termination_grace_seconds)
                await process.wait()
            drain = asyncio.gather(stdout_task, stderr_task)
            try:
                await asyncio.wait_for(
                    asyncio.shield(drain),
                    timeout=self.stream_drain_timeout_seconds,
                )
            except TimeoutError:
                logger.warning(
                    "Node process streams remained open after exit; terminating process group "
                    "(run=%s, attempt=%s, node_path=%s)",
                    spec.run_id,
                    spec.attempt_id,
                    spec.node_path,
                )
                await terminate_process_group(pgid, self.termination_grace_seconds)
                try:
                    await asyncio.wait_for(
                        asyncio.shield(drain),
                        timeout=self.stream_drain_timeout_seconds,
                    )
                except TimeoutError:
                    stdout_task.cancel()
                    stderr_task.cancel()
                    await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        except asyncio.CancelledError:
            cancelled = True
            logger.info(
                "Node process cancellation requested (run=%s, attempt=%s, node_path=%s)",
                spec.run_id,
                spec.attempt_id,
                spec.node_path,
            )
            await terminate_process_group(pgid, self.termination_grace_seconds)
            await process.wait()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        finally:
            await self.registry.unregister(spec.run_id, spec.attempt_id)
            redactor.clear()
        logger.debug(
            "Node process exited "
            "(run=%s, attempt=%s, node_path=%s, exit_code=%s, timed_out=%s, cancelled=%s)",
            spec.run_id,
            spec.attempt_id,
            spec.node_path,
            process.returncode,
            timed_out,
            cancelled,
        )
        return ProcessResult(
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            stdout_preview=stdout_preview.text,
            stderr_preview=stderr_preview.text,
            stdout_tail=stdout_tail.text,
            stderr_tail=stderr_tail.text,
            stdout_tail_truncated=stdout_tail.truncated,
            stderr_tail_truncated=stderr_tail.truncated,
            timed_out=timed_out,
            cancelled=cancelled,
            output_truncated=output_budget.truncated,
        )
