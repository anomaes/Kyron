---
title: Run states
description: Durable lifecycle states and valid operator actions in Kyron.
---

# Run states

Kyron stores state at several levels. A run status is the operator-facing summary; invocations, waves, executions, and attempts explain how it reached that status.

## Run lifecycle

| State | Meaning | Typical next action |
| --- | --- | --- |
| `queued` | Snapshot exists and run awaits coordinator ownership | Automatic scheduling |
| `running` | Engine is scheduling or executing work | Observe or cancel |
| `awaiting_feedback` | Active human or review-loop checkpoint | Eligible reviewers satisfy the policy quorum or give feedback |
| `failed` | Required work or a control transition failed | Diagnose, then resume when safe |
| `interrupted` | Active engine ownership was lost through restart or worker crash | Inspect, then explicitly resume |
| `completed` | Workflow execution and finalization succeeded | Review and merge the change request |
| `cancelled` | User cancellation stopped active work at a retained checkpoint | Resume explicitly or start a new run |

State-changing API calls validate the current state. A stale or invalid transition returns HTTP 409 rather than silently doing nothing.

## Wave lifecycle

A process wave records its index, start commit, execution membership, completion state, and successful checkpoint commit when applicable.

| Outcome | Result |
| --- | --- |
| Every required member succeeds | Combined worktree changes are committed and scheduling continues |
| Required member fails | Siblings are cancelled, worktree resets to start SHA, run fails |
| Only `allow_failure` members fail | Failure remains visible but the wave may succeed |
| Backend ownership is lost | In-flight work is classified as interrupted during startup recovery |

Resume creates fresh attempts for all nodes in the failed wave.

## Node execution and attempt states

A node execution is stable across retry. An attempt is immutable evidence of one try. Output paths, timestamps, exit information, and error details belong to the attempt.

This distinction lets the UI show:

- attempt 1 failed after producing output;
- the wave rolled back;
- attempt 2 started from the same boundary; and
- attempt 2 succeeded.

Historical attempts are never rewritten to look successful.

## Skipped nodes

A node becomes skipped when its incoming edge decisions and join mode prove that it cannot become ready. Skipping is a graph result, not a process failure. `settings.propagate_skips` affects how downstream skip state is resolved.

## Feedback lifecycle

At a checkpoint, feedback is accepted only when:

- the run is waiting at the matching execution;
- the actor is an eligible provider identity in the active gate snapshot;
- the event type is allowed by node configuration;
- the provider delivery has not already been consumed; and
- intermediate approval can be reset/dismissed when required.

The feedback event is persisted before scheduling continues.

## Cancellation

Cancellation is run-wide. Kyron cancels the registered task and active process groups, using a
grace period before force termination. It never resumes automatically, but an authorized operator
may explicitly resume while the safe worktree checkpoint is still retained.

## Cleanup lifecycle

Run worktrees and local branches remain while an associated change request is open. Merge/close webhooks initiate validated cleanup. Periodic reconciliation repairs missed webhook cleanup and reports orphans before removal. Output-file retention operates independently from database execution history.

For operational decisions, use [failure and recovery](/guides/recovery).
