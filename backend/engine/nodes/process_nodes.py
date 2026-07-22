from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.engine.context import build_process_environment, expand_public_variables
from backend.engine.pi.command import build_pi_command, resolve_pi_skill
from backend.engine.pi.json_events import PiEventCollector
from backend.engine.pi.renderer import render_event
from backend.engine.pi.sandbox import sandboxed_command
from backend.engine.process_runner import (
    DIAGNOSTIC_TAIL_BYTES,
    BoundedTail,
    ProcessResult,
    ProcessRunner,
    ProcessSpec,
)
from backend.schemas.pi import PiSettings
from backend.schemas.workflow import BashNode, PromptNode, ScriptNode


@dataclass(slots=True)
class NodeExecutionRequest:
    run_id: uuid.UUID
    attempt_id: uuid.UUID
    node_path: str
    worktree: Path
    output_directory: Path
    public_context: dict[str, object]
    secrets: dict[str, str]
    default_timeout: int
    max_preview_bytes: int
    pi: PiSettings


class ProcessNodeExecutor:
    def __init__(self, runner: ProcessRunner) -> None:
        self.runner = runner

    async def execute(
        self,
        node: BashNode | ScriptNode | PromptNode,
        request: NodeExecutionRequest,
    ) -> ProcessResult:
        timeout = node.config.timeout or request.default_timeout
        callback = None
        stdout_filename = "stdout.log"
        collector: PiEventCollector | None = None
        environment: dict[str, str] = {}
        pi_scratch: TemporaryDirectory[str] | None = None
        try:
            if isinstance(node, BashNode):
                command = [
                    node.config.shell,
                    "-lc",
                    expand_public_variables(node.config.command, request.public_context),
                ]
            elif isinstance(node, ScriptNode):
                script = (request.worktree / node.config.script).resolve()
                if not script.is_relative_to(request.worktree.resolve()) or not script.is_file():
                    raise ValueError("Script does not exist inside the worktree")
                command = [
                    node.config.python,
                    str(script),
                    *[
                        expand_public_variables(argument, request.public_context)
                        for argument in node.config.args
                    ],
                ]
            else:
                prompt = expand_public_variables(node.config.prompt, request.public_context)
                skill_path = None
                skill_name = None
                if request.pi.skill is not None:
                    skill_path, skill_name = resolve_pi_skill(request.worktree, request.pi.skill)
                command = build_pi_command(
                    prompt,
                    request.pi.provider,
                    request.pi.model,
                    skill_path=skill_path,
                    skill_name=skill_name,
                )
                collector = PiEventCollector()

                async def collect_and_publish(source: str, line: str) -> None:
                    assert collector is not None
                    before = len(collector.events)
                    await collector.accept(source, line)
                    if len(collector.events) > before:
                        await self.runner.broadcaster.publish(
                            request.run_id,
                            {
                                "type": "pi_event",
                                "node_path": request.node_path,
                                "message": render_event(collector.events[-1]),
                            },
                        )

                callback = collect_and_publish
                stdout_filename = "pi_events.jsonl"

            environment = build_process_environment(request.public_context, request.secrets)
            if isinstance(node, PromptNode):
                pi_scratch = TemporaryDirectory(prefix=f"kyron-pi-{request.attempt_id}-")
                scratch_root = Path(pi_scratch.name)
                agent_directory = scratch_root / "agent"
                cache_directory = scratch_root / "cache"
                temporary_directory = scratch_root / "tmp"
                agent_directory.mkdir()
                cache_directory.mkdir()
                temporary_directory.mkdir()
                environment.update(
                    {
                        "GIT_OPTIONAL_LOCKS": "0",
                        "PI_CODING_AGENT_DIR": str(agent_directory),
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "TMPDIR": str(temporary_directory),
                        "XDG_CACHE_HOME": str(cache_directory),
                    }
                )
                command = sandboxed_command(command, request.worktree, scratch_root)
            result = await self.runner.execute(
                ProcessSpec(
                    run_id=request.run_id,
                    attempt_id=request.attempt_id,
                    node_path=request.node_path,
                    command=command,
                    cwd=request.worktree,
                    environment=environment,
                    output_directory=request.output_directory,
                    timeout_seconds=timeout,
                    max_preview_bytes=request.max_preview_bytes,
                    stdout_filename=stdout_filename,
                ),
                secret_values=list(request.secrets.values()),
                line_callback=callback,
            )
        finally:
            request.secrets.clear()
            environment.clear()
            if pi_scratch is not None:
                pi_scratch.cleanup()
        if isinstance(node, PromptNode) and collector is not None:
            failure_message = None
            if collector.errors:
                failure_message = "Pi emitted malformed JSONL"
            elif collector.failure_message is not None:
                failure_message = f"Pi reported failure: {collector.failure_message}"
            if failure_message is not None:
                stderr_tail = BoundedTail(DIAGNOSTIC_TAIL_BYTES)
                stderr_tail.append(result.stderr_tail)
                stderr_tail.append(f"\n{failure_message}")
                return ProcessResult(
                    exit_code=result.exit_code or 1,
                    stdout_path=result.stdout_path,
                    stderr_path=result.stderr_path,
                    stdout_preview=result.stdout_preview,
                    stderr_preview=(result.stderr_preview + f"\n{failure_message}").strip(),
                    stdout_tail=result.stdout_tail,
                    stderr_tail=stderr_tail.text.strip(),
                    stdout_tail_truncated=result.stdout_tail_truncated,
                    stderr_tail_truncated=(
                        result.stderr_tail_truncated or stderr_tail.truncated
                    ),
                    timed_out=result.timed_out,
                    cancelled=result.cancelled,
                )
        return result
