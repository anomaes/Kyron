---
title: Runtime sequences
description: Dynamic views of run initialization, node execution, feedback checkpoints, and interruption recovery.
---

# Runtime sequences

C4 views describe stable structure. These sequences show when ownership and data change during the workflows most relevant to correctness and operations.

## Queue and initialize a run

```mermaid
sequenceDiagram
    actor User
    participant API as Workflow/run API
    participant Host as Code-host adapter
    participant Git as Git manager/local clone
    participant DB as PostgreSQL
    participant Runtime as Engine runtime
    participant Coord as Run coordinator
    participant FS as Managed filesystem

    User->>API: Request run for project, workflow and base ref
    opt change-request subject
        API->>Host: Resolve source branch and expected head commit
        Host-->>API: Normalized change-request metadata
    end
    API->>Git: Fetch repository refs with ephemeral credentials
    Git-->>API: Resolve exact code-subject commit
    API->>Git: Read root and transitive workflows with git show
    API->>API: Validate DAGs, composition and credential policy
    API->>DB: Insert QUEUED run with immutable snapshots
    API->>Runtime: Schedule run ID
    API-->>User: Run representation

    Runtime->>Coord: Execute owned run task
    Coord->>DB: QUEUED → RUNNING with expected status version
    Coord->>Git: Create root branch/worktree at exact commit
    Git->>FS: Materialize worktree and run-data directory
    Coord->>DB: Persist root invocation and workspace
    Coord->>Coord: Reconstruct graph and schedule ready nodes
```

The code subject and workflow-bundle revision are independent pins. Delivery runs normally select the same commit for both. Report-only runs can inspect an untrusted source commit while executing workflow definitions and credential policy from a trusted revision.

Run initialization uses a versioned durable transition before creating workspaces. If another owner already changed the row, initialization stops instead of duplicating execution.

## Execute one process-node attempt

```mermaid
sequenceDiagram
    participant Wave as Wave executor
    participant DB as PostgreSQL
    participant Crypto as Credential service/cipher
    participant Node as Process-node executor
    participant Pi as Pi config and Bubblewrap
    participant Runner as Process runner
    participant Child as Bash, Script or Pi
    participant Files as Attempt output

    Wave->>DB: Insert wave, node execution and fresh attempt
    Wave->>Crypto: Load credentials allowed by run policy snapshot
    Crypto->>DB: Read triggering user's encrypted values
    Crypto-->>Wave: Selected plaintext dictionary
    Wave->>Node: Node request, public context, secrets and paths
    Node->>Node: Build sanitized environment + public context + secrets

    opt Prompt node
        Node->>Pi: Create scratch/agent/cache/tmp directories
        Pi->>Pi: Stage snapshotted, secret-free models.json
        Pi->>Pi: Verify every credential reference is available
        Pi-->>Node: Bubblewrap argument array and Pi environment additions
    end

    Node->>Runner: ProcessSpec and secret values for redaction
    Runner->>Child: create_subprocess_exec with fresh environment
    par output streaming
        Child-->>Runner: stdout/stderr
        Runner->>Runner: Redact secrets and enforce byte bounds
        Runner->>Files: Persist attempt output
        Runner-->>Wave: Publish live log/Pi events
    end
    Child-->>Runner: Exit status
    Runner-->>Node: Bounded result and output paths
    Node->>Node: Clear secret/environment dictionaries and Pi scratch
    Node-->>Wave: Attempt result
    Wave->>DB: Persist result and output metadata
```

The process runner registers the child's process group so cancellation can send `SIGTERM`, wait for the configured grace period, and escalate to `SIGKILL`. Secret redaction covers persisted and broadcast output but does not prevent trusted child code from reading credentials intentionally released in its environment.

All ready process nodes in one invocation execute concurrently as a wave. If any required attempt fails, Kyron cancels siblings, records every outcome, resets the worktree to the wave start commit, and fails the wave. Retrying creates new attempt rows.

## Pause and resume at a feedback gate

```mermaid
sequenceDiagram
    participant Coord as Run coordinator
    participant DB as PostgreSQL
    participant Host as GitLab/GitHub
    actor Reviewer
    participant Webhook as Webhook API
    participant Runtime as Engine runtime

    Coord->>Host: Push workspace branch and open/update review request
    Coord->>DB: Open gate with policy and eligible-identity snapshot
    Coord->>DB: Set run AWAITING_FEEDBACK
    Coord-->>Runtime: Run task stops cleanly

    Reviewer->>Host: Approve, comment or request changes
    Host->>Webhook: Signed webhook delivery
    Webhook->>Webhook: Verify signature and deduplicate delivery
    Webhook->>DB: Match provider identity to gate snapshot and permission
    Webhook->>DB: Append decision/feedback evidence

    alt quorum satisfied
        Webhook->>Host: Consume intermediate provider approval
        Webhook->>DB: Prepare explicit resume transition
        Webhook->>Runtime: Reschedule run
        Runtime->>Coord: Continue addressed invocation/workspace
    else feedback still incomplete
        Webhook-->>Host: Accept event without resuming
    end
```

Only provider identities captured as eligible when the gate opened can control it, and project permission is checked again at the API boundary. Intermediate approval must be consumed before execution continues so it cannot also satisfy the final protected-branch requirement.

Workspace-review requests belong to isolated workspaces and target the immediate parent branch. This lets one child resume without advancing a sibling. The root final change request remains a separate lifecycle boundary.

## Backend restart and recovery

```mermaid
sequenceDiagram
    participant Process as Backend process
    participant DB as PostgreSQL
    participant Runtime as Engine runtime
    actor Operator
    participant Git as Git/worktree checks

    Process->>DB: Run migrations
    Process->>Runtime: Start FastAPI lifespan
    Runtime->>DB: Mark in-flight execution INTERRUPTED
    Runtime->>DB: Read durable QUEUED runs
    loop each queued run
        Runtime->>Runtime: Schedule bounded run task
    end
    Runtime->>Runtime: Start queue and resource reconcilers

    Note over DB: AWAITING_FEEDBACK gates remain waiting
    Operator->>DB: Request resume for an interrupted/failed run
    DB->>Git: Validate expected worktree and checkpoint state
    alt recovery checks pass
        Git-->>Runtime: Workspace ready
        Runtime->>Runtime: Reschedule with fresh attempts where required
    else recovery checks fail
        Git-->>Operator: Explicit recovery error and execution remains stopped
    end
```

Kyron does not try to resurrect lost operating-system processes. Durable state records the interruption, while an operator-driven resume validates the current workspace against recorded checkpoints. Feedback waits remain unchanged because they represent durable external coordination rather than active worker ownership.

## Related contracts

- [Run states](/reference/states) defines permitted high-level transitions.
- [Edges, conditions, and joins](/workflows/edges-and-joins) defines DAG readiness.
- [Review loops](/workflows/review-loops) defines explicit repetition.
- [Failure and recovery](/guides/recovery) provides operator actions.
- [Security model](/deployment/security) defines subprocess and secret guarantees.
