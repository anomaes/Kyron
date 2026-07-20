---
layout: home

hero:
  name: Kyron
  text: Deterministic AI-assisted delivery
  tagline: Build reviewable coding workflows as versioned graphs, run them against an exact Git commit, and recover every execution without losing its history.
  actions:
    - theme: brand
      text: Get started
      link: /getting-started/
    - theme: alt
      text: Author a workflow
      link: /workflows/
    - theme: alt
      text: Deploy Kyron
      link: /deployment/

features:
  - icon: SHA
    title: Exact-commit execution
    details: The root workflow and every child definition are resolved from one Git SHA and stored as an immutable run snapshot.
  - icon: DAG
    title: Composable workflow graphs
    details: Combine Bash, Python, coding-agent prompts, feedback checkpoints, child workflows, conditions, and bounded review loops.
  - icon: ↻
    title: Recoverable waves
    details: Parallel nodes execute as a checkpointed wave. A failure resets the entire wave and creates fresh attempts when you resume.
  - icon: CR
    title: Git-native human control
    details: GitLab merge requests and GitHub pull requests carry review, feedback, delivery, and cleanup through the same provider-neutral model.
  - icon: LOG
    title: Durable observability
    details: Runs preserve invocations, waves, attempts, edge decisions, engine events, process output, and checkpoint history.
  - icon: KEY
    title: Secret-aware execution
    details: Credentials stay encrypted at rest, are decrypted only for the operation that needs them, and never enter workflow snapshots or logs.
---

## Choose your path

| I want to… | Start here |
| --- | --- |
| Understand Kyron before installing it | [Read the core concepts](/getting-started/concepts) |
| Bring up a local or production instance | [Follow the quick start](/getting-started/quick-start) |
| Build a workflow in the UI | [Use the visual workflow builder](/guides/workflow-builder) |
| Author workflow JSON directly | [Learn the workflow language](/workflows/) |
| Add approval or revision cycles | [Design a review loop](/workflows/review-loops) |
| Diagnose or recover a failed run | [Use the recovery guide](/guides/recovery) |
| Operate Kyron on a VM | [Open the deployment guide](/deployment/) |
| Integrate through HTTP or WebSocket | [Use the API reference](/api) |

::: warning Trusted internal execution
Kyron is an orchestration engine, not a sandbox. Bash, Python, and Pi prompt nodes execute directly in the backend environment. Only trusted users should author workflows or register repositories.
:::

## The execution model in one minute

1. An engineer triggers a merged workflow from a registered repository.
2. Kyron resolves the selected base ref to an exact commit and snapshots the complete workflow bundle from that revision.
3. One isolated branch and worktree are created for the run.
4. Ready process nodes execute in deterministic waves; each successful wave becomes a Git checkpoint.
5. Feedback and review-loop nodes pause behind a snapshotted project approval policy.
6. Kyron pushes the finished branch and preserves enough state to inspect, resume, or clean up the run later.

[Learn why these rules matter →](/getting-started/concepts)
