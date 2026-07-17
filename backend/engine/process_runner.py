from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import aiofiles

from backend.engine.process_registry import ProcessRegistry, terminate_process_group
from backend.services.crypto import SecretRedactor
from backend.services.log_broadcaster import LogBroadcaster

LineCallback = Callable[[str, str], Awaitable[None]]


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
        redactor = SecretRedactor(secret_values)
        process = await asyncio.create_subprocess_exec(
            *spec.command,
            cwd=spec.cwd,
            env=spec.environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        pgid = os.getpgid(process.pid)
        await self.registry.register(spec.run_id, spec.attempt_id, pgid)

        async def copy_stream(
            stream: asyncio.StreamReader,
            path: Path,
            source: str,
            preview: BoundedPreview,
        ) -> None:
            async with aiofiles.open(path, "w", encoding="utf-8") as output:
                while chunk := await stream.readline():
                    text = redactor.redact(chunk.decode("utf-8", errors="replace"))
                    await output.write(text)
                    preview.append(text)
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
            copy_stream(process.stdout, stdout_path, "stdout", stdout_preview)
        )
        stderr_task = asyncio.create_task(
            copy_stream(process.stderr, stderr_path, "stderr", stderr_preview)
        )
        timed_out = False
        cancelled = False
        try:
            try:
                await asyncio.wait_for(process.wait(), timeout=spec.timeout_seconds)
            except TimeoutError:
                timed_out = True
                await terminate_process_group(pgid, self.termination_grace_seconds)
                await process.wait()
            await asyncio.gather(stdout_task, stderr_task)
        except asyncio.CancelledError:
            cancelled = True
            await terminate_process_group(pgid, self.termination_grace_seconds)
            await process.wait()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        finally:
            await self.registry.unregister(spec.run_id, spec.attempt_id)
            redactor.clear()
        return ProcessResult(
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            stdout_preview=stdout_preview.text,
            stderr_preview=stderr_preview.text,
            timed_out=timed_out,
            cancelled=cancelled,
        )
