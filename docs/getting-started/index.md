---
title: Welcome to Kyron
description: What Kyron is, who it is for, and how to find your way around it.
---

# Welcome to Kyron

Kyron is a self-hosted workflow engine for **reviewable, recoverable AI-assisted software delivery**. It lets an internal engineering team turn recurring delivery practices—implementation, testing, review, revision, and approval—into versioned workflow graphs that run against Git repositories.

Kyron is a good fit when you want coding agents to make real repository changes but still need exact inputs, Git history, human checkpoints, and an audit trail.

## What makes Kyron different

### A run starts from an exact commit

A user chooses a workflow and base ref, but Kyron does not keep following that moving branch. It resolves the ref to a 40-character commit SHA, loads the root workflow and every transitive child from that same SHA, and stores the resulting workflow bundle with the run.

That gives you a stable answer to: *What instructions did this run execute?*

### Parallel work is transactional at the wave boundary

Nodes that are ready together form an execution wave. They may run concurrently in the same worktree. Kyron records the worktree's starting commit before the wave begins and commits the combined result only when every required node succeeds.

If one required node fails, the entire wave is reset. Resuming creates new attempt rows and replays the wave from its recorded boundary.

### Human review is part of the state machine

`human_feedback` and `review_loop` nodes create or update a GitLab merge request or GitHub pull request and pause the run. Only the provider identity that triggered the run may control its checkpoint. An intermediate provider approval is consumed before execution continues, so it cannot accidentally count as final delivery approval.

## What Kyron is not

- It is **not a sandbox**. Workflow processes run in the backend container with access to the run worktree.
- It is **not a multi-tenant SaaS boundary**. The trust model assumes authenticated internal users and explicitly registered repositories.
- It is **not a general cyclic workflow engine**. Ordinary graphs must be acyclic; bounded repetition belongs in a `review_loop` node.
- It is **not a distributed worker system**. Production runs exactly one backend worker.

## How to use these docs

| If you are… | Recommended path |
| --- | --- |
| Evaluating Kyron | [Core concepts](/getting-started/concepts) → [Architecture](/architecture) → [Security model](/deployment/security) |
| Trying Kyron locally | [Quick start](/getting-started/quick-start) → [Your first workflow](/getting-started/first-workflow) |
| A workflow author | [Workflow overview](/workflows/) → [Node types](/workflows/node-types) → [Example library](/workflows/examples) |
| An operator | [Production deployment](/deployment/) → [Configuration](/deployment/configuration) → [Operations runbook](/operations) |
| Building an integration | [API guide](/api) → [Run states](/reference/states) → [Variables](/reference/variables) |
| Contributing code | [Developer guide](/contributing/) → [Architecture](/architecture) → [Decision log](/decisions) |

## The shortest useful path

If you want to see the product working, allow roughly 15 minutes:

1. [Start the local stack](/getting-started/quick-start).
2. Register a trusted test repository.
3. Add the [first workflow](/getting-started/first-workflow) to its default branch.
4. Trigger the workflow with a small task.
5. Open the run detail and follow its wave, Git checkpoint, and output.

::: tip Keep the first run boring
Use a disposable repository and a workflow that writes a small file, runs one test command, and stops. Add prompts, branching, and review only after the basic provider and worktree path is proven.
:::
