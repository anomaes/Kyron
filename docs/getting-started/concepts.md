---
title: Core concepts
description: The vocabulary and invariants behind Kyron runs.
---

# Core concepts

Kyron's behavior becomes much easier to predict once you separate the **workflow definition**, **run snapshot**, and **execution history**.

## Project

A project is a registered GitLab or GitHub repository. It stores provider-neutral repository metadata, an encrypted project access token, and optional Pi defaults for prompt nodes. The token performs Git and provider API operations; the signed-in user's provider identity determines who may trigger and control a run.

Project and browser providers must match for mutations. A GitHub session cannot trigger a GitLab project, even if both accounts share the same email address.

## Workflow definition

A workflow is strict JSON stored at `.workflowEngine/<id>.json` in the project repository. It declares:

- typed inputs and public variables;
- declared outputs;
- nodes and directed edges;
- graph and checkpoint settings; and
- catalog metadata such as name, description, and tags.

The filename stem and root `id` must match. Unknown fields are rejected, and ordinary graphs must be directed and acyclic.

## Run and workflow bundle

A run is one execution of a root workflow against a selected base ref. Before queueing it, Kyron fetches the repository, resolves the ref to an exact commit, recursively loads every referenced child workflow from that commit, validates the complete reference graph, and stores the immutable bundle.

Later changes to the branch or workflow files do not change an existing run.

## Invocation

An invocation is one runtime instance of one workflow definition. The root run has a root invocation. A `subworkflow` node creates a child invocation, and each `review_loop` iteration creates an invocation for the initial or revision workflow.

Invocations have stable paths such as `root/quality_checks` and carry their own public context and output mapping.

## Node execution and attempt

A node execution represents a node within an invocation. An attempt represents one actual try to execute it. Resuming a failed wave does not rewrite the failed attempt; it creates a new one. This preserves both the failure and the recovery.

## Edge evaluation and joins

Edges become eligible only after their source node reaches a terminal state. An optional condition is evaluated once and stored. The target node then applies its join mode:

- `and`: every incoming edge must be satisfied;
- `or`: at least one incoming edge must be satisfied.

Unsatisfied branches may cause downstream nodes to be skipped. See [edges, conditions, and joins](/workflows/edges-and-joins).

## Wave

A wave is a set of ready process nodes—Bash, Script, or Prompt—that may run concurrently. Kyron records the wave's starting Git commit.

- On success, outputs enter public context and the combined worktree state is committed.
- On required failure, running siblings are cancelled and the worktree is reset to the wave start.
- On resume, every node in the failed wave receives a fresh attempt.

Control nodes such as feedback, child workflows, and review loops are serialized outside process waves.

## Public context and secret environment

Kyron deliberately maintains two separate data planes:

| Context | May be persisted? | How it is referenced |
| --- | ---: | --- |
| Inputs, variables, built-ins, node outputs | Yes | `${NAME}` templates |
| Credentials and project tokens | No plaintext | Native subprocess environment variables such as `$NPM_TOKEN` |

Secrets are never valid `${...}` template variables. They are decrypted just in time, added to an in-memory redactor, and removed after the operation.

## Human checkpoint

A human checkpoint pauses execution while a change request is ready for the identities
selected by its reusable project approval policy. Decisions can enter through Kyron or an
authenticated provider webhook. Events are deduplicated, eligibility and quorum are
verified, intermediate approvals are consumed when the gate resolves, and the run continues
from durable state.

## Change request

“Change request” is Kyron's provider-neutral term for a GitLab merge request or GitHub pull request. A run has at most one active delivery change request; checkpoints update and reuse it.

## Why production uses one worker

The coordinator, task registry, process registry, and live log broadcaster are in-process components. Durable state makes a run recoverable after restart, but the current release does not implement cross-worker ownership or distributed locking. Running more than one backend worker can schedule the same work twice.

::: warning Non-negotiable
Production runs exactly one backend container and one Uvicorn worker.
:::
