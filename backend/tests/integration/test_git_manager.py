from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from backend.integrations.git_manager import GitError, GitManager


async def git(*args: str, cwd: Path) -> str:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        raise RuntimeError(stderr.decode())
    return stdout.decode().strip()


async def test_exact_sha_resolution_and_show_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    remote = tmp_path / "remote.git"
    clones = tmp_path / "clones"
    source.mkdir()
    await git("init", "-b", "main", cwd=source)
    await git("config", "user.email", "test@example.com", cwd=source)
    await git("config", "user.name", "Test", cwd=source)
    (source / "README.md").write_text("pinned content\n")
    await git("add", "README.md", cwd=source)
    await git("commit", "-m", "initial", cwd=source)
    await git("clone", "--bare", str(source), str(remote), cwd=tmp_path)

    manager = GitManager(clones)
    clone = clones / "project"
    await manager.clone(remote.as_uri(), clone, "unused-local-token")
    sha = await manager.resolve_remote_sha(clone, "main")
    assert sha == await git("rev-parse", "HEAD", cwd=source)
    assert await manager.show_file(clone, sha, "README.md") == "pinned content"


async def test_repository_path_escape_is_rejected(tmp_path: Path) -> None:
    manager = GitManager(tmp_path / "clones")
    with pytest.raises(GitError, match="outside"):
        manager.assert_beneath(tmp_path / "elsewhere", manager.clone_base_path)


async def test_worktree_checkpoint_and_failed_wave_reset(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    worktrees = tmp_path / "worktrees"
    run_data = tmp_path / "run-data"
    repository.mkdir()
    await git("init", "-b", "main", cwd=repository)
    await git("config", "user.email", "test@example.com", cwd=repository)
    await git("config", "user.name", "Test", cwd=repository)
    (repository / "tracked.txt").write_text("base\n")
    await git("add", "tracked.txt", cwd=repository)
    await git("commit", "-m", "base", cwd=repository)
    base_sha = await git("rev-parse", "HEAD", cwd=repository)
    await git("branch", "workflow_definition/local_test", base_sha, cwd=repository)

    manager = GitManager(tmp_path / "clones", worktrees, run_data)
    run_id = __import__("uuid").uuid4()
    branch, worktree, data_path = await manager.create_run_worktree(
        repository, run_id, "root", base_sha
    )
    assert branch.startswith("workflow/root_")
    assert data_path.exists()
    assert not await git("branch", "--list", "workflow_definition/local_test", cwd=repository)
    await manager.ensure_clean(worktree)
    (worktree / "tracked.txt").write_text("wave one\n")
    checkpoint = await manager.checkpoint(worktree, "wave 1")
    assert checkpoint != base_sha
    (worktree / "tracked.txt").write_text("failed wave\n")
    (worktree / "untracked.txt").write_text("remove me")
    await manager.reset_wave(worktree, checkpoint)
    assert (worktree / "tracked.txt").read_text() == "wave one\n"
    assert not (worktree / "untracked.txt").exists()
    await manager.remove_worktree(repository, worktree, branch)
    assert not worktree.exists()


async def test_worktree_removal_failure_is_not_ignored(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    worktrees = tmp_path / "worktrees"
    repository.mkdir()
    worktrees.mkdir()
    await git("init", "-b", "main", cwd=repository)
    unregistered = worktrees / "unregistered"
    unregistered.mkdir()
    manager = GitManager(tmp_path / "clones", worktrees, tmp_path / "run-data")

    with pytest.raises(GitError, match="Git operation failed"):
        await manager.remove_worktree(repository, unregistered)

    assert unregistered.exists()


async def test_isolated_children_integrate_atomically_in_requested_order(
    tmp_path: Path,
) -> None:
    clones = tmp_path / "clones"
    repository = clones / "repository"
    worktrees = tmp_path / "worktrees"
    repository.mkdir(parents=True)
    await git("init", "-b", "main", cwd=repository)
    await git("config", "user.email", "test@example.com", cwd=repository)
    await git("config", "user.name", "Test", cwd=repository)
    (repository / "base.txt").write_text("base\n")
    await git("add", "base.txt", cwd=repository)
    await git("commit", "-m", "base", cwd=repository)
    base_sha = await git("rev-parse", "HEAD", cwd=repository)

    manager = GitManager(clones, worktrees, tmp_path / "run-data")
    run_id = uuid.uuid4()
    parent_branch, parent, _ = await manager.create_run_worktree(
        repository, run_id, "root", base_sha
    )
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    first_branch, first = await manager.create_invocation_worktree(
        repository, run_id, first_id, "a", base_sha
    )
    second_branch, second = await manager.create_invocation_worktree(
        repository, run_id, second_id, "b", base_sha
    )
    (first / "a.txt").write_text("a\n")
    first_head = await manager.checkpoint(first, "child a")
    (second / "b.txt").write_text("b\n")
    second_head = await manager.checkpoint(second, "child b")

    integrated = await manager.integrate_heads(
        parent, base_sha, [first_head, second_head]
    )

    assert integrated == await manager.head_sha(parent)
    assert (parent / "a.txt").read_text() == "a\n"
    assert (parent / "b.txt").read_text() == "b\n"
    subjects = await git("log", "--format=%s", "-2", cwd=parent)
    assert subjects.splitlines() == [
        "Merge commit '" + second_head + "' into " + parent_branch,
        "Merge commit '" + first_head + "' into " + parent_branch,
    ]
    for path, branch in (
        (first, first_branch),
        (second, second_branch),
        (parent, parent_branch),
    ):
        await manager.remove_worktree(repository, path, branch)


async def test_isolated_integration_conflict_restores_exact_parent(
    tmp_path: Path,
) -> None:
    clones = tmp_path / "clones"
    repository = clones / "repository"
    worktrees = tmp_path / "worktrees"
    repository.mkdir(parents=True)
    await git("init", "-b", "main", cwd=repository)
    await git("config", "user.email", "test@example.com", cwd=repository)
    await git("config", "user.name", "Test", cwd=repository)
    (repository / "shared.txt").write_text("base\n")
    await git("add", "shared.txt", cwd=repository)
    await git("commit", "-m", "base", cwd=repository)
    base_sha = await git("rev-parse", "HEAD", cwd=repository)
    manager = GitManager(clones, worktrees, tmp_path / "run-data")
    run_id = uuid.uuid4()
    parent_branch, parent, _ = await manager.create_run_worktree(
        repository, run_id, "root", base_sha
    )
    children: list[tuple[Path, str, str]] = []
    for node_id, content in (("a", "first\n"), ("b", "second\n")):
        branch, child = await manager.create_invocation_worktree(
            repository, run_id, uuid.uuid4(), node_id, base_sha
        )
        (child / "shared.txt").write_text(content)
        head = await manager.checkpoint(child, node_id)
        children.append((child, branch, head))

    with pytest.raises(GitError):
        await manager.integrate_heads(
            parent, base_sha, [children[0][2], children[1][2]]
        )

    assert await manager.head_sha(parent) == base_sha
    assert (parent / "shared.txt").read_text() == "base\n"
    for child, branch, _ in children:
        await manager.remove_worktree(repository, child, branch)
    await manager.remove_worktree(repository, parent, parent_branch)
