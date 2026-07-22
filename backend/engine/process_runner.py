from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import aiofiles

from backend.engine.process_registry import ProcessRegistry, terminate_process_group
from backend.services.crypto import SecretRedactor
from backend.services.log_broadcaster import LogBroadcaster

logger = logging.getLogger(__name__)

LineCallback = Callable[[str, str], Awaitable[None]]
DIAGNOSTIC_TAIL_BYTES = 4096


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


class ProcessRunner:
    def __init__(
        self,
        registry: ProcessRegistry,
        broadcaster: LogBroadcaster,
        termination_grace_seconds: float = 10,
    ) -> None:
        self.registry = registry
        self.broadcaster = broadcaster
        self.termination_grace_seconds = termination_grace_seconds

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
                while chunk := await stream.readline():
                    text = redactor.redact(chunk.decode("utf-8", errors="replace"))
                    await output.write(text)
                    preview.append(text)
                    tail.append(text)
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
                await asyncio.wait_for(process.wait(), timeout=spec.timeout_seconds)
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
            await asyncio.gather(stdout_task, stderr_task)
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
        )
