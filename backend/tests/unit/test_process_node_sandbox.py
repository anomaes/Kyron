from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path

from backend.engine.nodes.process_nodes import NodeExecutionRequest, ProcessNodeExecutor
from backend.engine.process_runner import LineCallback, ProcessResult, ProcessRunner, ProcessSpec
from backend.schemas.pi import PiSettings
from backend.schemas.workflow import BashConfig, BashNode, PromptConfig, PromptNode
from backend.services.log_broadcaster import LogBroadcaster


class CapturingRunner(ProcessRunner):
    def __init__(self) -> None:
        self.broadcaster = LogBroadcaster()
        self.command: list[str] = []
        self.environment: dict[str, str] = {}
        self.secret_values: list[str] = []
        self.scratch_root: Path | None = None

    async def execute(
        self,
        spec: ProcessSpec,
        *,
        secret_values: Sequence[str] = (),
        line_callback: LineCallback | None = None,
    ) -> ProcessResult:
        del line_callback
        self.command = list(spec.command)
        self.environment = dict(spec.environment)
        self.secret_values = list(secret_values)
        bind_indexes = [
            index for index, value in enumerate(self.command) if value == "--bind"
        ]
        if bind_indexes:
            self.scratch_root = Path(self.command[bind_indexes[-1] + 1])
            assert self.scratch_root.is_dir()
        spec.output_directory.mkdir(parents=True, exist_ok=True)
        stdout = spec.output_directory / spec.stdout_filename
        stderr = spec.output_directory / spec.stderr_filename
        stdout.write_text("")
        stderr.write_text("")
        return ProcessResult(
            exit_code=0,
            stdout_path=stdout,
            stderr_path=stderr,
            stdout_preview="",
            stderr_preview="",
        )


def request(tmp_path: Path, secrets: dict[str, str]) -> NodeExecutionRequest:
    worktree = tmp_path / "worktree"
    worktree.mkdir(exist_ok=True)
    return NodeExecutionRequest(
        run_id=uuid.uuid4(),
        attempt_id=uuid.uuid4(),
        node_path="root/node",
        worktree=worktree,
        output_directory=tmp_path / "output",
        public_context={"TASK": "ship"},
        secrets=secrets,
        default_timeout=60,
        max_preview_bytes=1024,
        pi=PiSettings(provider="anthropic", model="anthropic/model"),
    )


async def test_prompt_node_is_write_confined_and_uses_ephemeral_pi_state(tmp_path: Path) -> None:
    runner = CapturingRunner()
    secrets = {"ANTHROPIC_API_KEY": "secret"}
    operation = request(tmp_path, secrets)

    await ProcessNodeExecutor(runner).execute(
        PromptNode(
            type="prompt",
            id="prompt",
            label="Prompt",
            config=PromptConfig(prompt="Implement ${TASK}"),
        ),
        operation,
    )

    assert runner.command[0] == "/usr/bin/bwrap"
    assert runner.command.count("--bind") == 2
    assert str(operation.worktree) in runner.command
    assert runner.command[runner.command.index("--") + 1] == "pi"
    assert runner.environment["GIT_OPTIONAL_LOCKS"] == "0"
    assert runner.environment["ANTHROPIC_API_KEY"] == "secret"
    assert runner.environment["PI_CODING_AGENT_DIR"].endswith("/agent")
    assert runner.secret_values == ["secret"]
    assert runner.scratch_root is not None
    assert not runner.scratch_root.exists()
    assert secrets == {}


async def test_bash_node_does_not_use_pi_write_confinement(tmp_path: Path) -> None:
    runner = CapturingRunner()
    operation = request(tmp_path, {})

    await ProcessNodeExecutor(runner).execute(
        BashNode(
            type="bash", id="bash", label="Bash", config=BashConfig(command="pwd")
        ),
        operation,
    )

    assert runner.command == ["/bin/bash", "-lc", "pwd"]
    assert "PI_CODING_AGENT_DIR" not in runner.environment
    assert "--bind" not in runner.command
