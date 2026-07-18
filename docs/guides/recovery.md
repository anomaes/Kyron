---
title: Failure and recovery
description: Understand wave rollback, resume, interruption, and operator recovery.
---

# Failure and recovery

Kyron's recovery guarantee is built around Git checkpoints and immutable attempts. The goal is not to hide failure; it is to make the exact failed work and the exact retry visible.

## What happens when a node fails

For a required process node in a wave, Kyron:

1. records the failed attempt and its output paths;
2. cancels any still-running siblings in the same wave;
3. resets the worktree to the wave's recorded start commit;
4. marks the wave and run failed; and
5. leaves all historical rows intact.

A node with `allow_failure: true` records its failure but does not fail the wave. Use that option only when downstream semantics genuinely tolerate the failure.

## Resume a failed run

Before selecting **Resume**, determine whether the underlying cause has changed. Examples include a restored external service, corrected repository code on the pinned base, replaced credential, or deliberately increased resource availability.

Resume restores the failed wave boundary and creates a fresh attempt for **every node in that wave**. It does not retry only the visibly failed sibling, because the successful siblings' filesystem changes were rolled back with the wave.

::: info A base ref does not move an existing run
Updating `main` does not change the run's `base_commit_sha` or snapshot. If the fix must come from a new commit, start a new run against that commit instead of resuming.
:::

## Interrupted runs

At startup, reconciliation classifies in-flight process work as interrupted while preserving feedback waits. No process is assumed to have survived backend ownership loss.

Inspect the run, wave boundary, worktree, and last durable engine event. Resume only after the environment is stable. A normal restart should still have exactly one backend worker.

## Worktree recovery failure

`WORKTREE_RECOVERY_FAILED` means Kyron could not restore the stored wave start SHA safely. Do not force the state forward.

1. Stop scheduling that run.
2. Inspect the run's stored worktree and wave start commit under the configured roots.
3. Verify the path belongs to the run and contains no unrelated work.
4. Repair the Git state without changing the run snapshot.
5. Resume through Kyron so new attempts are recorded.

## Approval reset failure

Kyron must consume intermediate approval before continuing. If provider permissions prevent that operation, repair the project token or bot/app authority and retry the checkpoint. Never bypass the reset by mutating database state.

## Stuck processes

Request cancellation through Kyron first. The process runner owns process groups and performs a bounded `SIGTERM` → `SIGKILL` escalation. Host-level termination is a last resort because it cannot record the same execution intent.

## Recovery decision table

| Situation | Resume the same run? |
| --- | --- |
| Temporary network or provider outage | Yes, after service recovery |
| Credential was rotated | Yes, after replacing the credential |
| Workflow definition itself is wrong | Usually no; merge a corrected definition and start a new run |
| Base repository code needs a new commit | No; start a new run from that commit |
| Backend restarted during a process wave | Yes, after inspecting interrupted state |
| Worktree cannot be restored to wave start | Not until operator repair succeeds |
| User cancelled intentionally | No automatic resume; normally start a new run |

For incident procedures and backup/restore behavior, use the [operations runbook](/operations).
