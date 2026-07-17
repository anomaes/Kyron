from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from backend.engine.context import build_process_environment, expand_public_variables
from backend.engine.pi.command import build_pi_command
from backend.engine.pi.json_events import PiEventCollector
from backend.engine.pi.renderer import render_event
from backend.engine.process_runner import ProcessResult, ProcessRunner, ProcessSpec
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
            command = build_pi_command(prompt, node.config.provider, node.config.model)
            collector = PiEventCollector()

            async def collect_and_publish(source: str, line: str) -> None:
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
        try:
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
        if isinstance(node, PromptNode) and collector.errors:
            return ProcessResult(
                exit_code=result.exit_code or 1,
                stdout_path=result.stdout_path,
                stderr_path=result.stderr_path,
                stdout_preview=result.stdout_preview,
                stderr_preview=(result.stderr_preview + "\nPi emitted malformed JSONL").strip(),
                timed_out=result.timed_out,
                cancelled=result.cancelled,
            )
        return result
