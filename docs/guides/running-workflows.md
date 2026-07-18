---
title: Run workflows
description: Trigger, observe, cancel, and inspect Kyron runs.
---

# Run workflows

Only merged definitions from the project's current default-branch revision appear in the workflow catalog. A run may target another base ref, but that ref must contain the selected root workflow and its complete child graph.

## Trigger a run

From the workflow catalog:

1. select **Run**;
2. choose a branch, tag, or commit-like base ref;
3. enter every required workflow input; and
4. confirm the run.

Kyron type-checks inputs, rejects unknown names, fetches the project, resolves the base ref to an exact SHA, snapshots the workflow bundle from that SHA, and then queues the run.

The requested ref is useful context; `base_commit_sha` is the reproducibility boundary.

## Read the run list

![Kyron run history showing multiple durable states](/assets/screenshots/runs.png)

Run history can be filtered by project, root workflow, status, triggering user, and time range. Each row identifies the active execution, immutable base revision, and provider change request when one exists.

## Follow a run

![Expanded run graph and live output on run detail](/assets/screenshots/run-detail.png)

Run detail combines four related views:

- **Graph** — the root and every child invocation, including review iterations;
- **Waves** — checkpoint boundaries and their start/end commits;
- **Attempts** — immutable tries, exit state, timestamps, and output paths;
- **Logs** — durable engine events followed by live process events.

The log WebSocket accepts `after_id`. On reconnect, the server first replays durable engine logs with larger sequence IDs and then switches to live delivery. Raw process output is live-only in the socket, but complete attempt files remain available through the output endpoint until retention cleanup.

## Interpret common outcomes

| Outcome | What to do |
| --- | --- |
| `awaiting_feedback` | The triggering provider user should approve or comment at the active checkpoint. |
| `failed` | Inspect the failed wave and attempt, correct the cause, then resume if safe. |
| `interrupted` | The backend restarted or lost ownership; inspect and explicitly resume. |
| `completed` | Review the final branch/change request and obtain fresh provider approval before merge. |
| `cancelled` | No automatic continuation occurs. Start a new run if work should be retried. |

## Cancel safely

Use **Cancel run** or `POST /api/runs/{run_id}/cancel`. Kyron cancels the registered task and terminates active subprocess groups, escalating from `SIGTERM` to `SIGKILL` after the configured grace period.

Prefer this path to killing a container or process manually. It records intent and gives the engine a chance to leave durable state consistent.

## Retrieve node output

The node output API selects an attempt and one stream: `stdout`, `stderr`, or `pi_events`. `tail_lines` bounds large reads. Paths are derived from durable node metadata and revalidated against the configured run-data root; callers cannot supply arbitrary filesystem paths.

For the exact routes and status codes, use the [API guide](/api).
