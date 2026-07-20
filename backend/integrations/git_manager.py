from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from backend.integrations.git_credentials import temporary_git_askpass
from backend.services.crypto import SecretRedactor


class GitError(RuntimeError):
    pass


class ProjectGitLocks:
    def __init__(self) -> None:
        self._locks: defaultdict[uuid.UUID, asyncio.Lock] = defaultdict(asyncio.Lock)

    def for_project(self, project_id: uuid.UUID) -> asyncio.Lock:
        return self._locks[project_id]


project_git_locks = ProjectGitLocks()


class GitManager:
    def __init__(
        self,
        clone_base_path: Path,
        worktree_base_path: Path | None = None,
        run_data_base_path: Path | None = None,
    ) -> None:
        self.clone_base_path = clone_base_path
        self.worktree_base_path = worktree_base_path or clone_base_path.parent / "worktrees"
        self.run_data_base_path = run_data_base_path or clone_base_path.parent / "run_data"

    async def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env_patch: dict[str, str] | None = None,
        redactor: SecretRedactor | None = None,
        check: bool = True,
    ) -> str:
        env = self._base_environment()
        env.update(env_patch or {})
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        output = stdout.decode("utf-8", errors="replace")
        error = stderr.decode("utf-8", errors="replace")
        if redactor:
            output = redactor.redact(output)
            error = redactor.redact(error)
        if check and process.returncode:
            raise GitError(f"Git operation failed ({process.returncode}): {error.strip()}")
        return output.strip()

    async def clone(
        self, git_url: str, destination: Path, token: str, *, username: str = "oauth2"
    ) -> None:
        self.clone_base_path.mkdir(parents=True, exist_ok=True)
        self.assert_beneath(destination, self.clone_base_path)
        if await asyncio.to_thread(destination.exists):
            raise GitError("Project clone destination already exists")
        redactor = SecretRedactor([token])
        try:
            with temporary_git_askpass(username, token) as credentials:
                await self.run(
                    ["clone", "--no-checkout", "--", git_url, str(destination)],
                    env_patch=credentials,
                    redactor=redactor,
                )
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        finally:
            redactor.clear()

    async def fetch(
        self, local_path: Path, token: str, *, username: str = "oauth2"
    ) -> None:
        self.assert_beneath(local_path, self.clone_base_path)
        redactor = SecretRedactor([token])
        try:
            with temporary_git_askpass(username, token) as credentials:
                await self.run(
                    ["fetch", "origin", "--prune"],
                    cwd=local_path,
                    env_patch=credentials,
                    redactor=redactor,
                )
        finally:
            redactor.clear()

    async def resolve_remote_sha(self, local_path: Path, base_ref: str) -> str:
        sha = await self.run(["rev-parse", f"origin/{base_ref}"], cwd=local_path)
        if len(sha) != 40 or any(character not in "0123456789abcdef" for character in sha):
            raise GitError("Git did not return a full commit SHA")
        return sha

    async def show_file(self, local_path: Path, commit_sha: str, path: str) -> str:
        if not path or path.startswith("/") or ".." in Path(path).parts:
            raise GitError("Repository file path is unsafe")
        return await self.run(["show", f"{commit_sha}:{path}"], cwd=local_path)

    async def list_files(self, local_path: Path, commit_sha: str, prefix: str) -> list[str]:
        output = await self.run(
            ["ls-tree", "-r", "--name-only", commit_sha, "--", prefix], cwd=local_path
        )
        return [line for line in output.splitlines() if line]

    async def create_run_worktree(
        self,
        repository_path: Path,
        run_id: uuid.UUID,
        workflow_id: str,
        base_commit_sha: str,
    ) -> tuple[str, Path, Path]:
        safe_workflow_id = "".join(
            character if character.isalnum() or character == "_" else "_"
            for character in workflow_id
        )
        branch = f"workflow/{safe_workflow_id}_{run_id.hex[:8]}"
        worktree = self.worktree_base_path / str(run_id)
        run_data = self.run_data_base_path / str(run_id)
        self.assert_beneath(worktree, self.worktree_base_path)
        self.assert_beneath(run_data, self.run_data_base_path)
        self.worktree_base_path.mkdir(parents=True, exist_ok=True)
        run_data.mkdir(parents=True, exist_ok=False)
        local_ref = await self.run(
            ["show-ref", "--verify", f"refs/heads/{branch}"],
            cwd=repository_path,
            check=False,
        )
        remote_ref = await self.run(
            ["show-ref", "--verify", f"refs/remotes/origin/{branch}"],
            cwd=repository_path,
            check=False,
        )
        if local_ref or remote_ref:
            shutil.rmtree(run_data, ignore_errors=True)
            raise GitError(f"Run branch '{branch}' already exists")
        try:
            await self.run(
                ["worktree", "add", "-b", branch, str(worktree), base_commit_sha],
                cwd=repository_path,
            )
            await self.run(["config", "user.name", "Workflow Engine"], cwd=worktree)
            await self.run(["config", "user.email", "workflow-engine@noreply.local"], cwd=worktree)
            snapshot_refs = await self.run(
                [
                    "for-each-ref",
                    "--format=%(refname:short)",
                    "--points-at",
                    base_commit_sha,
                    "refs/heads/workflow_definition",
                ],
                cwd=repository_path,
            )
            for snapshot_ref in snapshot_refs.splitlines():
                if snapshot_ref.startswith("workflow_definition/local_"):
                    await self.run(["branch", "-D", snapshot_ref], cwd=repository_path)
        except Exception:
            shutil.rmtree(run_data, ignore_errors=True)
            raise
        return branch, worktree, run_data

    async def head_sha(self, worktree: Path) -> str:
        return await self.run(["rev-parse", "HEAD"], cwd=worktree)

    async def ensure_clean(self, worktree: Path) -> None:
        status = await self.run(["status", "--porcelain"], cwd=worktree)
        if status:
            raise GitError("Worktree is not clean at wave start")

    async def checkpoint(self, worktree: Path, message: str) -> str:
        await self.run(["add", "-A"], cwd=worktree)
        staged = await self.run(["diff", "--cached", "--name-only"], cwd=worktree)
        if staged:
            await self.run(["commit", "-m", message], cwd=worktree)
        return await self.head_sha(worktree)

    async def reset_wave(self, worktree: Path, start_commit_sha: str) -> None:
        await self.run(["reset", "--hard", start_commit_sha], cwd=worktree)
        await self.run(["clean", "-fd"], cwd=worktree)
        if await self.head_sha(worktree) != start_commit_sha:
            raise GitError("Worktree recovery did not restore the wave start commit")

    async def push(
        self,
        worktree: Path,
        branch: str,
        token: str,
        *,
        username: str = "oauth2",
        force_with_lease: bool = False,
    ) -> None:
        redactor = SecretRedactor([token])
        try:
            with temporary_git_askpass(username, token) as credentials:
                args = ["push"]
                if force_with_lease:
                    args.append("--force-with-lease")
                args.extend(["origin", branch])
                await self.run(
                    args,
                    cwd=worktree,
                    env_patch=credentials,
                    redactor=redactor,
                )
        finally:
            redactor.clear()

    async def remove_worktree(
        self, repository_path: Path, worktree: Path, branch: str | None = None
    ) -> None:
        self.assert_beneath(worktree, self.worktree_base_path)
        await self.run(
            ["worktree", "remove", "--force", str(worktree)],
            cwd=repository_path,
            check=False,
        )
        await self.run(["worktree", "prune"], cwd=repository_path)
        if branch:
            await self.run(["branch", "-D", branch], cwd=repository_path, check=False)

    @staticmethod
    def assert_beneath(path: Path, root: Path) -> Path:
        resolved_root = root.resolve()
        resolved = path.resolve()
        if not resolved.is_relative_to(resolved_root) or resolved == resolved_root:
            raise GitError(f"Path is outside the configured root: {path}")
        return resolved

    @staticmethod
    def _base_environment() -> dict[str, str]:
        allowed = ("PATH", "LANG", "LC_ALL", "HOME", "TMPDIR", "SSH_AUTH_SOCK")
        return {key: value for key in allowed if (value := os.environ.get(key)) is not None}
