from __future__ import annotations

import json
import shutil
import stat
import uuid
from collections.abc import Sequence
from pathlib import Path

import pytest

from backend.engine.nodes.process_nodes import NodeExecutionRequest, ProcessNodeExecutor
from backend.engine.pi.models_config import (
    PiModelsConfigError,
    stage_models_config,
    validate_models_config,
)
from backend.engine.process_runner import LineCallback, ProcessResult, ProcessRunner, ProcessSpec
from backend.schemas.pi import PiSettings
from backend.schemas.workflow import BashConfig, BashNode, PromptConfig, PromptNode
from backend.services.log_broadcaster import LogBroadcaster

CUSTOM_PROVIDER_CONFIG = json.dumps(
    {
        "providers": {
            "private-gateway": {
                "baseUrl": "https://llm.example.com/v1",
                "api": "openai-completions",
                "apiKey": "$CUSTOM_LLM_API_KEY",
                "models": [{"id": "example-chat-model"}],
            }
        }
    }
)


async def accept_models_config(_: Path) -> None:
    pass


class AgentDirectoryRunner(ProcessRunner):
    """Records the Pi agent directory contents before the attempt scratch is cleaned up."""

    def __init__(self) -> None:
        self.broadcaster = LogBroadcaster()
        self.agent_directory: Path | None = None
        self.staged_models: str | None = None
        self.staged_mode: int | None = None
        self.secret_values: list[str] = []

    async def execute(
        self,
        spec: ProcessSpec,
        *,
        secret_values: Sequence[str] = (),
        line_callback: LineCallback | None = None,
    ) -> ProcessResult:
        self.secret_values = list(secret_values)
        agent_directory = spec.environment.get("PI_CODING_AGENT_DIR")
        if agent_directory is not None:
            self.agent_directory = Path(agent_directory)
            models = self.agent_directory / "models.json"
            if models.is_file():
                self.staged_models = models.read_text(encoding="utf-8")
                self.staged_mode = stat.S_IMODE(models.stat().st_mode)
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


def request(tmp_path: Path, *, secrets: dict[str, str] | None = None) -> NodeExecutionRequest:
    worktree = tmp_path / "worktree"
    worktree.mkdir(exist_ok=True)
    return NodeExecutionRequest(
        run_id=uuid.uuid4(),
        node_execution_id=uuid.uuid4(),
        attempt_id=uuid.uuid4(),
        attempt_number=1,
        node_path="root/node",
        worktree=worktree,
        output_directory=tmp_path / "output",
        public_context={},
        secrets=secrets or {},
        default_timeout=60,
        max_preview_bytes=1024,
        pi=PiSettings(provider="private-gateway", model="example-chat-model"),
    )


def prompt_node() -> PromptNode:
    return PromptNode(
        type="prompt", id="prompt", label="Prompt", config=PromptConfig(prompt="Ship it")
    )


async def test_configured_models_file_is_staged_into_the_attempt_agent_directory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "models.json"
    source.write_text(CUSTOM_PROVIDER_CONFIG, encoding="utf-8")
    runner = AgentDirectoryRunner()

    await ProcessNodeExecutor(runner, source, accept_models_config).execute(
        prompt_node(),
        request(tmp_path, secrets={"CUSTOM_LLM_API_KEY": "custom-secret"}),
    )

    assert runner.staged_models == CUSTOM_PROVIDER_CONFIG
    assert runner.staged_mode == 0o600
    assert runner.secret_values == ["custom-secret"]
    assert runner.agent_directory is not None
    assert not runner.agent_directory.exists()


async def test_agent_directory_stays_empty_when_no_models_file_is_configured(
    tmp_path: Path,
) -> None:
    runner = AgentDirectoryRunner()

    await ProcessNodeExecutor(runner).execute(prompt_node(), request(tmp_path))

    assert runner.agent_directory is not None
    assert runner.staged_models is None


async def test_prompt_node_fails_when_the_configured_models_file_is_missing(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "absent" / "models.json"
    runner = AgentDirectoryRunner()

    with pytest.raises(PiModelsConfigError) as failure:
        await ProcessNodeExecutor(runner, missing).execute(prompt_node(), request(tmp_path))

    assert str(missing) in str(failure.value)
    assert runner.agent_directory is None


async def test_prompt_node_fails_when_a_referenced_credential_is_not_available(
    tmp_path: Path,
) -> None:
    source = tmp_path / "models.json"
    source.write_text(CUSTOM_PROVIDER_CONFIG, encoding="utf-8")
    runner = AgentDirectoryRunner()

    with pytest.raises(PiModelsConfigError, match="CUSTOM_LLM_API_KEY"):
        await ProcessNodeExecutor(runner, source).execute(prompt_node(), request(tmp_path))

    assert runner.agent_directory is None


async def test_prompt_node_does_not_start_for_an_invalid_builtin_override(
    tmp_path: Path,
) -> None:
    source = tmp_path / "models.json"
    source.write_text(json.dumps({"providers": {"openai": {"baseUrl": 123}}}), encoding="utf-8")
    runner = AgentDirectoryRunner()

    async def reject_models_config(_: Path) -> None:
        raise PiModelsConfigError("Pi rejected baseUrl")

    with pytest.raises(PiModelsConfigError, match="baseUrl"):
        await ProcessNodeExecutor(runner, source, reject_models_config).execute(
            prompt_node(), request(tmp_path)
        )

    assert runner.agent_directory is None
    assert runner.staged_models is None


async def test_bash_nodes_do_not_receive_the_models_file(tmp_path: Path) -> None:
    source = tmp_path / "models.json"
    source.write_text(CUSTOM_PROVIDER_CONFIG, encoding="utf-8")
    runner = AgentDirectoryRunner()

    await ProcessNodeExecutor(runner, source).execute(
        BashNode(type="bash", id="bash", label="Bash", config=BashConfig(command="pwd")),
        request(tmp_path),
    )

    assert runner.agent_directory is None
    assert runner.staged_models is None


def test_stage_models_config_rejects_malformed_json(tmp_path: Path) -> None:
    source = tmp_path / "models.json"
    source.write_text('{"providers": }', encoding="utf-8")
    agent_directory = tmp_path / "agent"
    agent_directory.mkdir()

    with pytest.raises(PiModelsConfigError, match="not valid JSON"):
        stage_models_config(agent_directory, source)

    assert not (agent_directory / "models.json").exists()


def test_stage_models_config_rejects_a_directory(tmp_path: Path) -> None:
    source = tmp_path / "models.json"
    source.mkdir()
    agent_directory = tmp_path / "agent"
    agent_directory.mkdir()

    with pytest.raises(PiModelsConfigError, match="Cannot read"):
        stage_models_config(agent_directory, source)


def test_stage_models_config_accepts_pi_comments_and_trailing_commas(tmp_path: Path) -> None:
    content = """{
      // Pi accepts line comments in models.json.
      "providers": {
        "custom": {
          "baseUrl": "https://llm.example.test/v1", // comments do not affect URLs
          "api": "openai-completions",
          "apiKey": "$CUSTOM_API_KEY",
          "models": [{"id": "model",}],
        },
      },
    }
    """
    source = tmp_path / "models.json"
    source.write_text(content, encoding="utf-8")
    agent_directory = tmp_path / "agent"
    agent_directory.mkdir()

    required = stage_models_config(agent_directory, source)

    assert required == frozenset({"CUSTOM_API_KEY"})
    assert (agent_directory / "models.json").read_text(encoding="utf-8") == content


@pytest.mark.parametrize(
    ("provider_fields", "message"),
    [
        ({"apiKey": "inline-secret"}, "inline secret"),
        ({"apiKey": "!security find-password"}, "execute a command"),
        ({"headers": {"Authorization": "Bearer inline-secret"}}, "inline secret"),
        ({"headers": {"X-Subscription-Key": "inline-secret"}}, "inline secret"),
        ({"headers": {"X-API-Key": "!fetch-key"}}, "execute a command"),
    ],
)
def test_stage_models_config_rejects_unredactable_auth_values(
    tmp_path: Path, provider_fields: dict[str, object], message: str
) -> None:
    source = tmp_path / "models.json"
    source.write_text(
        json.dumps(
            {
                "providers": {
                    "custom": {
                        "baseUrl": "https://llm.example.test/v1",
                        "api": "openai-completions",
                        "models": [{"id": "model"}],
                        **provider_fields,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    agent_directory = tmp_path / "agent"
    agent_directory.mkdir()

    with pytest.raises(PiModelsConfigError, match=message):
        stage_models_config(agent_directory, source)


def test_stage_models_config_collects_provider_and_model_header_credentials(
    tmp_path: Path,
) -> None:
    source = tmp_path / "models.json"
    source.write_text(
        json.dumps(
            {
                "providers": {
                    "custom": {
                        "baseUrl": "https://llm.example.test/v1",
                        "api": "openai-completions",
                        "apiKey": "prefix-${API_KEY}",
                        "headers": {"X-Tenant": "$TENANT_ID", "User-Agent": "Kyron"},
                        "models": [{"id": "model", "headers": {"X-Model-Token": "${MODEL_TOKEN}"}}],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    agent_directory = tmp_path / "agent"
    agent_directory.mkdir()

    required = stage_models_config(agent_directory, source)

    assert required == frozenset({"API_KEY", "TENANT_ID", "MODEL_TOKEN"})


def test_stage_models_config_accepts_a_builtin_base_url_override(tmp_path: Path) -> None:
    source = tmp_path / "models.json"
    content = json.dumps({"providers": {"openai": {"baseUrl": "https://proxy.test/v1"}}})
    source.write_text(content, encoding="utf-8")
    agent_directory = tmp_path / "agent"
    agent_directory.mkdir()

    required = stage_models_config(agent_directory, source)

    assert required == frozenset()
    assert (agent_directory / "models.json").read_text(encoding="utf-8") == content


@pytest.mark.parametrize("pi_error", [None, "Provider openai: invalid baseUrl"])
async def test_validate_models_config_uses_the_installed_pi_runtime(
    tmp_path: Path, pi_error: str | None
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")
    package = tmp_path / "pi-package"
    dist = package / "dist"
    dist.mkdir(parents=True)
    (package / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    pi_entry = dist / "cli.js"
    pi_entry.write_text("", encoding="utf-8")
    (dist / "index.js").write_text(
        """
export class ModelRuntime {
  static async create(options) {
    if (options.allowModelNetwork !== false || !options.modelsPath.endsWith("models.json")) {
      throw new Error("unsafe validation options");
    }
    return new ModelRuntime();
  }
  getError() { return ERROR; }
}
""".replace("ERROR", json.dumps(pi_error)),
        encoding="utf-8",
    )
    agent_directory = tmp_path / "agent"
    agent_directory.mkdir()
    (agent_directory / "models.json").write_text("{}", encoding="utf-8")

    if pi_error is None:
        await validate_models_config(
            agent_directory,
            pi_executable=pi_entry,
            node_executable=Path(node),
        )
    else:
        with pytest.raises(PiModelsConfigError, match="invalid baseUrl"):
            await validate_models_config(
                agent_directory,
                pi_executable=pi_entry,
                node_executable=Path(node),
            )
