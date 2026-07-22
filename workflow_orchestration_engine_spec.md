# Workflow Orchestration Engine
## Complete Implementation Specification

> **Provider extension:** `docs/code-host-provider-spec.md` is the normative
> delta for GitLab/GitHub dual-provider identity, delivery, webhooks, fields, and
> configuration. It supersedes GitLab-only clauses in this original specification.

**Revision:** 2.0  
**Status:** Implementation handoff  
**Target environment:** Trusted internal deployment on a single VM  
**Primary integrations:** GitLab, GitHub, Caddy OAuth, Pi coding agent

---

## 0. Document Purpose

This document is the authoritative implementation specification for a self-hosted workflow orchestration platform. It is intended to be handed directly to a coding assistant or implementation team.

The specification defines:

- Product scope and trust assumptions.
- System architecture and deployment model.
- Database schema and state machines.
- Workflow and sub-workflow definition formats.
- Explicit review-loop semantics.
- Git worktree and exact-revision handling.
- Deterministic failure recovery and resume behavior.
- GitLab merge-request and GitHub pull-request feedback, approval, and webhook integration.
- Pi coding-agent invocation and event handling.
- Backend APIs, frontend behavior, testing, and implementation order.

Where pseudocode is provided, it is normative regarding behavior but not necessarily final production syntax.

---

# 1. Project Overview

## 1.1 Goal

Build a self-hosted workflow orchestration platform that allows authenticated internal users to visually create, trigger, execute, and monitor AI-assisted coding workflows on Git repositories.

The platform runs on a single VM behind Caddy. It integrates with:

- GitLab and GitHub for repositories, branches, change requests, comments, reviewers, approvals, and lifecycle webhooks.
- Pi as the coding assistant used by prompt nodes.
- PostgreSQL for durable execution metadata.
- The local filesystem for cloned repositories, worktrees, node output, and run artifacts.

## 1.2 Internal Trust Model

This system is designed for trusted internal use only.

The following assumptions are intentional:

1. The application is reachable only through the internal environment and Caddy-managed OAuth.
2. Workflow definitions are created and approved by a trusted workflow author.
3. Project membership and project-scoped permissions control visibility of projects,
   workflows, runs, logs, reports, and workflow status.
4. The first authenticated user is bootstrapped as global system administrator. Global
   administrators and project administrators manage project memberships, roles, approval
   policies, and governance profiles.
5. Parallel nodes may share the same worktree. The workflow author is responsible for ensuring that nodes scheduled in parallel do not conflict.
6. Bash and Python nodes are trusted to execute within the backend environment. Pi nodes
   retain read, network, environment, and compute access, while Bubblewrap confines
   filesystem writes to the run worktree and ephemeral Pi state. Container-per-node
   sandboxing is out of scope for the first version.

These assumptions simplify the initial implementation. They must be clearly documented in the README and deployment notes so that the system is not later exposed to untrusted users without a security redesign.

## 1.3 Core Execution Concept

Users register GitLab or GitHub repositories, then define workflows in a visual graph editor. A workflow is a directed acyclic graph of executable and control nodes.

Supported node types are:

1. `bash` — execute a shell command.
2. `script` — execute a Python script from the repository.
3. `prompt` — execute Pi in non-interactive JSON mode.
4. `human_feedback` — create or update a merge request and pause for approval or feedback.
5. `subworkflow` — invoke another workflow once within the same run and worktree.
6. `review_loop` — invoke a child workflow, request review, and repeat a child workflow when changes are requested.

Arbitrary graph cycles are not supported. Repetition is represented explicitly by a `review_loop` node. This keeps workflow execution, persistence, resume, and visualization deterministic while still supporting iterative AI-review workflows.

When a workflow is triggered, the engine:

1. Fetches the GitLab repository.
2. Resolves the exact commit SHA of the selected base ref.
3. Loads the root workflow and all transitively referenced sub-workflows from that exact commit.
4. Validates and snapshots the complete workflow bundle.
5. Creates an isolated branch and Git worktree from the pinned commit SHA.
6. Executes ready nodes in waves, respecting conditions and join semantics.
7. Executes independent nodes in the same wave concurrently.
8. Records the Git commit at the start and end of every wave.
9. Stores engine logs in PostgreSQL and process output on disk.
10. Pauses at human feedback or review-loop checkpoints.
11. Creates a change request if one does not yet exist and requests all eligible provider
    identities snapshotted for the active approval policy as reviewers.
12. Continues only when the active gate policy's complete quorum is satisfied, or an
    authorized project administrator records a reasoned override.
13. Resets the intermediate GitLab approval before continuing so a new approval is required for final merge.
14. On completion, commits and pushes final changes and leaves the worktree available until the merge request is merged or closed.
15. On failure or restart, resumes from the start of the failed or interrupted execution wave.

## 1.4 Key Requirements

- Multi-user authentication through Caddy and an OAuth auth service.
- Project-membership-controlled visibility of projects, workflows, runs, logs, and reports.
- Per-project encrypted GitLab project access tokens.
- Per-user encrypted AI-provider credentials.
- Credential values decrypted only immediately before process execution.
- Credential plaintext never persisted in workflow snapshots, checkpoints, graph state, logs, API responses, or node output metadata.
- Exact repository commit SHA pinned for every run.
- Workflow and transitive sub-workflow bundle snapshotted at trigger time.
- Visual workflow builder with reusable sub-workflows.
- Explicit `review_loop` control node for iterative review and revision.
- Parallel fan-out and AND/OR joins inside acyclic workflows.
- Shared worktree for all nodes in one run.
- Git checkpoint per execution wave.
- Deterministic resume by resetting the worktree to the failed wave's start commit and rerunning that wave.
- GitLab merge request creation, reviewer assignment, comments, approval detection, approval reset, and cleanup webhooks.
- Reusable project approval policies select roles and optionally named users, support one
  or more quorum requirements, configurable initiator approval, and optionally require
  distinct approvers across requirements.
- Frontend and provider gate actions use the same immutable eligibility snapshot.
- Live process and engine log streaming over WebSocket.
- Maximum number of concurrent workflow runs.
- Task and subprocess tracking for cancellation.
- One Uvicorn worker in the prototype architecture.
- Hourly stale-resource reconciliation.

## 1.5 Non-Goals for Version 1

The following are explicitly out of scope:

- Public internet exposure without the OAuth layer.
- Untrusted workflow execution.
- Separate worker service or distributed job queue.
- Multi-VM execution.
- Arbitrary cyclic workflow graphs.
- Conflict-safe parallel editing of the same files.
- Exact rollback of external side effects performed by scripts.
- Kubernetes deployment.
- Git providers other than GitLab.

---

# 2. Architecture Overview

## 2.1 High-Level Architecture

```text
┌────────────────────────────────────────────────────────────────────┐
│ Caddy                                                              │
│ - TLS termination                                                  │
│ - Static React frontend                                            │
│ - forward_auth to auth-service                                     │
│ - Reverse proxy for HTTP and WebSocket                             │
│ - Unauthenticated exceptions: health and GitLab webhook            │
└──────────────────────┬─────────────────────────────────────────────┘
                       │ trusted identity headers
                       ▼
┌────────────────────────────────────────────────────────────────────┐
│ FastAPI Backend — exactly one Uvicorn worker                        │
│                                                                    │
│ API routes                 Engine module                           │
│ - projects                 - scheduler / execution waves           │
│ - credentials              - sub-workflow invocation               │
│ - workflows                - review-loop controller                │
│ - runs                     - resume / cancellation                 │
│ - feedback                 - subprocess runner                     │
│ - webhook                  - Git manager                           │
│ - WebSocket logs           - GitLab client                         │
│                            - Pi JSON event adapter                  │
│                            - ephemeral credential loader            │
└───────────────┬───────────────────────────┬────────────────────────┘
                │                           │
                ▼                           ▼
┌─────────────────────────────┐  ┌───────────────────────────────────┐
│ PostgreSQL                  │  │ Persistent filesystem             │
│ - users                     │  │ /var/workflowengine/repos         │
│ - credentials               │  │ /var/workflowengine/worktrees     │
│ - projects                  │  │ /var/workflowengine/run_data      │
│ - workflow_runs             │  │ - stdout/stderr                   │
│ - workflow_invocations      │  │ - Pi JSONL                        │
│ - execution_waves           │  │ - artifacts                       │
│ - node_executions           │  └───────────────────────────────────┘
│ - node_attempts             │
│ - edge_evaluations          │
│ - feedback_events           │
│ - run_logs                  │
│ - webhook_deliveries        │
└─────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────────────┐
│ GitLab                                                             │
│ - repository                                                       │
│ - branches and pushes                                              │
│ - merge requests                                                   │
│ - reviewer assignment                                              │
│ - comments beginning with @kyron                                    │
│ - approval events                                                  │
│ - merge/close cleanup events                                       │
└────────────────────────────────────────────────────────────────────┘
```

## 2.2 Component Responsibilities

### Caddy

- Terminate TLS.
- Serve the built React application.
- Delegate authentication to the auth service using `forward_auth`.
- Strip any client-supplied trusted identity headers before forwarding.
- Copy identity headers only from a successful auth-service response.
- Proxy `/api/*`, including WebSocket upgrades, to FastAPI.
- Proxy `/auth/*` to the auth service.
- Allow `/api/health` and `/api/webhook/gitlab` without OAuth.

### Auth Service

- Perform GitLab OAuth login.
- Store only a signed HTTP-only session cookie in the browser.
- Return identity headers to Caddy on `/auth/verify`:
  - `X-Token-User-Email`
  - `X-Token-User-Name`
  - `X-Token-User-Avatar`
  - `X-Token-GitLab-User-Id`
  - `X-Token-GitLab-Username`
- Use the GitLab user ID from OAuth as the authoritative identity for reviewer assignment and approval matching.

### FastAPI Backend

- Expose all HTTP and WebSocket APIs.
- Maintain the in-process run semaphore, task registry, process registry, and log broadcaster.
- Start and resume workflow tasks.
- Store durable state before reporting actions as successful.
- Enforce project membership and operation-specific permissions, and accept gate decisions
  only from provider identities in the active gate's immutable eligibility snapshot.

### Engine Module

- Execute the snapshotted workflow bundle.
- Resolve ready nodes and build execution waves.
- Invoke sub-workflows in the same worktree.
- Manage review-loop iterations.
- Record wave Git checkpoints.
- Restore a clean wave start state after failure.
- Decrypt credentials immediately before each subprocess and discard them afterward.

## 2.3 In-Process Prototype Limitation

The initial system deliberately uses FastAPI background tasks instead of a separate worker service.

Important limitations:

- Tasks disappear when Uvicorn restarts.
- The concurrency semaphore is in memory.
- Active process tracking is in memory.
- The WebSocket broadcaster is in memory.
- A run record can be committed before its asyncio task is successfully registered.
- Multiple Uvicorn workers would create independent schedulers and could execute the same work twice.

Therefore:

1. The backend must run with exactly one Uvicorn worker.
2. Auto-reload must never be used in production.
3. PostgreSQL is the source of truth for run state.
4. Startup recovery must requeue `QUEUED` runs and mark active runs `INTERRUPTED`.
5. A future production-hardening phase may split the engine into a database-backed worker, but this is not required for version 1.

---

# 3. Technology Stack

| Layer | Technology |
|---|---|
| Reverse proxy | Caddy 2 |
| Frontend | React 18+, TypeScript, Vite, React Flow, Tailwind CSS |
| Frontend server state | TanStack Query |
| Builder state | Zustand |
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Database | PostgreSQL 16+ |
| ORM | SQLAlchemy 2 async |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Encryption | `cryptography` Fernet |
| Git | Git CLI through async subprocesses |
| GitLab API | `httpx` or `python-gitlab`; direct REST examples are normative |
| AI assistant | `@earendil-works/pi-coding-agent` CLI |
| Process management | `asyncio.create_subprocess_exec` / `create_subprocess_shell` |
| Filesystem I/O | `aiofiles` for asynchronous reads where useful |
| Testing | pytest, pytest-asyncio, HTTPX test client, Playwright optional |

---

# 4. Database Schema

All timestamps use `TIMESTAMPTZ` and are stored in UTC.

## 4.1 `users`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Generated |
| `email` | VARCHAR(255) UNIQUE | From OAuth |
| `display_name` | VARCHAR(255) | From OAuth |
| `avatar_url` | TEXT NULL | From OAuth |
| `gitlab_user_id` | BIGINT UNIQUE | Authoritative GitLab identity |
| `gitlab_username` | VARCHAR(255) | GitLab username |
| `oauth_provider` | VARCHAR(50) | Initially `gitlab` |
| `created_at` | TIMESTAMPTZ | Generated |
| `last_login_at` | TIMESTAMPTZ | Updated during authenticated requests, but no more than once per configured interval |

## 4.2 `credentials`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Generated |
| `user_id` | UUID FK | References `users.id` |
| `key_name` | VARCHAR(255) | Must match environment variable syntax |
| `encrypted_value` | BYTEA | Fernet ciphertext |
| `key_version` | INTEGER | Encryption-key version, initially `1` |
| `description` | TEXT NULL | User note |
| `created_at` | TIMESTAMPTZ | Generated |
| `updated_at` | TIMESTAMPTZ | Generated |

Constraints:

- Unique `(user_id, key_name)`.
- `key_name` must match `^[A-Za-z_][A-Za-z0-9_]*$`.

Credential values are never copied into another database table.

## 4.3 `projects`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Generated |
| `name` | VARCHAR(255) | Display name |
| `git_url` | TEXT | Original HTTPS clone URL without token |
| `gitlab_project_id` | BIGINT UNIQUE | GitLab project ID |
| `encrypted_access_token` | BYTEA | Project access token ciphertext |
| `token_key_version` | INTEGER | Encryption-key version |
| `local_path` | TEXT UNIQUE | Bare/shared clone path |
| `default_branch` | VARCHAR(255) | Cached project default branch |
| `pi` | JSONB | Project-wide Pi provider, model, and repository skill defaults |
| `added_by` | UUID FK | References `users.id` |
| `created_at` | TIMESTAMPTZ | Generated |
| `updated_at` | TIMESTAMPTZ | Generated |

The project token must be a GitLab project access token represented by a bot user and must have sufficient access for repository writes and GitLab API operations.

## 4.4 `workflow_runs`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Run ID |
| `root_workflow_id` | VARCHAR(255) | Root workflow identifier |
| `project_id` | UUID FK | References `projects.id` |
| `triggered_by` | UUID FK | References `users.id` |
| `status` | VARCHAR(50) | State machine below |
| `status_version` | INTEGER | Incremented on atomic transitions |
| `base_ref` | VARCHAR(255) | Usually default branch |
| `base_commit_sha` | CHAR(40) | Exact repository revision |
| `workflow_definition_commit_sha` | CHAR(40) | Same as base SHA in v1 |
| `workflow_bundle_snapshot` | JSONB | Root and all referenced workflows, without secrets |
| `public_context` | JSONB | Persistable non-secret variables only |
| `branch_name` | VARCHAR(255) NULL | Run branch |
| `worktree_path` | TEXT NULL | Run worktree |
| `run_data_path` | TEXT NULL | Output directory |
| `current_head_sha` | CHAR(40) NULL | Latest committed checkpoint |
| `final_commit_sha` | CHAR(40) NULL | Final run commit |
| `mr_iid` | INTEGER NULL | MR internal ID |
| `mr_url` | TEXT NULL | MR URL |
| `reviewer_provider*` | Provider identity fields | Triggering identity retained as the default final reviewer; gate snapshots are authoritative for intermediate review |
| `current_invocation_id` | UUID NULL | Current invocation |
| `current_node_execution_id` | UUID NULL | Current logical node |
| `current_wave_id` | UUID NULL | Current wave |
| `pending_operation` | VARCHAR(50) NULL | Durable external transition awaiting completion, such as feedback or final publication |
| `error_type` | VARCHAR(100) NULL | `NODE_FAILURE`, `INTERRUPTED`, etc. |
| `error_message` | TEXT NULL | Sanitized error |
| `cancel_requested_at` | TIMESTAMPTZ NULL | Cancellation flag |
| `created_at` | TIMESTAMPTZ | Generated |
| `queued_at` | TIMESTAMPTZ | Generated |
| `started_at` | TIMESTAMPTZ NULL | First execution start |
| `finished_at` | TIMESTAMPTZ NULL | Terminal state time |

Indexes:

- `(status, queued_at)`.
- `(project_id, created_at DESC)`.
- `(mr_iid, project_id)`.
- `(triggered_by, created_at DESC)`.

### Run status state machine

```text
QUEUED -> RUNNING -> COMPLETED
             |  \
             |   -> AWAITING_FEEDBACK -> RUNNING
             |                            |
             |                            -> AWAITING_FEEDBACK
             |
             -> FAILED -> RESUMING -> RUNNING
             -> INTERRUPTED -> RESUMING -> RUNNING

QUEUED/RUNNING/RESUMING/AWAITING_FEEDBACK/FAILED/INTERRUPTED -> CANCELLED
CANCELLED -> QUEUED/RESUMING/AWAITING_FEEDBACK
```

Valid values:

- `QUEUED`
- `RUNNING`
- `AWAITING_FEEDBACK`
- `FAILED`
- `INTERRUPTED`
- `RESUMING`
- `COMPLETED`
- `CANCELLED`

## 4.5 `workflow_invocations`

An invocation represents one execution of the root workflow or a sub-workflow.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Generated |
| `run_id` | UUID FK | References `workflow_runs.id` |
| `workflow_id` | VARCHAR(255) | Workflow in snapshot bundle |
| `invocation_path` | TEXT | Stable path, e.g. `root/review_1/revision[2]` |
| `parent_invocation_id` | UUID NULL | Parent invocation |
| `parent_node_execution_id` | UUID NULL | Calling subworkflow/review-loop node |
| `loop_iteration` | INTEGER | `1` outside loops |
| `input_context` | JSONB | Non-secret mapped inputs |
| `output_context` | JSONB | Non-secret exported outputs |
| `status` | VARCHAR(50) | `PENDING`, `RUNNING`, `SUCCESS`, `FAILED`, `CANCELLED` |
| `started_at` | TIMESTAMPTZ NULL | |
| `finished_at` | TIMESTAMPTZ NULL | |

Constraints:

- Unique `(run_id, invocation_path)`.

## 4.6 `execution_waves`

A wave is a set of ready nodes launched together against one shared worktree checkpoint.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Generated |
| `run_id` | UUID FK | |
| `invocation_id` | UUID FK | |
| `wave_index` | INTEGER | Monotonic within invocation |
| `status` | VARCHAR(50) | `PENDING`, `RUNNING`, `SUCCESS`, `FAILED`, `INTERRUPTED`, `ROLLED_BACK` |
| `start_commit_sha` | CHAR(40) | Clean checkpoint before wave |
| `end_commit_sha` | CHAR(40) NULL | Checkpoint after successful wave |
| `started_at` | TIMESTAMPTZ NULL | |
| `finished_at` | TIMESTAMPTZ NULL | |
| `error_message` | TEXT NULL | Sanitized |

Constraints:

- Unique `(invocation_id, wave_index)`.

## 4.7 `node_executions`

A node execution is a logical node instance within an invocation.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Generated |
| `run_id` | UUID FK | |
| `invocation_id` | UUID FK | |
| `wave_id` | UUID FK NULL | Human checkpoints may be outside normal waves |
| `node_id` | VARCHAR(255) | Node ID from workflow |
| `node_path` | TEXT | Invocation path plus node ID |
| `node_type` | VARCHAR(50) | |
| `status` | VARCHAR(50) | Below |
| `current_attempt` | INTEGER | Starts at `0` |
| `exit_code` | INTEGER NULL | Most recent attempt |
| `stdout_path` | TEXT NULL | Relative to run data |
| `stderr_path` | TEXT NULL | Relative to run data |
| `output_values` | JSONB | Persistable non-secret outputs only |
| `started_at` | TIMESTAMPTZ NULL | |
| `finished_at` | TIMESTAMPTZ NULL | |
| `error_message` | TEXT NULL | |

Statuses:

- `PENDING`
- `RUNNING`
- `SUCCESS`
- `FAILED`
- `SKIPPED`
- `AWAITING_FEEDBACK`
- `CANCELLED`
- `INTERRUPTED`

Constraint:

- Unique `(invocation_id, node_id)` because ordinary workflow graphs are acyclic. Repeated child-workflow execution receives a new invocation path.

## 4.8 `node_attempts`

Every retry or resume creates a new attempt and preserves history.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Generated |
| `node_execution_id` | UUID FK | |
| `attempt_number` | INTEGER | 1-based |
| `status` | VARCHAR(50) | `RUNNING`, `SUCCESS`, `FAILED`, `CANCELLED`, `INTERRUPTED` |
| `process_pid` | INTEGER NULL | Diagnostic only |
| `exit_code` | INTEGER NULL | |
| `started_at` | TIMESTAMPTZ | |
| `finished_at` | TIMESTAMPTZ NULL | |
| `error_type` | VARCHAR(100) NULL | |
| `error_message` | TEXT NULL | Sanitized |

Constraint:

- Unique `(node_execution_id, attempt_number)`.

## 4.9 `edge_evaluations`

Persisting edge results avoids reevaluating filesystem-dependent conditions during resume.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `run_id` | UUID FK | |
| `invocation_id` | UUID FK | |
| `source_node_execution_id` | UUID FK | |
| `edge_id` | VARCHAR(255) | |
| `target_node_id` | VARCHAR(255) | |
| `condition_result` | BOOLEAN | |
| `evaluated_value` | TEXT NULL | Sanitized diagnostic value |
| `created_at` | TIMESTAMPTZ | |

Constraint:

- Unique `(source_node_execution_id, edge_id)`.

## 4.10 `feedback_events`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `run_id` | UUID FK | |
| `node_execution_id` | UUID FK | Human or review-loop node |
| `iteration` | INTEGER | Review-loop iteration |
| `event_type` | VARCHAR(30) | `approval` or `comment` |
| `source` | VARCHAR(30) | `gitlab` or `frontend` |
| `author_user_id` | UUID NULL | Frontend user if known |
| `author_provider` | VARCHAR(30) | Authenticated code-host provider |
| `author_provider_user_id` | VARCHAR(255) | Must be eligible in the gate snapshot |
| `author_username` | VARCHAR(255) | |
| `message` | TEXT | Empty for approval |
| `gitlab_note_id` | BIGINT NULL | |
| `created_at` | TIMESTAMPTZ | |

## 4.11 `run_logs`

Engine-level logs only.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | Also used as stream sequence |
| `run_id` | UUID FK | |
| `invocation_path` | TEXT NULL | |
| `node_path` | TEXT NULL | |
| `timestamp` | TIMESTAMPTZ | |
| `level` | VARCHAR(20) | `DEBUG`, `INFO`, `WARN`, `ERROR` |
| `event_type` | VARCHAR(100) | Structured lifecycle type |
| `message` | TEXT | Sanitized |
| `metadata` | JSONB | Must not contain secrets |

Index `(run_id, id)`.

## 4.12 `webhook_deliveries`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `delivery_key` | VARCHAR(255) UNIQUE | `webhook-id`, `Idempotency-Key`, or fallback UUID header |
| `gitlab_project_id` | BIGINT NULL | |
| `event_name` | VARCHAR(100) | |
| `received_at` | TIMESTAMPTZ | |
| `processed_at` | TIMESTAMPTZ NULL | |
| `status` | VARCHAR(30) | `RECEIVED`, `PROCESSED`, `IGNORED`, `FAILED` |
| `result` | JSONB | Sanitized |

This table prevents duplicate handling across GitLab retries and application restarts.

## 4.13 Authorization, governance, gates, and reports

The authorization and conformance model uses the following durable records:

| Tables | Purpose |
|---|---|
| `project_memberships`, `project_roles`, `project_role_permissions`, `project_membership_roles` | Active project membership and composable project-scoped roles from the fixed permission catalog |
| `approval_policies`, `approval_policy_requirements`, `approval_requirement_roles`, `approval_requirement_users` | Reusable role/user/dynamic-triggerer requirements, per-requirement quorum, initiator approval, and cross-requirement distinctness settings |
| `governance_profiles` | Optional tag-scoped rules requiring named policies, independent approval, and a minimum total quorum |
| `gate_instances` | Immutable policy and eligibility snapshots tied to the exact invocation, node execution, iteration, and checkpoint commit |
| `gate_decisions` | Actor snapshots, matched requirements, approval/feedback/override evidence, provider event IDs, and supersession state |
| `authorization_audit_events` | Append-only actor, action, target, project/run scope, and sanitized details for security-relevant actions |
| `run_reports` | One versioned frozen report payload for each terminal run |
| `change_request_lifecycle_events` | Post-run merge/close actor, delivery, and optional merge commit evidence appended to report responses |

The `run.delete` project permission allows permanent deletion only after a run reaches
`COMPLETED`, `FAILED`, `INTERRUPTED`, or `CANCELLED`. Deletion removes the worktree, local run
branch, output data, and execution record hierarchy before removing the run itself. Active runs
cannot be deleted. A separate authorization audit event retains the actor, project, deleted run
identifier, and final status; remote branches and change requests are left untouched.

The first authenticated user becomes the initial global system administrator. New projects
seed the built-in roles, assign the registering administrator as project administrator, and
create the `default` approval policy. That policy has one quorum-1 requirement whose only
eligible identity is the user who triggered the workflow. This is bootstrap behavior, not an
implicit authorization rule for later users.

A gate snapshot is never recalculated in place. Membership or policy edits affect only later
gate instances. Revision feedback closes the current gate, supersedes its approvals, and a
later iteration resolves current membership into a new snapshot at its new checkpoint SHA.

---
# 5. Workflow Definition Format

## 5.1 Storage Location

Workflow files are JSON documents stored in the repository:

```text
repo-root/
└── .workflowEngine/
    ├── delivery/
    │   ├── full_review.json
    │   └── implement_changes.json
    ├── quality/
    │   ├── revise_from_feedback.json
    │   └── test_and_validate.json
    └── templates/
        └── print_text.json
```

Node templates are project-scoped JSON documents. Each template contains an ID,
display name, description, and one fully validated workflow node. Inserting a
template clones the node and assigns a unique node ID and canvas position.

The builder maintains project-scoped local definition changes outside the shared
repository clone. **Store** validates and writes to this local layer without a Git
commit or remote operation. The workflow catalog overlays local changes on the exact
default-branch revision and reports outgoing and in-review counts.

**Create review** batches all outgoing workflow and template changes into one branch,
one commit, and one GitLab merge request or GitHub pull request. The reviewed layer
remains visible until it matches the default branch after merge. Additional outgoing
changes update the existing review branch.

Ordinary runs load workflow definitions merged into the selected base ref. An explicit
local-definition test run materializes the complete local overlay into an exact local
Git commit and snapshots from that commit. Such a run never pushes its run branch or
opens a code-host change request; its worktree and results remain on the Kyron host.

## 5.2 Workflow Identifier Rules

Workflow IDs, node IDs, input names, output names, and variable names must match:

```regex
^[A-Za-z][A-Za-z0-9_]*$
```

Workflow filenames must equal `<workflow_id>.json`.

Workflow definitions may be placed at any depth below `.workflowEngine/`. The relative
folder path is catalog metadata and the UI mirrors that hierarchy. The top-level
`.workflowEngine/templates/` directory remains reserved for node templates. Workflow IDs
must be unique across the complete directory tree; sub-workflow and review-loop references
continue to use the workflow ID and do not include the folder path. Exact-commit snapshot
resolution builds an ID-to-path index from the Git tree before loading the transitive bundle.

Workflow tags are optional lowercase labels used only for catalog organization. A tag must
match `^[a-z0-9][a-z0-9._-]*$`, is limited to 64 characters, and may occur only once per
workflow. A workflow may have at most 32 tags. Tags do not affect execution or reference
resolution.

## 5.3 Root Schema

```json
{
  "id": "full_review",
  "name": "Full AI Review",
  "description": "Implements a task, validates it, and repeats revisions after review feedback.",
  "version": 2,
  "created_by": "user@example.com",
  "tags": ["implementation", "team-platform"],

  "inputs": {
    "TASK": {
      "type": "string",
      "required": true,
      "description": "Task to implement"
    }
  },

  "outputs": {
    "FINAL_TEST_STATUS": {
      "type": "string",
      "source": "${NODE_final_tests_EXIT_CODE}"
    }
  },

  "variables": {
    "TARGET_DIR": "src/",
    "TEST_COMMAND": "python -m pytest -q"
  },

  "nodes": [],
  "edges": [],

  "settings": {
    "pi": {
      "provider": "anthropic",
      "model": "anthropic/claude-sonnet-4-5",
      "skill": ".agents/skills/implementation/SKILL.md"
    },
    "auto_commit_after_wave": true,
    "wave_commit_message_template": "workflow(${WORKFLOW_ID}): wave ${WAVE_INDEX}",
    "final_commit_message_template": "workflow(${WORKFLOW_ID}): complete run ${RUN_ID}",
    "mr_title_template": "Workflow: ${WORKFLOW_NAME} (${RUN_ID_SHORT})",
    "mr_description_template": "Automated workflow run triggered by ${USER_NAME}.\n\nWorkflow: ${WORKFLOW_NAME}\nBase commit: ${BASE_COMMIT_SHA}\nRun: ${RUN_ID}",
    "timeout_per_node_seconds": 1800,
    "max_review_iterations": 5,
    "max_subworkflow_depth": 8,
    "max_output_variable_bytes": 65536
  }
}
```

## 5.4 Node Common Fields

Every node contains:

```json
{
  "id": "node_id",
  "type": "bash",
  "label": "Human-readable label",
  "join": "and",
  "config": {},
  "position": { "x": 100, "y": 100 }
}
```

Common rules:

- `join` is optional and defaults to `and`.
- `join` matters only for nodes with more than one incoming edge.
- `position` is frontend metadata and does not affect execution.
- Nodes must not contain secret values.

## 5.5 Edge Schema

```json
{
  "id": "edge_tests_to_review",
  "source": "tests",
  "target": "review",
  "condition": {
    "type": "exit_code",
    "operator": "equals",
    "value": 0
  }
}
```

Edges are directed. The graph inside each workflow file must be acyclic.

## 5.6 Complete Example with Sub-Workflow and Review Loop

```json
{
  "id": "implement_and_review",
  "name": "Implement and Review",
  "description": "Runs an implementation child workflow and repeats revisions until approved.",
  "version": 2,
  "created_by": "user@example.com",

  "inputs": {
    "TASK": {
      "type": "string",
      "required": true
    }
  },

  "variables": {
    "TARGET_DIR": "src/"
  },

  "nodes": [
    {
      "id": "prepare",
      "type": "bash",
      "label": "Prepare repository",
      "config": {
        "command": "git status --short && python -m pip install -r requirements.txt",
        "timeout": 900,
        "allow_failure": false
      },
      "position": { "x": 100, "y": 100 }
    },
    {
      "id": "implementation_review",
      "type": "review_loop",
      "label": "Implement and review",
      "config": {
        "initial_workflow_id": "implement_changes",
        "revision_workflow_id": "revise_from_feedback",
        "inputs": {
          "TASK": "${TASK}",
          "TARGET_DIR": "${TARGET_DIR}"
        },
        "revision_inputs": {
          "TASK": "${TASK}",
          "TARGET_DIR": "${TARGET_DIR}",
          "FEEDBACK": "${FEEDBACK}"
        },
        "commit_message": "Checkpoint: implementation iteration ${REVIEW_ITERATION}",
        "mr_title": "Implement: ${TASK}",
        "mr_description": "Approve or comment with `@kyron` followed by feedback.",
        "max_iterations": 5
      },
      "position": { "x": 100, "y": 260 }
    },
    {
      "id": "final_validation",
      "type": "subworkflow",
      "label": "Final validation",
      "config": {
        "workflow_id": "test_and_validate",
        "inputs": {
          "TARGET_DIR": "${TARGET_DIR}"
        },
        "output_mapping": {
          "TEST_STATUS": "FINAL_TEST_STATUS"
        }
      },
      "position": { "x": 100, "y": 430 }
    }
  ],

  "edges": [
    {
      "id": "e1",
      "source": "prepare",
      "target": "implementation_review",
      "condition": null
    },
    {
      "id": "e2",
      "source": "implementation_review",
      "target": "final_validation",
      "condition": null
    }
  ],

  "settings": {
    "auto_commit_after_wave": true,
    "wave_commit_message_template": "workflow(${WORKFLOW_ID}): wave ${WAVE_INDEX}",
    "final_commit_message_template": "workflow(${WORKFLOW_ID}): complete",
    "mr_title_template": "Workflow: ${WORKFLOW_NAME} (${RUN_ID_SHORT})",
    "mr_description_template": "Triggered by ${USER_NAME} from ${BASE_COMMIT_SHA}.",
    "timeout_per_node_seconds": 1800,
    "max_review_iterations": 5,
    "max_subworkflow_depth": 8,
    "max_output_variable_bytes": 65536
  }
}
```

---

# 6. Node Types

## 6.1 Bash Node

```json
{
  "type": "bash",
  "config": {
    "command": "python -m pytest ${TEST_ARGS}",
    "timeout": 1800,
    "allow_failure": false,
    "shell": "/bin/bash"
  }
}
```

Behavior:

- Expand public `${VAR}` placeholders before execution.
- Execute through the configured shell.
- Set `cwd` to the run worktree.
- Inject the complete public context and all decrypted credentials into the process environment.
- Capture stdout and stderr separately.
- A non-zero exit code fails the node unless `allow_failure` is true.

Normative execution form:

```python
await asyncio.create_subprocess_exec(
    "/bin/bash", "-lc", expanded_command,
    cwd=worktree_path,
    env=ephemeral_env,
    stdout=PIPE,
    stderr=PIPE,
    start_new_session=True,
)
```

Do not pass the access token in the command line.

## 6.2 Script Node

```json
{
  "type": "script",
  "config": {
    "script": "scripts/validate.py",
    "python": "python3",
    "args": ["--strict", "--output", "results.json"],
    "timeout": 1800,
    "allow_failure": false
  }
}
```

Behavior:

- The path is relative to the worktree root.
- Resolve the path and verify that the final path remains inside the worktree.
- Verify that the file exists before execution.
- Execute without `shell=True`.
- Expand public variables in each argument.

## 6.3 Prompt Node

```json
{
  "type": "prompt",
  "config": {
    "prompt": "Implement the following task: ${TASK}",
    "provider": "anthropic",
    "model": "anthropic/claude-sonnet-4-5",
    "skill": ".agents/skills/implementation/SKILL.md",
    "timeout": 1800,
    "allow_failure": false,
    "project_trust": "never"
  }
}
```

Pi must be invoked in JSON event-stream mode so that the backend can parse structured agent events.

Normative inner command:

```bash
pi --mode json --no-session --no-approve \
  --no-extensions \
  --extension /app/backend/engine/pi/worktree_guard.mjs \
  --provider anthropic \
  --model anthropic/claude-sonnet-4-5 \
  --no-skills \
  --skill /absolute/worktree/.agents/skills/implementation/SKILL.md \
  "/skill:implementation <expanded prompt>"
```

Rules:

- `--provider` is omitted when not configured.
- `--model` is omitted when not configured.
- `provider`, `model`, and `skill` resolve field-by-field from the prompt node,
  workflow `settings.pi`, project defaults, and finally Pi's own defaults.
- A configured `skill` is a repository-relative file or directory. Resolve it against
  the worktree, reject escapes and missing files, read the skill name from
  `SKILL.md` frontmatter, load it with `--skill`, and force it with `/skill:<name>`.
- `--no-skills` accompanies an explicit skill so the invocation loads exactly the
  snapshotted skill selected by the workflow configuration.
- `--no-session` prevents durable Pi session state from becoming the workflow state source.
- `--no-approve` prevents non-interactive execution from automatically trusting repository-local Pi configuration and extensions.
- `--no-extensions` plus the explicit built-in extension rejects out-of-worktree paths
  from Pi's `write` and `edit` tools without loading repository extensions.
- The engine parses each JSONL record from stdout.
- Raw JSONL is stored in `pi_events.jsonl`.
- A human-readable event stream is published to the run log WebSocket.
- Stderr is stored separately.
- The process exit code determines success.

The engine wraps the complete Pi argument array in Bubblewrap. It recursively
bind-mounts `/` read-only, rebinds only the resolved run worktree and a per-attempt
scratch directory read-write, creates a private PID namespace with an empty read-only
`/proc` and isolated ephemeral `/dev`, drops capabilities, and changes to the resolved
worktree before executing Pi. Pi state, cache, and temporary environment paths point into
the scratch directory. Consequently the Pi process, its Bash tool, and all descendants
can modify the worktree, scratch directory, and ephemeral device filesystem but cannot
mutate other filesystem paths. The sandbox does not restrict reads, network, environment
variables, or compute resources.

The empty `/proc` prevents access to the parent container namespace through
`/proc/<pid>/root` without requiring the container runtime to expose an unmasked procfs.
Prompt-node commands that require procfs information are unsupported.

Bubblewrap must be invoked as an argument array and must fail closed: Pi must not run if
the namespace or any mount cannot be established. The production image includes
`/usr/bin/bwrap`. Deployment acceptance must run
`python -m backend.engine.pi.sandbox --check` inside the backend container; this verifies
the complete namespace and mount behavior. Landlock is not required.

The Compose backend uses an unconfined seccomp profile while remaining an unprivileged
UID with all Linux capabilities dropped. Other runtimes may use a custom profile that
permits the required namespace and mount operations.

## 6.4 Human Feedback Node

```json
{
  "type": "human_feedback",
  "config": {
    "approval_policy": "default",
    "commit_message": "Checkpoint: awaiting review",
    "mr_title": "Workflow: ${WORKFLOW_NAME}",
    "mr_description": "Approve to continue or comment with `@kyron <feedback>`.",
    "allow_comment_feedback": true,
    "allow_approval": true
  }
}
```

`approval_policy` defaults to `default` when omitted. Every project has this policy; it requires
one approval from the workflow triggerer and permits that user to provide revision feedback.
Workflows select another project policy key when they require independent or additional review.

The node:

1. Resolves the referenced project approval policy and snapshots its eligible identities,
   requirements, and quorums.
2. Durably records the pending feedback publication and its checkpoint before external effects.
3. Pushes the run branch.
4. Reconciles or creates the change request and requests the snapshotted identities as reviewers.
5. Stores an atomic checkpoint containing the open gate, node status, and run status.
6. Pauses in `AWAITING_FEEDBACK`.
7. Records eligible approvals without continuing until every quorum requirement is met.
8. Ties all decisions to the exact checkpoint commit SHA.

On approval:

- Record an immutable gate decision against the open gate instance.
- Continue waiting when the complete policy quorum is not yet satisfied.
- Once satisfied, consume intermediate provider approvals, mark the gate and human node
  successful, and resume outgoing edges.

On eligible `@kyron` comment:

- Strip the prefix.
- Store `FEEDBACK`, `FEEDBACK_TYPE=comment`, and feedback-author public variables.
- Close the current gate as `CHANGES_REQUESTED`, preserve prior approvals as superseded,
  and resume the configured revision behavior. A later checkpoint always creates a new
  gate instance against a new commit and resolves current policy membership again.

A standalone human-feedback node does not itself repeat previous nodes. Iterative revision must use a `review_loop` node.

## 6.5 Sub-Workflow Node

```json
{
  "type": "subworkflow",
  "config": {
    "workflow_id": "test_and_validate",
    "inputs": {
      "TARGET_DIR": "${TARGET_DIR}"
    },
    "output_mapping": {
      "TEST_STATUS": "FINAL_TEST_STATUS"
    },
    "allow_failure": false
  }
}
```

Behavior:

1. Resolve `workflow_id` from the run's snapshotted workflow bundle.
2. Create a new `workflow_invocations` record.
3. Build the child public context:
   - Child workflow variable defaults.
   - Mapped child inputs.
   - Built-in run variables.
   - Parent node output variables that were explicitly mapped or already public.
4. Execute the child graph in the same worktree and run branch.
5. Do not create a separate worktree, branch, merge request, or workflow run.
6. Export declared child outputs through `output_mapping`.
7. Mark the sub-workflow node successful only when the child invocation succeeds.

Child workflows may call further child workflows up to `max_subworkflow_depth`.

Recursive workflow references are invalid, even if the recursion would be reached only conditionally.

## 6.6 Review Loop Node

The review loop is the only repeating control construct in version 1.

```json
{
  "type": "review_loop",
  "config": {
    "approval_policy": "default",
    "initial_workflow_id": "implement_changes",
    "revision_workflow_id": "revise_from_feedback",
    "inputs": {
      "TASK": "${TASK}"
    },
    "revision_inputs": {
      "TASK": "${TASK}",
      "FEEDBACK": "${FEEDBACK}"
    },
    "commit_message": "Checkpoint: review iteration ${REVIEW_ITERATION}",
    "mr_title": "Implement: ${TASK}",
    "mr_description": "Approve or request changes with `@kyron`.",
    "max_iterations": 5
  }
}
```

### Review-loop algorithm

1. Set `REVIEW_ITERATION=1`.
2. Invoke `initial_workflow_id` in a child invocation path such as:
   `root/review_node/initial[1]`.
3. If the child fails, the review-loop node fails.
4. Commit current changes, resolve and snapshot the approval policy, push, create or update the change request, request every eligible policy identity as reviewer, and pause.
5. If eligible approvals satisfy every policy quorum:
   - Reset MR approvals.
   - Mark the review-loop node `SUCCESS`.
   - Continue to the node's outgoing edges.
6. If an eligible policy identity provides an `@kyron` comment:
   - Store the feedback event.
   - Increment `REVIEW_ITERATION`.
   - If the new iteration exceeds `max_iterations`, fail the review-loop node with `MAX_REVIEW_ITERATIONS_REACHED`.
   - Invoke `revision_workflow_id` for iteration 2 and later.
   - If `revision_workflow_id` is absent, invoke `initial_workflow_id` again.
   - Provide the feedback through mapped public input variables.
   - After the child succeeds, commit, push, and pause again.
7. Repeat until approval or iteration limit.

Every child execution receives a new invocation record and unique invocation path. No graph node is mutated back to `PENDING`; the repeated work is represented by additional child invocations.

### Review-loop output behavior

A review-loop node may optionally export outputs from the last successful child invocation:

```json
{
  "output_mapping": {
    "SUMMARY": "IMPLEMENTATION_SUMMARY"
  }
}
```

Only the latest successful child invocation is used.

---

# 7. Workflow Validation

Validation occurs server-side before saving a workflow and again when triggering a run.

## 7.1 Structural Validation

1. Workflow ID matches the identifier regex.
2. Filename matches workflow ID.
3. Workflow version is supported.
4. Node IDs are unique.
5. Edge IDs are unique.
6. Every edge references existing source and target nodes.
7. At least one start node exists.
8. Every node is reachable from a start node.
9. The workflow graph is acyclic.
10. Join mode is `and` or `or`.
11. Required node configuration fields exist.
12. Node timeouts and iteration limits are positive and within configured maximums.
13. Script paths are relative and do not contain traversal outside the repository.
14. Variable names and workflow input/output names match the identifier regex.

## 7.2 Sub-Workflow Validation

When saving or triggering:

1. Every referenced workflow file exists in the same commit snapshot.
2. The complete workflow-reference graph is acyclic.
3. The maximum reference depth does not exceed `max_subworkflow_depth`.
4. All required child inputs are mapped or have defaults.
5. Every mapped child output exists in the child's output definition.
6. A child workflow cannot reference itself directly or indirectly.
7. A `review_loop` initial and revision workflow must not contain a `human_feedback` or `review_loop` node by default.

The last rule prevents nested review pauses inside a review-loop child. It may be relaxed later, but version 1 rejects it to keep checkpoint ownership unambiguous.

## 7.3 Condition Validation

Unknown condition types or operators are validation errors. They must never default to true.

## 7.4 Save-Time and Run-Time Validation

Save-time validation validates the proposed workflow against the current default branch.

Run-time validation validates the root workflow and all transitive references at the exact pinned commit. A run must not start if the workflow bundle cannot be resolved or validated.

---
# 8. Graph Execution Semantics

## 8.1 Acyclic Graph Model

Every individual workflow definition is a DAG. Reusable composition is provided through `subworkflow`, and repetition is provided through `review_loop`.

This gives the scheduler a finite set of logical node executions for each invocation and avoids ambiguous back-edge state.

## 8.2 Edge Conditions

Supported conditions:

### Exit code

```json
{
  "type": "exit_code",
  "operator": "equals",
  "value": 0
}
```

Operators:

- `equals`
- `not_equals`
- `greater_than`
- `greater_than_or_equal`
- `less_than`
- `less_than_or_equal`

### Output contains

```json
{
  "type": "output_contains",
  "value": "SUCCESS",
  "stream": "stdout"
}
```

`stream` is `stdout`, `stderr`, or `combined`, defaulting to `stdout`.

### File exists

```json
{
  "type": "file_exists",
  "value": "reports/summary.json"
}
```

The final resolved path must remain inside the worktree.

### Public variable comparison

```json
{
  "type": "variable",
  "name": "FINAL_TEST_STATUS",
  "operator": "equals",
  "value": "0"
}
```

Credential values cannot be used in conditions.

## 8.3 Condition Evaluation

Conditions are evaluated exactly once when their source node reaches a terminal status. The result is persisted in `edge_evaluations`.

For a successful or `allow_failure` process node, conditions use the actual exit code and output.

For a skipped source node:

- Its outgoing edges are evaluated as false unless the edge has no condition and the workflow setting `propagate_skips` is explicitly enabled.
- Version 1 defaults to false propagation to avoid surprising execution.

## 8.4 AND Join

A node with `join: "and"` waits until all predecessors are terminal and all incoming edges have been evaluated.

Then:

- If at least one incoming edge is true, execute the node.
- If all incoming edges are false, mark the node `SKIPPED`.

This matches branch-merging behavior where some predecessor branches may intentionally not select the node.

## 8.5 OR Join

A node with `join: "or"` becomes ready after the first true incoming edge.

Rules:

- The node executes once.
- Later true edges do not cause another execution.
- Other nodes in an already-running wave are not cancelled merely because the OR target has become ready.
- The OR target is scheduled in the next wave, not injected into a wave already in progress.

This produces deterministic wave boundaries.

## 8.6 Execution Waves

The scheduler groups currently ready ordinary nodes into a wave.

A wave may contain:

- Bash nodes.
- Script nodes.
- Prompt nodes.

Composite and pause-capable nodes are executed as control boundaries, one at a time:

- Sub-workflow nodes.
- Human-feedback nodes.
- Review-loop nodes.

A sub-workflow owns its child invocation's internal waves and Git checkpoints. Executing a sub-workflow as an isolated control boundary prevents a child checkpoint commit from accidentally staging changes made by a parallel sibling node.

### Wave start

Before starting a wave:

1. Verify that the worktree is clean.
2. Resolve `git rev-parse HEAD`.
3. Store the value as `execution_waves.start_commit_sha`.
4. Create node attempts and atomically mark the wave and nodes `RUNNING`.

### Parallel execution

All nodes in the wave are launched concurrently.

They share one worktree. This is an intentional trusted-workflow design. The workflow author must only place nodes in parallel when their commands and file changes do not conflict.

### Wave success

A wave succeeds only when every non-`allow_failure` node succeeds.

After all processes complete:

1. Persist each node's attempt result and output paths.
2. Update public node-output variables.
3. Evaluate and persist outgoing edge conditions.
4. If `auto_commit_after_wave` is true, stage all changes and create one wave checkpoint commit if needed.
5. Push is not required after every wave, but the local checkpoint commit must exist.
6. Record the resulting HEAD as `end_commit_sha`.
7. Mark wave `SUCCESS`.

### Wave failure

When any non-allowed node fails:

1. Cancel remaining tasks in the wave.
2. Terminate all process groups belonging to those tasks.
3. Wait until all process tasks terminate.
4. Persist all completed attempt results.
5. Mark unsuccessful or cancelled attempts accordingly.
6. Reset the worktree:

```bash
git reset --hard <wave.start_commit_sha>
git clean -fd
```

7. Mark the wave `FAILED` and then `ROLLED_BACK` after reset succeeds.
8. Mark the run `FAILED`.
9. Do not evaluate outgoing edges from the failed wave.

The complete wave is the resume unit. Nodes in the same failed wave that had succeeded are rerun because their shared filesystem effects were rolled back.

## 8.7 Node Failure and `allow_failure`

If `allow_failure=true`:

- The node execution is marked `SUCCESS_WITH_FAILURE` in metadata but uses the database status `SUCCESS` for scheduling.
- Its actual non-zero exit code remains available.
- Edge conditions use the actual exit code.
- The engine writes an explicit warning log.

## 8.8 Deadlock and Completion Detection

The invocation completes only when every reachable node is in a terminal state:

- `SUCCESS`
- `SKIPPED`

If no node is ready but non-terminal nodes remain, the invocation fails with `GRAPH_DEADLOCK`. It must never be marked completed silently.

---

# 9. Workflow Bundle Snapshot and Exact Repository Revision

## 9.1 Trigger-Time Revision Resolution

The trigger endpoint must perform the following under the per-project Git lock:

```bash
git fetch origin --prune
git rev-parse origin/<base_ref>
```

The resulting 40-character SHA becomes `base_commit_sha`.

Workflow paths are indexed directly from that commit, not from a mutable checked-out
working directory. The resolved root path is then read with:

```bash
git show <base_commit_sha>:.workflowEngine/<resolved folders>/<workflow_id>.json
```

All referenced child workflows are resolved using the same SHA.

## 9.2 Workflow Bundle Snapshot

The snapshot is a JSON object:

```json
{
  "snapshot_version": 1,
  "base_commit_sha": "012345...",
  "root_workflow_id": "implement_and_review",
  "project_pi": {
    "provider": "anthropic",
    "model": "anthropic/claude-sonnet-4-5",
    "skill": ".agents/skills/implementation/SKILL.md"
  },
  "workflows": {
    "implement_and_review": { "...": "full workflow JSON" },
    "implement_changes": { "...": "full workflow JSON" },
    "revise_from_feedback": { "...": "full workflow JSON" },
    "test_and_validate": { "...": "full workflow JSON" }
  },
  "reference_graph": {
    "implement_and_review": [
      "implement_changes",
      "revise_from_feedback",
      "test_and_validate"
    ]
  }
}
```

The snapshot contains no credentials or access tokens. It includes the project Pi
defaults in effect at trigger time so later project configuration changes cannot alter
queued, resumed, or feedback-continuation behavior.

Resume and feedback continuation always use this snapshot, never live repository workflow files.

## 9.3 Worktree Creation

After the run is recorded as `QUEUED`, execution creates:

```bash
git worktree add \
  -b workflow/<workflow_id>_<run_short_id> \
  /var/workflowengine/worktrees/<run_id> \
  <base_commit_sha>
```

This guarantees that code and workflow definitions correspond to the same pinned commit.

## 9.4 Run Branch Rules

Branch format:

```text
workflow/<root_workflow_id>_<first-8-run-hex>
```

Requirements:

- Sanitize workflow ID even though validation already restricts it.
- Verify no local or remote branch collision.
- Store branch name before any push.
- Never force-push unless explicitly required by a recovery operation and safe against the known run branch.

## 9.5 Git Identity

Configure identity in the worktree:

```bash
git config user.name "Workflow Engine"
git config user.email "workflow-engine@noreply.local"
```

Optionally add trailers to commit messages:

```text
Workflow-Run: <run_id>
Triggered-By: <user email>
```

---

# 10. Variables, Inputs, Outputs, and Credentials

## 10.1 Two Separate Contexts

The implementation must maintain two different contexts.

### Persistable public context

May contain:

- Workflow variables.
- Trigger inputs.
- Built-in run values.
- Node output values.
- Review feedback.
- Child workflow input/output mappings.

This context may be stored in `workflow_runs.public_context`, invocation rows, and node output metadata.

### Ephemeral secret environment

Contains decrypted credential values.

Rules:

- Created immediately before a subprocess starts.
- Used only for that subprocess environment.
- Never stored in any database field.
- Never added to public variable expansion.
- Never serialized to logs or output metadata.
- Local references are deleted after process creation.

All credentials for the triggering user are injected into every subprocess, as requested for the trusted internal version.

## 10.2 Variable Priority

Public variables are merged in this order, lowest to highest priority:

1. Workflow variable defaults.
2. Workflow invocation inputs.
3. Built-in run variables.
4. Parent-to-child mapped values.
5. Review-loop feedback variables.
6. Node output variables.
7. Current-node built-ins.

A reserved built-in name cannot be overridden by workflow JSON.

## 10.3 Built-In Variables

| Variable | Meaning |
|---|---|
| `RUN_ID` | Full UUID |
| `RUN_ID_SHORT` | First 8 hex characters |
| `ROOT_WORKFLOW_ID` | Root workflow ID |
| `WORKFLOW_ID` | Current invocation workflow ID |
| `WORKFLOW_NAME` | Current workflow name |
| `INVOCATION_ID` | Current invocation UUID |
| `INVOCATION_PATH` | Stable invocation path |
| `PROJECT_ID` | Internal project UUID |
| `PROJECT_NAME` | Display name |
| `BASE_REF` | Selected base ref |
| `BASE_COMMIT_SHA` | Exact pinned SHA |
| `BRANCH` | Run branch |
| `WORKTREE_PATH` | Absolute worktree path |
| `RUN_DATA_PATH` | Absolute run data path |
| `USER_NAME` | Triggering user display name |
| `USER_EMAIL` | Triggering user email |
| `GITLAB_USER_ID` | Triggering user's GitLab ID as string |
| `GITLAB_USERNAME` | Triggering user's username |
| `NODE_ID` | Current node ID |
| `NODE_LABEL` | Current node label |
| `NODE_PATH` | Current fully scoped node path |
| `WAVE_INDEX` | Current invocation wave index |
| `REVIEW_ITERATION` | Current review-loop iteration, when applicable |
| `FEEDBACK` | Latest feedback text |
| `FEEDBACK_TYPE` | `comment` or `approval` |
| `FEEDBACK_AUTHOR` | GitLab username or frontend display name |

## 10.4 Node Output Variables

After a process node completes:

| Variable | Meaning |
|---|---|
| `NODE_<id>_EXIT_CODE` | Actual exit code |
| `NODE_<id>_STDOUT` | Stdout up to configured byte limit |
| `NODE_<id>_STDERR` | Stderr up to configured byte limit |
| `NODE_<id>_STDOUT_PATH` | Relative output-file path |
| `NODE_<id>_STDERR_PATH` | Relative output-file path |

If output exceeds `max_output_variable_bytes`, the value is truncated and the path remains available.

Scoped child output names are mapped explicitly by the parent node to avoid collisions.

## 10.5 Variable Expansion

```python
VARIABLE_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

def expand_public_variables(template: str, context: Mapping[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in context:
            raise UnresolvedVariableError(name)
        return str(context[name])
    return VARIABLE_PATTERN.sub(replace, template)
```

Unlike the previous design, unresolved variables are errors by default. Silently leaving `${VAR}` can hide workflow mistakes and accidentally defer expansion to the shell.

A Bash node may opt into shell-native variables by writing `$VAR` without braces. Credential environment variables are available only this way.

## 10.6 Environment Construction

```python
async def build_ephemeral_process_env(
    user_id: UUID,
    public_context: dict[str, Any],
) -> dict[str, str]:
    encrypted = await credential_repo.list_for_user(user_id)
    decrypted: dict[str, str] = {}
    try:
        for credential in encrypted:
            decrypted[credential.key_name] = decrypt(credential.encrypted_value)

        env = sanitized_base_environment()
        env.update({key: str(value) for key, value in public_context.items()})
        env.update(decrypted)
        return env
    finally:
        decrypted.clear()
```

The returned environment remains in process memory for process creation, but it is never persisted or logged.

## 10.7 Secret Redaction

Before storing any exception, command description, API error, stdout line, stderr line, Pi event, or public output preview:

- Redact known credential values currently loaded in memory.
- Redact project access token values when a Git/GitLab operation is active.
- Redact authenticated URLs.
- Redact common token patterns such as `glpat-...` and provider keys.

No unredacted process output is persisted. The engine must log a command summary without dumping the full environment.

---

# 11. Git Checkpoints and Resume-from-Failure

## 11.1 Resume Guarantee

The system provides this guarantee:

> A failed, interrupted, or explicitly cancelled run resumes from its latest safe Git checkpoint. A process wave is re-executed as a whole, and enclosing control nodes are reset so nested sub-workflows can continue.

The system does not promise exactly-once external side effects. Trusted workflows should avoid irreversible external actions or make them idempotent.

## 11.2 Why Resume Uses Waves

Parallel nodes share one worktree. If one node fails after another has modified files, it is not safe to preserve only the successful sibling's filesystem changes without a more complex merge model.

Therefore:

- Every wave starts from a known Git commit.
- All filesystem changes from a failed wave are rolled back.
- All nodes in the wave run again on resume.
- Earlier successful waves remain committed and are not repeated.

## 11.3 Failure Recording

On failure, persist:

- Failed wave ID.
- Wave start SHA.
- Node attempt results.
- Failure type and sanitized message.
- Current invocation and node IDs.
- Worktree rollback result.

The run transitions to `FAILED` only after rollback succeeds. If rollback itself fails, set `error_type=WORKTREE_RECOVERY_FAILED` and block resume until an operator repairs the worktree.

An unexpected in-process coordinator exception must not leave a run owned only in memory. In a
fresh database session, transition an active `RUNNING` or `RESUMING` run to `INTERRUPTED`, mark
any active wave, node, and attempt interrupted, and append a sanitized engine event. Do not use
`FAILED` when the worktree rollback outcome is unknown.

## 11.4 Resume Algorithm

```python
async def resume_run(run_id: UUID, current_user: User) -> None:
    run = await lock_run_for_update(run_id)

    if run.status not in {"FAILED", "INTERRUPTED"}:
        raise InvalidState("Run is not resumable")

    assert_worktree_exists(run.worktree_path)
    assert_snapshot_valid(run.workflow_bundle_snapshot)

    failed_wave = await wave_repo.get_resume_wave(run_id)
    if failed_wave is None:
        raise InvalidState("No resumable wave found")

    await atomic_transition(
        run_id,
        expected={"FAILED", "INTERRUPTED"},
        new="RESUMING",
    )

    await terminate_any_tracked_processes(run_id)
    await reset_worktree(run.worktree_path, failed_wave.start_commit_sha)

    await wave_repo.prepare_new_attempt(failed_wave.id)
    await node_repo.prepare_wave_nodes_for_retry(failed_wave.id)

    task = asyncio.create_task(guarded_continue_run(run_id, failed_wave.id))
    register_task(run_id, task)
```

Pending feedback and final-publication operations are durable recovery boundaries. Resume resets
the worktree to their stored `current_head_sha` and continues the pending external transition
without replaying successful waves. Change-request creation first reconciles by the run's unique
source branch; after an ambiguous create response it reconciles again before retrying. Persist the
change-request identifier before requesting reviewers.

## 11.5 Interrupted Runs

On backend startup:

- `QUEUED`: leave queued and schedule again.
- `RUNNING`: mark `INTERRUPTED`.
- `RESUMING`: mark `INTERRUPTED`.
- Waves in `RUNNING`: mark `INTERRUPTED`.
- Node attempts in `RUNNING`: mark `INTERRUPTED`.
- `AWAITING_FEEDBACK`: leave unchanged.
- Terminal runs: leave unchanged.

The same interruption transition is applied immediately when an individual in-process run worker
crashes while the backend remains healthy; it does not wait for a container restart.

Before marking a run interrupted, the startup process should verify that no other backend instance is expected. The version-1 deployment guarantees this through the one-worker, one-backend-container rule.

## 11.6 Resume after Human Feedback

Human feedback is not treated as failure resume.

The checkpoint transition from `AWAITING_FEEDBACK` to `RUNNING` creates a new continuation task. For a review loop, feedback creates a new child invocation. For a standalone feedback node, the node becomes successful and normal graph scheduling continues.

## 11.7 Resume and Node Attempts

Existing attempt rows are never overwritten. A resumed wave increments each node execution's `current_attempt` and inserts a new `node_attempts` row.

Output paths include attempt numbers:

```text
run_data/<run_id>/outputs/<node_path_safe>/attempt-1/stdout.log
run_data/<run_id>/outputs/<node_path_safe>/attempt-2/stdout.log
```

---
# 12. Authentication and User Resolution

## 12.1 Caddy-Managed OAuth

Authentication is handled by Caddy and the auth service.

Flow:

1. Browser requests the application.
2. Caddy performs a `forward_auth` request to `/auth/verify`.
3. If no valid session exists, the auth service redirects to GitLab OAuth.
4. After callback, the auth service creates a signed HTTP-only session cookie.
5. On authenticated requests, the auth service returns trusted identity headers.
6. Caddy copies these headers to the backend request.
7. The backend upserts the user.

Cookie requirements:

- `HttpOnly`
- `Secure`
- `SameSite=Lax`
- Explicit expiration and server-side/signature validation
- Key rotation support through a current and previous signing key

## 12.2 Trusted Header Handling

Caddy must remove incoming versions of all trusted headers before `forward_auth` and only set values returned by the auth service.

The backend must not be exposed directly on a public or internal host port. It is reachable only on the Docker network.

## 12.3 Backend Dependency

```python
async def resolve_current_user(request: Request, session: AsyncSession) -> User:
    email = request.headers.get("X-Token-User-Email")
    name = request.headers.get("X-Token-User-Name")
    avatar = request.headers.get("X-Token-User-Avatar")
    gitlab_id_raw = request.headers.get("X-Token-GitLab-User-Id")
    gitlab_username = request.headers.get("X-Token-GitLab-Username")

    if not email or not gitlab_id_raw or not gitlab_username:
        raise HTTPException(401, "Missing trusted authentication headers")

    try:
        gitlab_id = int(gitlab_id_raw)
    except ValueError as exc:
        raise HTTPException(401, "Invalid GitLab user ID") from exc

    return await users.upsert_from_auth(
        email=email,
        display_name=name or gitlab_username,
        avatar_url=avatar,
        gitlab_user_id=gitlab_id,
        gitlab_username=gitlab_username,
    )
```

## 12.4 Project Authorization Model

A global system administrator manages user activation and system-administrator assignment.
Every non-system operation is authorized through active project membership and one or more
project-scoped roles. Built-in roles cover project administration, workflow authoring,
operation, approval, and read-only access; project administrators may also create custom
roles from the fixed permission catalog.

Workflow gates add a second authorization condition: the actor must have `gate.respond`
and must appear in the open gate's immutable eligibility snapshot. The snapshot comes from
the selected reusable approval policy and may include roles, named users, multiple
requirements, and per-requirement quorums. Whether the initiator may approve and whether
approvers must be distinct across requirements are policy settings.

## 12.5 WebSocket Authentication

Caddy authenticates the initial upgrade request. FastAPI reads the same trusted headers and verifies that the user exists.

The backend resolves the run's project and requires `run.view` before accepting the
WebSocket upgrade. Project membership therefore controls live-output visibility as well as
the REST run and report endpoints.

## 12.6 Webhook Authentication

At minimum, verify the configured `X-Gitlab-Token` using constant-time comparison.

When the GitLab instance supports Standard Webhooks signing, support optional verification of:

- `webhook-id`
- `webhook-timestamp`
- `webhook-signature`

The signed message format is:

```text
<webhook-id>.<webhook-timestamp>.<raw-request-body>
```

The system may initially use `X-Gitlab-Token`, but webhook delivery idempotency must still be implemented.

---

# 13. Credential Management

## 13.1 Encryption

Use Fernet with an environment-provided key.

```python
from cryptography.fernet import Fernet

cipher = Fernet(os.environ["CREDENTIALS_ENCRYPTION_KEY"])

def encrypt_secret(value: str) -> bytes:
    return cipher.encrypt(value.encode("utf-8"))

def decrypt_secret(value: bytes) -> str:
    return cipher.decrypt(value).decode("utf-8")
```

The encryption key is not stored in PostgreSQL, source control, or container images.

## 13.2 API Rules

- Create and update endpoints receive plaintext over authenticated TLS.
- Plaintext is encrypted before database commit.
- Credential values are never returned.
- Lists return key name, description, and timestamps only.
- Deletion permanently removes the row.
- Credential values are never written to application logs.

## 13.3 Execution Rules

At node process start:

1. Load the triggering user's encrypted credentials.
2. Decrypt them in memory.
3. Build an ephemeral environment.
4. Build an in-memory exact-value redactor from the decrypted values.
5. Start the subprocess.
6. Redact known secret values before any stdout/stderr line is written to disk, sent over WebSocket, or copied into a public output variable.
7. Clear temporary dictionaries, redaction values, and local references after process completion.

Credential values are not part of `${...}` expansion. They are accessed through normal environment-variable syntax inside the process, for example:

```bash
echo "$ANTHROPIC_API_KEY"  # Technically possible, but trusted workflows must not log it.
```

## 13.4 Project Access Token

The per-project token is decrypted only for a Git or GitLab operation.

For Git pushes, prefer a temporary `GIT_ASKPASS` script or temporary credential helper rather than embedding the token directly in the process arguments or permanently changing the remote URL.

Example approach:

```python
with temporary_git_askpass(username="oauth2", password=token) as env_patch:
    env = {**sanitized_base_environment(), **env_patch}
    await run_exec(
        ["git", "push", "origin", branch_name],
        cwd=worktree_path,
        env=env,
    )
```

If an authenticated URL is used as a fallback, it must never be logged or stored as the repository remote.

---

# 14. Backend API Specification

## 14.1 Conventions

- Prefix: `/api`.
- JSON request and response bodies unless otherwise stated.
- UTC ISO 8601 timestamps.
- UUIDs represented as strings.
- Pagination: `page`, `page_size`, maximum `200`.
- Error shape:

```json
{
  "detail": "Human-readable message",
  "code": "MACHINE_READABLE_CODE",
  "context": {}
}
```

- State-changing endpoints use database transactions and atomic expected-state checks.

## 14.2 Health and Auth

```text
GET /api/health
GET /api/auth/me
```

Health response:

```json
{
  "status": "ok",
  "database": "ok",
  "worker_mode": "in_process_single_worker"
}
```

## 14.3 Projects

```text
GET    /api/projects
POST   /api/projects
GET    /api/projects/{project_id}
DELETE /api/projects/{project_id}
PUT    /api/projects/{project_id}/token
PUT    /api/projects/{project_id}/pi
POST   /api/projects/{project_id}/fetch
POST   /api/projects/{project_id}/validate
GET    /api/projects/{project_id}/workflows
```

### Register project

```json
{
  "name": "Example project",
  "git_url": "https://code.example.com/group/repo.git",
  "gitlab_project_id": 123,
  "access_token": "glpat-...",
  "default_branch": "main",
  "pi": {
    "provider": "anthropic",
    "model": "anthropic/claude-sonnet-4-5",
    "skill": ".agents/skills/implementation/SKILL.md"
  }
}
```

Registration validation:

1. Verify HTTPS URL.
2. Verify GitLab project through API.
3. Verify token can read repository metadata.
4. Verify token can create or update a temporary branch if a non-destructive capability test is enabled.
5. Verify token represents a bot user if approval reset is required.
6. Clone repository.
7. Store encrypted token only after validation succeeds.

## 14.4 Credentials

```text
GET    /api/credentials
POST   /api/credentials
PUT    /api/credentials/{credential_id}
DELETE /api/credentials/{credential_id}
```

Credential update always requires a new plaintext value. The old value cannot be retrieved.

## 14.5 Workflow Definitions

```text
GET    /api/projects/{project_id}/workflows
GET    /api/projects/{project_id}/workflows/{workflow_id}
POST   /api/projects/{project_id}/workflows/validate
PUT    /api/projects/{project_id}/workflows/{workflow_id}
DELETE /api/projects/{project_id}/workflows/{workflow_id}
GET    /api/projects/{project_id}/workflows/{workflow_id}/references
```

### Validate workflow

Request:

```json
{
  "workflow": { "...": "workflow JSON" },
  "proposed_related_workflows": {}
}
```

Response:

```json
{
  "valid": false,
  "errors": [
    {
      "path": "nodes[2].config.workflow_id",
      "code": "MISSING_SUBWORKFLOW",
      "message": "Workflow 'validate_code' does not exist"
    }
  ],
  "warnings": []
}
```

### Save workflow

Saving creates a workflow-definition worktree and MR. It does not modify the default branch directly.

Response:

```json
{
  "branch_name": "workflow_definition/full_review_ab12cd34",
  "mr_iid": 42,
  "mr_url": "https://..."
}
```

## 14.6 Trigger Workflow

```text
POST /api/projects/{project_id}/workflows/{workflow_id}/runs
```

Request:

```json
{
  "base_ref": "main",
  "inputs": {
    "TASK": "Add validation to the import endpoint"
  }
}
```

Behavior:

1. Fetch repository.
2. Resolve exact SHA.
3. Resolve and validate workflow bundle.
4. Validate trigger inputs.
5. Insert run as `QUEUED` with snapshot.
6. Commit transaction.
7. Register the background task.
8. If task registration fails, leave the run queued and let startup/queue reconciliation schedule it.

Response:

```json
{
  "run_id": "uuid",
  "status": "QUEUED",
  "base_commit_sha": "012345..."
}
```

## 14.7 Runs

```text
GET  /api/runs
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/graph
GET  /api/runs/{run_id}/logs
GET  /api/runs/{run_id}/nodes/{node_execution_id}
GET  /api/runs/{run_id}/nodes/{node_execution_id}/output
POST /api/runs/{run_id}/cancel
POST /api/runs/{run_id}/resume
POST /api/runs/{run_id}/approve
POST /api/runs/{run_id}/feedback
```

### Run list filters

- `project_id`
- `root_workflow_id`
- `status`
- `triggered_by`
- `created_after`
- `created_before`

### Output endpoint

Query:

- `attempt`
- `stream=stdout|stderr|pi_events`
- Optional byte range or `tail_lines`.

The endpoint must not read arbitrary paths supplied by the client.

## 14.8 Approve

```text
POST /api/runs/{run_id}/approve
```

Rules:

1. Current user must equal `run.triggered_by`.
2. Run must atomically transition from `AWAITING_FEEDBACK` to `RUNNING`.
3. Record feedback event.
4. Reset GitLab approval.
5. Post a traceability comment.
6. Continue the run.

If approval reset fails, revert the run to `AWAITING_FEEDBACK` and return an error. A fresh final approval is a required invariant, so the system fails closed.

## 14.9 Feedback

```text
POST /api/runs/{run_id}/feedback
```

Request:

```json
{
  "message": "Please also update the error response documentation."
}
```

Rules:

- Current user must equal `run.triggered_by`.
- Message must be non-empty and within configured length.
- Post the comment to GitLab for traceability.
- Continue the standalone feedback node or review loop.

## 14.10 WebSocket

```text
WS /api/ws/runs/{run_id}/logs?after_id=<last_engine_log_id>
```

Messages:

```json
{
  "type": "log",
  "sequence": 1234,
  "run_id": "...",
  "invocation_path": "root/review/initial[1]",
  "node_path": "root/review/initial[1]/implement",
  "timestamp": "...",
  "level": "INFO",
  "source": "engine",
  "message": "Node started"
}
```

Process output events use a per-process sequence and are live-only. The client can fetch complete output from files after reconnect.

Heartbeat:

```json
{
  "type": "heartbeat",
  "timestamp": "..."
}
```

Terminal event:

```json
{
  "type": "run_status",
  "status": "COMPLETED"
}
```

## 14.11 GitLab Webhook

```text
POST /api/webhook/gitlab
```

The raw body must be retained until authentication/signature verification completes.

Webhook handling is detailed in Section 17.

---

# 15. Engine Lifecycle

## 15.1 Trigger Registration

```python
active_tasks: dict[UUID, asyncio.Task] = {}
run_semaphore = asyncio.Semaphore(MAX_CONCURRENT_RUNS)

async def schedule_run(run_id: UUID) -> None:
    if run_id in active_tasks and not active_tasks[run_id].done():
        return

    async def guarded() -> None:
        try:
            async with run_semaphore:
                await execute_or_continue_run(run_id)
        finally:
            active_tasks.pop(run_id, None)
            active_processes.pop(run_id, None)

    task = asyncio.create_task(guarded(), name=f"workflow-run-{run_id}")
    active_tasks[run_id] = task
```

Use an asyncio lock around task-registration checks even with one event loop so concurrent endpoint and webhook calls cannot register duplicate tasks.

## 15.2 Queue Reconciliation

A periodic task runs every minute:

1. Select old `QUEUED` runs that have no active task.
2. Schedule them in queue order.
3. Do not create a second task for an already active run.

This closes the transaction-to-task-registration gap.

## 15.3 Initial Execution

```python
async def execute_new_run(run_id: UUID) -> None:
    run = await runs.get(run_id)
    project = await projects.get(run.project_id)

    worktree = await git_manager.create_run_worktree(
        project=project,
        run_id=run.id,
        workflow_id=run.root_workflow_id,
        base_commit_sha=run.base_commit_sha,
    )

    await runs.set_worktree(
        run.id,
        branch_name=worktree.branch,
        worktree_path=worktree.path,
        run_data_path=worktree.run_data_path,
        current_head_sha=run.base_commit_sha,
    )

    root_invocation = await invocations.create_root(run)
    await runs.transition(run.id, expected="QUEUED", new="RUNNING")
    await execute_invocation(root_invocation.id)
    await finalize_run(run.id)
```

## 15.4 Invocation Scheduler

```python
async def execute_invocation(invocation_id: UUID) -> InvocationResult:
    invocation = await invocations.get(invocation_id)
    workflow = snapshot.get_workflow(invocation.run_id, invocation.workflow_id)

    await invocations.mark_running(invocation_id)
    scheduler = DagScheduler(workflow)
    await scheduler.restore_from_database(invocation_id)

    while True:
        terminal = await scheduler.is_terminal()
        if terminal:
            break

        ready = await scheduler.next_ready_nodes()
        if not ready:
            raise GraphDeadlockError(invocation.invocation_path)

        control_nodes = [
            n for n in ready
            if n.type in {"subworkflow", "human_feedback", "review_loop"}
        ]
        if control_nodes:
            if len(ready) != 1:
                # Run any ready process nodes first. Composite/control nodes start
                # only after the preceding wave has a durable Git checkpoint.
                ready = [n for n in ready if n not in control_nodes]
            else:
                await execute_control_node(invocation, control_nodes[0])
                continue

        await execute_wave(invocation, ready)

    outputs = resolve_workflow_outputs(workflow, invocation.public_context)
    await invocations.mark_success(invocation_id, outputs)
    return InvocationResult(outputs=outputs)
```

If multiple control nodes become ready simultaneously, execute them in deterministic node-ID order, one at a time. This prevents multiple simultaneous MR checkpoints for one run.

## 15.5 Finalization

On successful root invocation:

1. Commit final changes if any.
2. Push the run branch.
3. Create the MR if it does not exist.
4. Ensure the triggering user is assigned as the default final reviewer when no active gate supplies a reviewer set.
5. Store final HEAD SHA.
6. Mark run `COMPLETED`.
7. Publish terminal status event.
8. Keep worktree and run output until MR merge/close cleanup.

The final change request remains unapproved. Repository branch-protection policy determines
which fresh provider approvals are required for merge.

---
# 16. Subprocess Execution, Cancellation, and Logging

## 16.1 Process Groups

Every subprocess starts in a new process session:

```python
process = await asyncio.create_subprocess_exec(
    *cmd,
    cwd=cwd,
    env=env,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    start_new_session=True,
)
```

For shell nodes, execute `/bin/bash -lc <command>` through `create_subprocess_exec` instead of `create_subprocess_shell` where possible.

Track process groups by run and node attempt:

```python
active_processes: dict[UUID, dict[UUID, int]]
# run_id -> node_attempt_id -> process group ID
```

## 16.2 Cancellation Escalation

```python
async def terminate_process_group(pgid: int, grace_seconds: float = 10.0) -> None:
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        await wait_for_process_group_exit(pgid, timeout=grace_seconds)
    except asyncio.TimeoutError:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
```

Cancelling a run:

1. Atomically set `cancel_requested_at`.
2. Kill all active process groups.
3. Cancel the run task.
4. Wait for cleanup.
5. Mark active attempts and waves cancelled.
6. Mark run `CANCELLED`.
7. If an MR exists, keep worktree until MR closes unless the user explicitly chooses cleanup.
8. Retain the worktree and run data so an authorized operator may explicitly resume. Normal
   retention cleanup may remove them later.

## 16.3 Timeout Handling

A timeout is a node failure with `error_type=TIMEOUT`.

On timeout:

1. Terminate process group with escalation.
2. Drain or close output streams.
3. Close output files.
4. Persist partial output.
5. Fail and roll back the wave.

## 16.4 Output Files

Layout:

```text
run_data/<run_id>/
├── manifest.json
├── outputs/
│   └── <safe-node-path>/
│       └── attempt-<n>/
│           ├── stdout.log
│           ├── stderr.log
│           └── pi_events.jsonl
└── artifacts/
```

`manifest.json` contains only non-secret metadata and output paths.

## 16.5 Streaming Implementation

Read stdout and stderr concurrently. Decode with UTF-8 and replacement for malformed bytes. Apply the attempt's in-memory secret redactor before writing, broadcasting, or buffering each decoded line.

Do not keep unbounded output in memory. Maintain only:

- A bounded preview buffer for public output variables.
- A bounded recent-line buffer for live UI convenience.
- Full output in files.

Pseudo-implementation:

```python
async def copy_stream(stream, file, source, broadcaster, preview, redactor):
    while chunk := await stream.readline():
        text = chunk.decode("utf-8", errors="replace")
        safe_text = redactor.redact(text)
        await file.write(safe_text)
        preview.append_bounded(safe_text)
        await broadcaster.publish_process_line(
            source=source,
            line=safe_text.rstrip("\n"),
        )
```

## 16.6 Engine Logs

Every important transition writes a structured engine log and broadcasts it:

- Run queued, started, paused, resumed, completed, failed, cancelled.
- Worktree created and cleaned.
- Wave created, started, committed, rolled back.
- Node attempt started and finished.
- Child invocation started and finished.
- Review iteration started.
- Feedback accepted or ignored.
- MR created, pushed, approval reset.
- Startup interruption recovery.

Do not log:

- Process environments.
- Credential values.
- Authenticated Git URLs.
- Raw OAuth sessions.
- Full HTTP authorization headers.

## 16.7 In-Memory Log Broadcaster

The broadcaster is live-only and may drop process-output lines for slow subscribers. Full output remains available on disk.

Each subscriber queue has a finite maximum. On overflow:

1. Drop the oldest live process-output event.
2. Insert a synthetic event indicating dropped messages.
3. Never block workflow execution on a WebSocket client.

## 16.8 WebSocket Reconnection

To avoid a database-log race:

1. Subscribe to the live broadcaster.
2. Read engine logs after `after_id` from PostgreSQL.
3. Send historical logs.
4. Drain queued live events, discarding duplicate engine events by sequence.
5. Continue live streaming.

Process-output history is loaded through the output endpoint, not replayed through the WebSocket.

---

# 17. GitLab Integration

## 17.1 Project Access Token Requirements

Each project uses its own GitLab project access token.

Required capabilities:

- Read repository.
- Write repository.
- Use GitLab API.
- Create merge requests.
- Assign reviewers.
- Post notes.
- Reset approvals.

The reset-approvals endpoint is available to bot users with valid project or group tokens. Project registration must verify that the token is suitable.

## 17.2 User Identity

Do not resolve reviewers by searching for email addresses.

The auth service obtains immutable provider user IDs during OAuth. Store provider identities
and use the snapshotted eligible identities directly in `reviewer_ids`.

This avoids failures when email addresses are private or not searchable by the project token.

## 17.3 Create Merge Request

Endpoint:

```text
POST /api/v4/projects/:id/merge_requests
```

Request fields:

```json
{
  "source_branch": "workflow/full_review_ab12cd34",
  "target_branch": "main",
  "title": "Workflow: Full Review",
  "description": "...",
  "reviewer_ids": [12345],
  "remove_source_branch": true
}
```

For an intermediate gate, the reviewer IDs are all eligible GitLab identities in the gate
snapshot. For the final change request, the triggering identity is a default when no gate
reviewer set is supplied.

After creation, store:

- `mr_iid`
- `mr_url`
- the provider-neutral triggering reviewer fields used as the final-review default

## 17.4 Ensure Reviewer Assignment

When an MR already exists, replace its reviewer list with the complete intended gate reviewer set. If necessary, update the MR through:

```text
PUT /api/v4/projects/:id/merge_requests/:merge_request_iid
```

with the complete intended `reviewer_ids` list.

## 17.5 Push and Approval Synchronization

After pushing a commit to an existing MR, GitLab may temporarily report merge status values such as `checking` or `approvals_syncing`.

Before relying on approval state, poll the MR until:

- `detailed_merge_status` is not `checking` or `approvals_syncing`.
- A bounded timeout is reached.

This prevents accepting stale approval state while GitLab processes a new commit.

## 17.6 Accepted Approval Event

GitLab merge-request webhooks distinguish:

- `action: "approval"` — one user added an approval.
- `action: "approved"` — all required approval rules are satisfied.

The engine handles `action: "approval"` and checks the actor's immutable provider identity
against the current gate eligibility snapshot:

```text
payload.user.id in gate.eligible_provider_user_ids
```

The `approved` event may also arrive. It must be treated as a possible duplicate and ignored if the checkpoint already transitioned.

## 17.7 Approval Handling

For a valid approval event:

1. Locate the run by `(project.id, object_attributes.iid)`.
2. Verify run is `AWAITING_FEEDBACK`.
3. Verify `payload.user.id` is eligible for at least one unsatisfied policy requirement.
4. Record the approval without continuing if the complete policy quorum is not yet met.
5. Once the quorum is met, atomically reserve the checkpoint transition and reset approvals:

```text
PUT /api/v4/projects/:id/merge_requests/:merge_request_iid/reset_approvals
```

6. If reset fails, return the run to `AWAITING_FEEDBACK` and record an error.
7. Insert a `feedback_events` row with `event_type=approval`.
8. Mark the waiting node ready to continue.
9. Schedule continuation.

Use the top-level `user` object for the actor.

## 17.8 Comment Feedback Handling

GitLab note webhook requirements:

- `object_kind == "note"`
- `merge_request` exists.
- `object_attributes.system` is not true.
- `object_attributes.note.strip()` begins with `@kyron`, case-insensitive.
- Top-level `user.id` is eligible in the current gate snapshot.

The actor is read from:

```python
payload["user"]["id"]
payload["user"]["username"]
```

The note text is read from:

```python
payload["object_attributes"]["note"]
```

Strip exactly the initial prefix and following whitespace.

Empty feedback after `@kyron` is rejected or ignored with a clear result.

## 17.9 Frontend Feedback Traceability

When an eligible approver uses the frontend:

- Frontend approval posts:

```text
Approved via Workflow Engine by <name>.
The intermediate approval was reset; a fresh GitLab approval is required for final merge.
```

- Frontend feedback posts:

```text
@kyron <feedback text>

Submitted via Workflow Engine by <name>.
```

The engine must avoid processing its own posted `@kyron` comment as a duplicate continuation. Options:

1. Insert the frontend feedback event and transition state before posting the comment; the webhook then sees the run no longer awaiting and is ignored.
2. Also store the returned GitLab note ID and ignore that note explicitly.

Use both for clarity.

## 17.10 Merge and Close Events

Handle:

- `action: "merge"`
- `action: "close"`

Lookup by project ID and MR IID.

If the run is active:

1. Request cancellation.
2. Terminate process groups.
3. Wait for task completion.
4. Mark cancelled if not terminal.

Then:

1. Acquire the project Git lock.
2. Remove the worktree.
3. Prune worktree metadata.
4. Delete local run branch.
5. Remove run data according to retention policy.

Do not delete a worktree while a task is still using it.

## 17.11 Webhook Idempotency

Choose delivery key in this order:

1. `webhook-id`
2. `Idempotency-Key`
3. `X-Gitlab-Event-UUID` plus `X-Gitlab-Webhook-UUID`

Insert `webhook_deliveries` before business processing. A unique-key conflict means the delivery is a retry and should return the previously recorded result or `ignored`.

Atomic run state transitions remain necessary even with delivery deduplication because frontend and GitLab actions may race.

## 17.12 Webhook Handler Outline

```python
@app.post("/api/webhook/gitlab")
async def gitlab_webhook(request: Request):
    raw_body = await request.body()
    verify_gitlab_webhook(request.headers, raw_body)

    delivery_key = get_delivery_key(request.headers)
    delivery = await webhook_repo.try_begin(delivery_key, request.headers)
    if not delivery.created:
        return delivery.previous_result or {"status": "duplicate"}

    payload = json.loads(raw_body)

    try:
        result = await route_gitlab_event(payload)
        await webhook_repo.finish(delivery.id, "PROCESSED", result)
        return result
    except Exception as exc:
        await webhook_repo.finish(delivery.id, "FAILED", sanitized_error(exc))
        raise
```

## 17.13 GitLab Client Error Handling

- Use a shared `httpx.AsyncClient` with connection pooling.
- Set connect, read, write, and pool timeouts.
- Retry idempotent GET requests on network failures and 502/503/504.
- Retry explicitly safe PUT/POST operations only with idempotency-aware logic.
- Respect GitLab rate-limit headers when available.
- Include project ID, endpoint category, and status code in sanitized logs.
- Never include the private token in exception output.

---

# 18. Pi Coding-Agent Integration

## 18.1 Installation

Install the official npm package:

```dockerfile
RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent \
    && pi --version
```

Pin a tested package version in the production Dockerfile rather than always installing latest:

```dockerfile
ARG PI_VERSION=<tested-version>
RUN npm install -g --ignore-scripts \
    "@earendil-works/pi-coding-agent@${PI_VERSION}" \
    && pi --version
```

The chosen version must be recorded in the build metadata and README.

## 18.2 Non-Interactive Modes

Pi supports:

- `pi -p "prompt"` for basic one-shot output.
- `pi --mode json "prompt"` for structured JSONL events.
- `pi --mode rpc` for interactive process integration.

Version 1 uses JSON event-stream mode because each prompt node sends one prompt and waits for completion.

## 18.3 Command Construction

Use argument arrays, not shell string concatenation:

```python
cmd = [
    "pi",
    "--mode", "json",
    "--no-session",
    "--no-approve",
]

if provider:
    cmd += ["--provider", provider]
if model:
    cmd += ["--model", model]

cmd.append(expanded_prompt)
```

Do not use the obsolete `pi --prompt` form.

## 18.4 Project Trust

Non-interactive Pi modes do not display a trust prompt.

The default version-1 behavior is `--no-approve`, which ignores unapproved project-local Pi settings, extensions, and packages. This prevents a repository from silently changing Pi's runtime integration behavior.

A future trusted-project option may permit `--approve`, but it must be explicit in project configuration and not editable by arbitrary workflow input.

## 18.5 JSON Event Parsing

Each stdout line is one JSON object.

The adapter should recognize at least:

- `agent_start`
- `agent_end`
- `turn_start`
- `turn_end`
- `message_start`
- `message_update`
- `message_end`
- `tool_execution_start`
- `tool_execution_update`
- `tool_execution_end`
- `auto_retry_start`
- `auto_retry_end`
- `extension_error`

Unknown event types must be preserved in raw JSONL and may be shown generically rather than failing the node.

## 18.6 Human-Readable Live Events

Translate events into concise UI messages, for example:

- `Pi session started`
- `Assistant response streaming`
- `Running tool: bash`
- `Editing src/example.py`
- `Provider retry 1/3`
- `Pi session completed`

Do not store sensitive environment data.

## 18.7 Result Determination

The prompt node succeeds when:

- The Pi process exits with code `0`.
- JSONL parsing did not encounter an unrecoverable framing error.
- No engine-level timeout or cancellation occurred.

A Pi-reported extension error may be logged but does not automatically fail the node unless the process exits non-zero or the final session event indicates failure.

## 18.8 Future RPC Option

RPC mode may later be used for multi-turn nodes or direct steering. It starts with:

```bash
pi --mode rpc --no-session --no-approve
```

Commands and responses use strict JSONL over stdin/stdout. RPC is not required for the initial implementation.

---
# 19. Workflow Definition Persistence Through GitLab

## 19.1 Save Workflow

Saving a workflow does not write directly to the default branch.

Flow:

1. Fetch origin.
2. Resolve current default-branch SHA.
3. Validate the workflow and all references.
4. Create a temporary definition worktree from that SHA.
5. Write the workflow's indexed `.workflowEngine/<folders>/<workflow_id>.json` path with stable formatting.
6. Stage only the workflow file.
7. Commit with:

```text
Update workflow: <workflow name>
```

8. Push branch:

```text
workflow_definition/<workflow_id>_<short_uuid>
```

9. Create an MR targeting the default branch.
10. Assign the current user as reviewer.
11. Remove the temporary local worktree.
12. Return MR information.

The updated workflow becomes runnable only after the MR is merged.

## 19.2 Delete Workflow

Deletion follows the same MR-based process but removes the file.

The backend must reject deletion when another workflow on the same proposed base revision references the deleted workflow, unless the request includes compatible updates to all referencing workflows.

## 19.3 Stable JSON Formatting

Use deterministic formatting to reduce review noise:

- UTF-8.
- Two-space indentation.
- Trailing newline.
- Preserve node and edge array order from the UI.
- Sort simple object keys only where it does not harm readability, such as `variables`.

## 19.4 Optimistic Concurrency

The workflow editor loads and stores the source file blob SHA or base commit SHA.

Save requests include:

```json
{
  "workflow": { "...": "..." },
  "expected_base_commit_sha": "012345..."
}
```

If the default branch changed since the editor loaded, return `409 WORKFLOW_BASE_CHANGED` and require the user to reload or explicitly create an MR from the newer base.

---

# 20. Frontend Specification

## 20.1 Routes

```text
/projects
/projects/:projectId/workflows
/projects/:projectId/workflows/new
/projects/:projectId/workflows/:workflowId/edit
/credentials
/runs
/runs/:runId
```

There is no dedicated login page. Caddy redirects unauthenticated requests.

## 20.2 Application Shell

Header:

- Product name.
- Current user name, avatar, and GitLab username.
- Links to Projects, Runs, and Credentials.

Global UI requirements:

- Clear loading and error states.
- Toasts for background actions.
- Confirmation dialogs for destructive actions.
- Links to GitLab open in a new tab with safe `rel` attributes.

## 20.3 Projects Page

Display:

- Name.
- Git URL.
- GitLab project ID.
- Default branch.
- Token configured indicator.
- Added by.
- Last fetch result.
- Project-wide Pi provider, model, and skill defaults.

Actions:

- Add project.
- Validate project and token.
- Fetch latest.
- Update token.
- Update Pi defaults.
- View workflows.
- Remove project.

## 20.4 Credentials Page

Display only:

- Key name.
- Description.
- Updated time.
- Masked indicator.

Actions:

- Add.
- Replace value.
- Delete.

Never show a stored value.

## 20.5 Workflow List

For each workflow:

- Name.
- ID.
- Description.
- Tags.
- Node count.
- Direct child-workflow references.
- Last commit SHA and modification time.
- Edit.
- Run.
- Delete.

The run dialog renders typed workflow inputs from the workflow's `inputs` schema.
The catalog provides text search across name, ID, description, and tags; a tag filter;
and an optional grouping mode that groups workflows into tag sections. Multi-tagged
workflows appear in each applicable group.

## 20.6 Workflow Builder

Use React Flow.

### Palette

- Bash.
- Python Script.
- Pi Prompt.
- Human Feedback.
- Sub-Workflow.
- Review Loop.

### Node cards

Show:

- Type icon.
- Label.
- Short configuration preview.
- Join badge when applicable.
- Child workflow name for sub-workflow nodes.
- Initial/revision child names and maximum iteration count for review loops.
- Validation-error indicator.

### Common node editor

- Label.
- Join mode.
- Timeout where supported.
- Allow failure where supported.

### Sub-workflow editor

- Searchable child-workflow dropdown populated from the repository catalog.
- Input mapping table.
- Output mapping table.
- Reference preview.
- Button to open child workflow in another route/tab.

### Review-loop editor

- Searchable initial child-workflow dropdown populated from the repository catalog.
- Searchable optional revision child-workflow dropdown.
- Initial input mapping.
- Revision input mapping.
- Maximum review iterations.
- Commit message.
- MR title and description.
- Output mapping from final child invocation.

### Edge editor

- Condition type.
- Operator.
- Value.
- Output stream where applicable.

### Settings

- Workflow variables.
- Typed inputs.
- Declared outputs.
- Default node timeout.
- Wave commit template.
- Final commit template.
- MR templates.
- Maximum review iterations.
- Maximum sub-workflow depth.
- Maximum output-variable bytes.
- Workflow tags.

### Validation UX

Client validation mirrors obvious schema rules, but server validation is authoritative.

Highlight:

- Invalid nodes.
- Broken references.
- DAG cycles.
- Recursive workflow references.
- Missing child inputs.
- Invalid variable references.

The frontend must not offer arbitrary edge loops. React Flow connection validation should reject a connection that creates a DAG cycle.

## 20.7 Run Graph and Invocation History

The run graph renders the root workflow and every persisted child invocation from the
run snapshot. Each invocation is a distinct visual section containing the child
workflow's nodes and execution states. A control edge connects the parent node to its
first child invocation. Later invocations belonging to the same review-loop node are
linked in iteration order with a feedback transition, and their cards show the
iteration number, child workflow, invocation path, status, and the feedback that
started the round. Nested sub-workflow invocations are expanded using the same rules.

## 20.8 Run List

Columns:

- Status.
- Workflow.
- Project.
- Triggered by.
- Base commit short SHA.
- Started.
- Duration.
- Current invocation/node.
- MR.
- Actions.

Filters:

- Status.
- Project.
- Workflow.
- Triggered user.
- Date range.

Auto-refresh every ten seconds when no WebSocket status channel is available.

## 20.9 Run Detail

Header:

- Root workflow.
- Project.
- Status.
- Triggering user.
- Base branch and exact SHA.
- Run branch.
- Current HEAD.
- MR link.
- Started and elapsed time.

### Graph view

Render the root graph read-only.

For sub-workflow and review-loop nodes:

- Expandable panel listing child invocations.
- Each child invocation can open its own graph view.
- Review-loop card shows current iteration and feedback history.

Node colors:

- Grey: pending.
- Blue/pulsing: running.
- Green: success.
- Red: failed.
- Yellow: skipped.
- Orange/pulsing: awaiting feedback.
- Purple: interrupted/resuming.

### Wave view

Show execution waves with:

- Wave index.
- Included nodes.
- Start SHA.
- End SHA.
- Attempt count.
- Rollback status.

This makes resume behavior understandable.

### Logs

Tabs:

- Engine.
- All live output.
- Per-node output.
- Pi events.

Features:

- Auto-scroll toggle.
- Search.
- Download stdout/stderr.
- Attempt selector.
- Clear indication when live lines were dropped and full output must be loaded from disk.

### Feedback panel

Visible when `AWAITING_FEEDBACK`.

For project members with run visibility:

- Show MR link.
- Show the policy, requirements, eligible reviewers, and quorum progress.
- Show previous feedback events.

For users with `gate.respond` who are eligible in the current snapshot:

- Approve button.
- Feedback textarea and send button.

For other users, hide or disable controls and explain that the active approval policy does
not select their identity.

### Actions

- Cancel for active states.
- Resume for `FAILED` and `INTERRUPTED`.
- View MR.
- View base commit.

## 20.10 Frontend WebSocket Behavior

- Connect while viewing a run.
- Reconnect with exponential backoff.
- Preserve last engine log sequence.
- On reconnect, request logs after that sequence.
- Fall back to polling run status if WebSocket is unavailable.
- Stop reconnecting after terminal state unless the user manually refreshes.

---

# 21. Backend Project Structure

```text
workflow-engine/
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   ├── lifecycle.py
│   │
│   ├── auth/
│   │   ├── middleware.py
│   │   └── models.py
│   │
│   ├── api/
│   │   ├── health_routes.py
│   │   ├── auth_routes.py
│   │   ├── project_routes.py
│   │   ├── credential_routes.py
│   │   ├── workflow_routes.py
│   │   ├── run_routes.py
│   │   ├── feedback_routes.py
│   │   ├── webhook_routes.py
│   │   └── websocket_routes.py
│   │
│   ├── engine/
│   │   ├── coordinator.py
│   │   ├── scheduler.py
│   │   ├── waves.py
│   │   ├── invocations.py
│   │   ├── resume.py
│   │   ├── cancellation.py
│   │   ├── task_registry.py
│   │   ├── process_registry.py
│   │   ├── context.py
│   │   ├── conditions.py
│   │   ├── snapshot.py
│   │   ├── validation.py
│   │   ├── nodes/
│   │   │   ├── base.py
│   │   │   ├── bash.py
│   │   │   ├── script.py
│   │   │   ├── prompt.py
│   │   │   ├── human_feedback.py
│   │   │   ├── subworkflow.py
│   │   │   └── review_loop.py
│   │   └── pi/
│   │       ├── command.py
│   │       ├── json_events.py
│   │       └── renderer.py
│   │
│   ├── integrations/
│   │   ├── git_manager.py
│   │   ├── git_credentials.py
│   │   ├── gitlab_client.py
│   │   ├── gitlab_webhooks.py
│   │   └── webhook_auth.py
│   │
│   ├── services/
│   │   ├── project_service.py
│   │   ├── credential_service.py
│   │   ├── workflow_service.py
│   │   ├── feedback_service.py
│   │   ├── cleanup_service.py
│   │   ├── reconciliation_service.py
│   │   └── log_broadcaster.py
│   │
│   ├── db/
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── repositories/
│   │   └── migrations/
│   │
│   ├── schemas/
│   │   ├── auth.py
│   │   ├── project.py
│   │   ├── credential.py
│   │   ├── workflow.py
│   │   ├── run.py
│   │   ├── feedback.py
│   │   └── webhook.py
│   │
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   ├── fixtures/
│   │   └── conftest.py
│   │
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── workflow-builder/
│   │   ├── run-detail/
│   │   ├── pages/
│   │   ├── stores/
│   │   ├── hooks/
│   │   ├── types/
│   │   └── utils/
│   ├── package.json
│   ├── package-lock.json
│   ├── tsconfig.json
│   └── vite.config.ts
│
├── auth-service/
│   ├── src/
│   ├── package.json
│   └── Dockerfile
│
├── deploy/
│   ├── Caddyfile
│   ├── Caddy.Dockerfile
│   └── docker-compose.yml
│
├── .env.example
├── README.md
└── AGENTS.md
```

---

# 22. Environment Variables

```bash
# Application
APP_ENV=production
APP_BASE_URL=https://workflow.example.internal
LOG_LEVEL=INFO

# Database
DATABASE_URL=postgresql+asyncpg://workflow_engine:${POSTGRES_PASSWORD}@postgres:5432/workflow_engine
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10
POSTGRES_PASSWORD=<secret>

# Encryption
CREDENTIALS_ENCRYPTION_KEY=<fernet-key>
CREDENTIALS_ENCRYPTION_KEY_VERSION=1

# GitLab
GITLAB_URL=https://code.siemens.com
GITLAB_WEBHOOK_SECRET=<secret>
# Optional on supported GitLab versions:
GITLAB_WEBHOOK_SIGNING_SECRET=

# Paths
PROJECT_CLONE_BASE_PATH=/var/workflowengine/repos
WORKTREE_BASE_PATH=/var/workflowengine/worktrees
RUN_DATA_BASE_PATH=/var/workflowengine/run_data

# Engine
MAX_CONCURRENT_RUNS=10
DEFAULT_NODE_TIMEOUT_SECONDS=1800
MAX_NODE_TIMEOUT_SECONDS=14400
MAX_REVIEW_ITERATIONS=10
MAX_SUBWORKFLOW_DEPTH=8
MAX_OUTPUT_VARIABLE_BYTES=65536
PROCESS_TERMINATION_GRACE_SECONDS=10
QUEUE_RECONCILIATION_INTERVAL_SECONDS=60
STALE_RESOURCE_RECONCILIATION_INTERVAL_SECONDS=3600
STALE_FAILED_RUN_DAYS=7
TERMINAL_WORKTREE_RETENTION_DAYS=1
ORPHAN_WORKTREE_GRACE_HOURS=24
RUN_OUTPUT_RETENTION_DAYS=30
LONG_OPEN_CHANGE_REQUEST_WARNING_DAYS=14
LONG_OPEN_CHANGE_REQUEST_WARNING_REPEAT_DAYS=7
WORKTREE_USAGE_WARNING_BYTES=53687091200
RUN_DATA_USAGE_WARNING_BYTES=53687091200
FILESYSTEM_USAGE_WARNING_PERCENT=85

# Auth service
OAUTH_CLIENT_ID=<gitlab-oauth-client-id>
OAUTH_CLIENT_SECRET=<secret>
OAUTH_REDIRECT_URI=https://workflow.example.internal/auth/callback
SESSION_SIGNING_KEY=<secret>
SESSION_PREVIOUS_SIGNING_KEY=
SESSION_MAX_AGE_SECONDS=28800

# Pi
PI_VERSION=<tested-version>
```

Requirements:

- `.env` is never committed.
- Secrets use Docker secrets or a protected environment file where possible.
- The encryption key and session signing key are backed up separately from PostgreSQL.

---

# 23. Docker and Deployment

## 23.1 Backend Dockerfile

```dockerfile
FROM python:3.11-slim

ARG PI_VERSION

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       git curl ca-certificates nodejs npm \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g --ignore-scripts \
      "@earendil-works/pi-coding-agent@${PI_VERSION}" \
    && pi --version

RUN useradd --create-home --uid 10001 workflow

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN mkdir -p /var/workflowengine \
    && chown -R workflow:workflow /app /var/workflowengine

USER workflow

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

The actual Node installation method should use a supported Node 20+ source if the base distribution package is too old. The final image must verify `node --version`, `npm --version`, and `pi --version` during build.

## 23.2 Caddy Image with Frontend Build

Use one deterministic image rather than a build-only frontend container and shared-volume race.

```dockerfile
FROM node:20-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend-build /frontend/dist /srv/frontend
```

## 23.3 Docker Compose

```yaml
services:
  caddy:
    build:
      context: ..
      dockerfile: deploy/Caddy.Dockerfile
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      backend:
        condition: service_healthy
      auth-service:
        condition: service_started
    restart: unless-stopped

  auth-service:
    build: ../auth-service
    env_file: ../.env
    expose:
      - "3001"
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: workflow_engine
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: workflow_engine
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U workflow_engine"]
      interval: 10s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  backend:
    build:
      context: ../backend
      args:
        PI_VERSION: ${PI_VERSION}
    env_file: ../.env
    expose:
      - "8000"
    volumes:
      - /var/workflowengine:/var/workflowengine
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    command:
      - uvicorn
      - main:app
      - --host
      - 0.0.0.0
      - --port
      - "8000"
      - --workers
      - "1"
    restart: unless-stopped

volumes:
  postgres_data:
  caddy_data:
  caddy_config:
```

Do not publish backend, auth-service, or PostgreSQL ports to the host.

## 23.4 Caddyfile

Caddy's `reverse_proxy` supports WebSocket upgrades, so one authenticated `/api/*` handler is sufficient.

```caddyfile
workflow.example.internal {
    encode zstd gzip

    handle /api/webhook/gitlab {
        reverse_proxy backend:8000
    }

    handle /api/health {
        reverse_proxy backend:8000
    }

    handle /auth/* {
        reverse_proxy auth-service:3001
    }

    handle /api/* {
        route {
            request_header -X-Token-User-Email
            request_header -X-Token-User-Name
            request_header -X-Token-User-Avatar
            request_header -X-Token-GitLab-User-Id
            request_header -X-Token-GitLab-Username

            forward_auth auth-service:3001 {
                uri /auth/verify
                copy_headers {
                    X-Token-User-Email
                    X-Token-User-Name
                    X-Token-User-Avatar
                    X-Token-GitLab-User-Id
                    X-Token-GitLab-Username
                }
            }

            reverse_proxy backend:8000
        }
    }

    handle {
        root * /srv/frontend
        try_files {path} /index.html
        file_server
    }
}
```

Before deployment, run:

```bash
caddy validate --config /etc/caddy/Caddyfile
caddy adapt --config /etc/caddy/Caddyfile --pretty
```

The adapted configuration should be reviewed to ensure trusted-header removal, auth, and route ordering behave as intended.

## 23.5 Filesystem Permissions

- Backend runs as a non-root user.
- `/var/workflowengine` is owned by that user.
- Repositories and run output are not readable by unrelated host users.
- Auth-service and PostgreSQL containers do not mount the workflow filesystem.

## 23.6 Backup Requirements

Back up:

- PostgreSQL.
- `RUN_DATA_BASE_PATH` according to retention needs.
- Credential-encryption key.
- Auth session signing key.
- Caddy data if certificate recovery is needed.

A backup without the encryption key cannot restore credentials. A key without the database must also be protected as sensitive material.

---
# 24. Cleanup and Retention

## 24.1 Worktree Lifecycle

A run worktree remains available while its MR is open so reviewers can inspect the branch and the engine can continue after feedback.

Cleanup triggers:

- MR merged.
- MR closed.
- Cancelled run without MR.
- Completed run without MR after the terminal-worktree retention deadline.
- Failed run without MR after stale-resource deadline.
- Manual operator cleanup.

## 24.2 Safe Cleanup Sequence

```python
async def cleanup_run_resources(run_id: UUID, reason: str) -> None:
    run = await runs.get(run_id)

    if run.status in ACTIVE_STATES:
        await cancellation.request_and_wait(run_id)

    project = await projects.get(run.project_id)
    async with project_git_lock(project.id):
        if run.worktree_path and path_exists(run.worktree_path):
            await git("worktree", "remove", "--force", run.worktree_path,
                      cwd=project.local_path)
        await git("worktree", "prune", cwd=project.local_path)
        if run.branch_name:
            await git("branch", "-D", run.branch_name,
                      cwd=project.local_path, check=False)

    await apply_run_data_retention(run)
    await runs.record_cleanup(run_id, reason)
```

Never use an arbitrary database path without confirming it is beneath the configured worktree or run-data base path.

## 24.3 Remote Branch

When the MR setting `remove_source_branch=true` succeeds, GitLab removes the remote branch on merge. On close, the remote branch may remain.

The cleanup reconciler may delete the remote run branch after confirming:

- MR is merged or closed.
- Branch name exactly equals the run's stored branch.
- No other open MR uses the branch.

## 24.4 Run Output Retention

Do not automatically delete logs at the same moment as the worktree.

Default policy:

- Worktree: remove on MR merge/close.
- Terminal worktree without an MR: remove after
  `TERMINAL_WORKTREE_RETENTION_DAYS`.
- Run output: retain for `RUN_OUTPUT_RETENTION_DAYS`.
- Engine logs and database metadata: retain indefinitely unless a separate policy is configured.
- Credential records: until user deletion.

## 24.5 Hourly Reconciliation

Every hour:

1. Query GitLab for old open/closed/merged MR state where webhook cleanup may have been missed.
2. Clean terminal worktrees whose MR is no longer open.
3. Clean stale failed/cancelled runs without MRs.
4. Delete expired run output.
5. Run `git worktree prune` on project clones.
6. Detect missing worktrees for resumable runs and mark them non-resumable with a clear error.
7. Detect orphan worktree directories not referenced by the database; delete only
   direct-child Kyron-shaped paths after both a durable detection grace period and
   an inactivity grace period, with durable audit events.
8. Warn on open change requests older than the configured threshold, with a
   configured repeat interval.
9. Measure worktree/run-output root usage, emit Prometheus gauges, and persist
   threshold warning/recovery transitions.

---

# 25. Error Model

## 25.1 Error Categories

Use machine-readable error types:

- `VALIDATION_ERROR`
- `UNRESOLVED_VARIABLE`
- `MISSING_SUBWORKFLOW`
- `RECURSIVE_SUBWORKFLOW`
- `GRAPH_DEADLOCK`
- `NODE_FAILURE`
- `NODE_TIMEOUT`
- `PI_PROTOCOL_ERROR`
- `GIT_FAILURE`
- `GITLAB_API_FAILURE`
- `APPROVAL_RESET_FAILURE`
- `WORKTREE_RECOVERY_FAILED`
- `MAX_REVIEW_ITERATIONS_REACHED`
- `INTERRUPTED`
- `CANCELLED`
- `INTERNAL_ERROR`

## 25.2 User-Facing Errors

The UI shows:

- Concise message.
- Error category.
- Failed invocation and node.
- Attempt number.
- Link to output.
- Resume availability.

Stack traces are logged to the backend operational log but not stored in user-facing run logs unless explicitly sanitized.

## 25.3 Retry Rules

Infrastructure operations may retry automatically:

- GitLab GET: up to three retries with exponential backoff.
- Git fetch: one retry on transient network failure.
- Git push: one retry after fetch only when non-fast-forward cannot represent another actor modifying the unique run branch.
- Database serialization/deadlock: transaction retry.

Node processes are not automatically retried inside a wave. The user resumes the failed run, creating new attempts.

## 25.4 Approval Reset Is Required

Intermediate approval reset is not best-effort. It is a workflow invariant.

If reset fails:

- Do not continue execution.
- Leave or restore run state as `AWAITING_FEEDBACK`.
- Show an actionable error.
- Permit eligible approvers to try approval again after the token or provider issue is fixed.

---

# 26. Security and Operational Notes

## 26.1 Trusted Internal Execution

The system intentionally executes trusted Bash and Script workflows directly in the
backend environment. Pi Prompt nodes add filesystem write confinement, but remain trusted
for reads, network access, environment access, and resource consumption. This is
acceptable only under the documented assumptions.

Before exposing the system to untrusted repositories or workflow authors, redesign execution to use isolated runner containers with resource and network restrictions.

## 26.2 Minimum Protections Retained Despite Trust

Even internally:

- Backend is not directly exposed.
- OAuth is mandatory except health and webhook.
- Trusted headers are stripped and re-added by Caddy.
- Credentials remain encrypted at rest.
- Decrypted credentials are ephemeral.
- Project tokens are never persisted in Git remotes.
- Webhooks are authenticated and deduplicated.
- Paths are validated beneath configured roots.
- Pi and its descendants receive a read-only root filesystem with only the run worktree
  and ephemeral Pi state mounted read-write; execution fails if Bubblewrap cannot create
  that boundary.
- Git commands use argument arrays.
- Processes run as non-root.
- Output and database backups are controlled.

## 26.3 Auditability

The following are represented in engine logs or dedicated rows:

- Project registration and token replacement.
- Credential creation, replacement, and deletion without values.
- Workflow save and delete MR creation.
- Run trigger, resume, cancel, approval, and feedback.
- Triggering user and GitLab actor.
- Git commit checkpoints.
- MR creation and cleanup.
- Webhook delivery result.

A separate append-only audit table may be added later, but structured logs and immutable attempt rows are sufficient for the initial internal version.

## 26.4 Database Transactions

Use transactions for:

- Run trigger snapshot insertion.
- Run state transitions.
- Wave and node start.
- Wave completion and edge evaluation persistence.
- Feedback checkpoint creation.
- Feedback acceptance and continuation reservation.
- Webhook delivery insertion.

Use row locking or conditional updates such as:

```sql
UPDATE workflow_runs
SET status = 'RUNNING', status_version = status_version + 1
WHERE id = :run_id
  AND status = 'AWAITING_FEEDBACK'
  AND status_version = :expected_version
RETURNING *;
```

## 26.5 Time and Clock

- Store UTC timestamps.
- Use monotonic clocks for process timeout and duration calculations.
- Use wall-clock UTC only for persistence and display.

---

# 27. Testing Specification

## 27.1 Unit Tests — Workflow Validation

Test:

- Valid simple DAG.
- Duplicate node and edge IDs.
- Missing node references.
- Orphaned nodes.
- Direct graph cycles.
- Invalid join mode.
- Missing node configuration.
- Invalid script traversal.
- Unknown condition type and operator.
- Missing sub-workflow.
- Direct and indirect recursive sub-workflows.
- Maximum sub-workflow depth.
- Missing child input mapping.
- Invalid output mapping.
- Review-loop child containing a nested checkpoint.

## 27.2 Unit Tests — Scheduler

Test:

- Linear execution.
- Parallel fan-out.
- AND join with all true.
- AND join with one true and one false.
- AND join with all false and skip.
- OR join first true.
- OR join where earlier predecessor is false and later is true.
- Persisted edge evaluations.
- Graph deadlock detection.
- Deterministic node ordering.
- Control-node wave boundary.

## 27.3 Unit Tests — Sub-Workflows

Test:

- Single child invocation.
- Nested child invocation.
- Input defaults and overrides.
- Output mapping.
- Child failure propagation.
- Child allow-failure behavior where configured.
- Unique invocation paths.

## 27.4 Unit Tests — Review Loop

Test:

- Initial child succeeds, user approves.
- Initial child succeeds, user gives feedback, revision child runs.
- Multiple feedback iterations.
- Fallback to initial workflow when revision workflow is omitted.
- Maximum iterations reached.
- Only snapshotted eligible identities are accepted and every configured quorum is enforced.
- Other-user approval ignored.
- Only triggering-user `@kyron` comment accepted.
- Approval reset failure leaves run waiting.
- Duplicate approval webhook ignored.
- Frontend action racing GitLab webhook.

## 27.5 Unit Tests — Resume

Test:

- Failure in a single-node wave.
- Failure in one node of a parallel wave.
- Successful sibling is rerun after rollback.
- Worktree exactly matches start SHA before resume.
- Prior successful waves remain committed.
- Attempt numbers increment.
- Interrupted wave after startup.
- Missing worktree blocks resume.
- Failed rollback blocks resume.
- Resume inside a child invocation.
- Resume inside a review-loop revision invocation.

## 27.6 Unit Tests — Credentials

Test:

- Ciphertext at rest.
- API never returns values.
- Public context contains no secret.
- Workflow snapshot contains no secret.
- Process environment receives all triggering-user credentials.
- Environment is not logged.
- Redaction removes known values from errors.

## 27.7 Unit Tests — Pi Adapter

Test with captured JSONL fixtures:

- Successful session.
- Streaming message updates.
- Tool execution events.
- Unknown event type.
- Malformed JSON line.
- Process non-zero exit.
- Timeout.
- Cancellation.
- Bounded preview output.

## 27.8 Integration Tests — Git

Using temporary local bare repositories:

- Exact SHA resolution.
- Worktree from SHA.
- Wave checkpoint commit.
- Failed-wave reset.
- Final push.
- Definition workflow branch and commit.
- Cleanup.
- Project lock behavior.

## 27.9 Integration Tests — GitLab Client

Mock HTTP endpoints and verify:

- MR create payload includes triggering reviewer ID.
- Existing MR reviewer update.
- Note posting.
- Approval reset endpoint and error behavior.
- MR state polling.
- Webhook payload routing.
- Top-level webhook actor fields.
- `approval` versus `approved` behavior.

## 27.10 API Tests

- Auth header required.
- Project CRUD.
- Credential CRUD.
- Workflow validation and save.
- Trigger with typed inputs.
- Run retrieval and pagination.
- Permission- and policy-eligible feedback controls.
- Atomic duplicate action rejection.
- Output path safety.
- WebSocket authentication and replay.

## 27.11 End-to-End Scenarios

### E2E 1 — Simple success

- Trigger Bash -> Prompt -> Test.
- Verify branch, commits, MR, reviewer, logs, completion.

### E2E 2 — Review loop

- Initial child changes file.
- MR created with all reviewers selected by the gate policy.
- An eligible reviewer comments `@kyron update docs`.
- Revision child receives feedback and changes docs.
- The required eligible reviewers satisfy the policy quorum.
- Approval resets.
- Workflow completes.
- Final merge requires fresh approval.

### E2E 3 — Parallel failure and resume

- Two parallel nodes modify non-conflicting files.
- One fails.
- Entire wave rolls back.
- Resume reruns both nodes.
- Both succeed.

### E2E 4 — Backend restart

- Start long-running node.
- Restart backend.
- Run becomes `INTERRUPTED`.
- Resume resets to wave start and succeeds.

### E2E 5 — Webhook duplicate

- Deliver same webhook twice with identical idempotency key.
- Verify one feedback event and one continuation.

## 27.12 Acceptance Criteria

The initial release is accepted when:

- All unit and integration suites pass.
- A workflow with nested sub-workflows completes.
- A review loop performs at least two revision rounds.
- Failed parallel wave resumes correctly.
- No decrypted credential appears in database dumps, snapshots, logs, or output metadata.
- Exact base SHA is visible and matches worktree ancestry.
- Only eligible gate identities can decide a checkpoint; authorized project administrators
  may use a reasoned, audited override.
- Final MR requires a new approval after intermediate approval.
- Backend runs with one worker.
- Caddy routes HTTP and WebSocket traffic correctly.

---

# 28. Implementation Checklist and Recommended Order

The coding assistant should implement in the following order. Do not begin with the complete frontend graph editor; first make the execution core testable through APIs and fixtures.

## Phase 1 — Repository and Foundations

- [ ] Create backend, frontend, auth-service, and deployment directories.
- [ ] Add Python and TypeScript formatting, linting, and test commands.
- [ ] Add `.env.example` and typed configuration loading.
- [ ] Configure SQLAlchemy async engine and Alembic.
- [ ] Create initial Docker Compose with PostgreSQL and one-worker backend.
- [ ] Add health endpoint.
- [ ] Add CI or local verification script.

**Exit condition:** Backend starts, migrations run, database health is reported.

## Phase 2 — Database Domain Model

- [ ] Implement all tables from Section 4.
- [ ] Add status enums or validated string constants.
- [ ] Add indexes and uniqueness constraints.
- [ ] Implement repository classes and transactional state transitions.
- [ ] Implement webhook-delivery deduplication repository.
- [ ] Add migration tests.

**Exit condition:** State transitions and attempt history are unit tested.

## Phase 3 — Authentication

- [ ] Implement GitLab OAuth in auth service.
- [ ] Store signed HTTP-only session cookie.
- [ ] Return GitLab user ID and username from `/auth/verify`.
- [ ] Configure Caddy trusted-header stripping and copying.
- [ ] Implement backend user upsert dependency.
- [ ] Add WebSocket authentication.
- [ ] Test spoofed header removal through Caddy.

**Exit condition:** Authenticated user including GitLab ID reaches HTTP and WebSocket routes.

## Phase 4 — Credential and Project Services

- [ ] Implement Fernet encryption service.
- [ ] Implement credential CRUD with no retrieval of values.
- [ ] Implement project registration and token validation.
- [ ] Implement temporary Git credentials for clone/fetch/push.
- [ ] Implement per-project Git locks.
- [ ] Add project clone and fetch operations.
- [ ] Confirm tokens never appear in logs or remotes.

**Exit condition:** A project can be registered, cloned, fetched, and pushed to with encrypted token storage.

## Phase 5 — Workflow Schemas and Validation

- [ ] Implement Pydantic workflow models.
- [ ] Implement all six node types.
- [ ] Implement typed workflow inputs and outputs.
- [ ] Implement DAG validation.
- [ ] Implement condition validation.
- [ ] Implement transitive sub-workflow resolution at a commit SHA.
- [ ] Implement recursive-reference detection and depth limit.
- [ ] Implement workflow-bundle snapshot generation.
- [ ] Add complete validation fixtures.

**Exit condition:** Root and child workflow bundles are reproducibly loaded and validated from an exact Git commit.

## Phase 6 — Git Worktrees and Checkpoints

- [ ] Implement exact base SHA resolution.
- [ ] Implement run branch and worktree creation from SHA.
- [ ] Configure worktree Git identity.
- [ ] Implement clean-worktree checks.
- [ ] Implement wave checkpoint commit.
- [ ] Implement hard reset and clean to wave start SHA.
- [ ] Implement safe cleanup and path validation.
- [ ] Test all operations using temporary repositories.

**Exit condition:** A simulated failed wave can be reset exactly and rerun.

## Phase 7 — Subprocess Runner and Logging

- [ ] Implement process-group creation.
- [ ] Implement stdout/stderr file streaming.
- [ ] Implement bounded previews.
- [ ] Implement timeouts.
- [ ] Implement SIGTERM/SIGKILL escalation.
- [ ] Implement task and process registries.
- [ ] Implement engine log repository and broadcaster.
- [ ] Implement WebSocket log route and reconnect behavior.
- [ ] Implement secret redaction.

**Exit condition:** Long-running and failing test processes stream output, cancel cleanly, and preserve files.

## Phase 8 — Basic DAG Engine

- [ ] Implement node readiness calculation.
- [ ] Implement AND and OR joins.
- [ ] Implement edge evaluation persistence.
- [ ] Implement wave formation and deterministic ordering.
- [ ] Implement parallel execution of Bash, Script, and Prompt nodes in the shared worktree.
- [ ] Execute Sub-Workflow, Human Feedback, and Review Loop nodes as isolated control boundaries.
- [ ] Implement wave success commit.
- [ ] Implement wave failure rollback.
- [ ] Implement graph deadlock detection.
- [ ] Implement Bash and Script nodes.

**Exit condition:** Linear, fan-out, fan-in, conditional, and failed-wave workflows pass unit and integration tests.

## Phase 9 — Pi Prompt Node

- [ ] Pin and install Pi package.
- [ ] Build command using `--mode json --no-session --no-approve`.
- [ ] Inject ephemeral credential environment.
- [ ] Parse JSONL events.
- [ ] Store raw events and present human-readable stream.
- [ ] Handle malformed events, timeout, cancellation, and exit code.
- [ ] Add Pi adapter fixtures and one real smoke test.

**Exit condition:** A prompt node changes a test repository and produces structured live events.

## Phase 10 — Sub-Workflow Invocation

- [ ] Implement invocation records and paths.
- [ ] Map child inputs.
- [ ] Execute child DAG in same run/worktree.
- [ ] Map declared child outputs.
- [ ] Propagate child failure.
- [ ] Support nested children up to depth limit.
- [ ] Add child graph to run-detail API.

**Exit condition:** Nested sub-workflows execute and resume correctly.

## Phase 11 — GitLab MR and Webhooks

- [ ] Implement shared GitLab HTTP client.
- [ ] Create MR with every provider reviewer selected by the gate policy.
- [ ] Replace reviewers on an existing MR when a new gate snapshot opens.
- [ ] Post notes.
- [ ] Reset approvals using project token.
- [ ] Implement webhook auth.
- [ ] Implement delivery deduplication.
- [ ] Correctly parse note actors from top-level `user`.
- [ ] Correctly handle individual `approval` events.
- [ ] Match approval and feedback actors against the current gate eligibility snapshot.
- [ ] Implement merge/close cancellation and cleanup.

**Exit condition:** GitLab comments and approvals cause exactly one correct state transition.

## Phase 12 — Human Feedback and Review Loop

- [ ] Implement atomic pause checkpoint.
- [ ] Implement standalone human-feedback node.
- [ ] Implement review-loop initial child invocation.
- [ ] Implement revision child invocation with feedback mapping.
- [ ] Implement max iteration failure.
- [ ] Reset approval before every continuation.
- [ ] Preserve feedback history.
- [ ] Add race tests for frontend and webhook actions.

**Exit condition:** Full iterative review workflow completes and requires fresh final approval.

## Phase 13 — Resume, Startup Recovery, and Reconciliation

- [ ] Implement startup interruption marking.
- [ ] Requeue queued runs.
- [ ] Implement failed-wave resume.
- [ ] Create new attempts rather than overwriting.
- [ ] Implement queue reconciliation.
- [ ] Implement hourly resource reconciliation.
- [ ] Implement missing-worktree diagnostics.
- [ ] Test backend restart during root and child waves.

**Exit condition:** Restart and failure scenarios recover according to Section 11.

## Phase 14 — Workflow Definition Git MRs

- [ ] Implement workflow listing from exact default-branch revision.
- [ ] Implement validation endpoint.
- [ ] Implement save/update through temporary worktree and MR.
- [ ] Implement delete through MR.
- [ ] Assign current user as reviewer.
- [ ] Implement optimistic base-commit conflict response.

**Exit condition:** Workflow edits are reviewed and become live only after merge.

## Phase 15 — Frontend Core

- [ ] Build application shell and auth display.
- [ ] Build Projects page.
- [ ] Build Credentials page.
- [ ] Build Workflow list and typed run dialog.
- [ ] Build Run list and Run detail.
- [ ] Build logs, node attempts, waves, and feedback panel.
- [ ] Enforce triggering-user control visibility.

**Exit condition:** All backend functionality is usable without the visual builder.

## Phase 16 — Visual Workflow Builder

- [ ] Add React Flow canvas.
- [ ] Add six node card types.
- [ ] Add configuration panels.
- [ ] Add edge condition editor.
- [ ] Add workflow inputs, outputs, variables, and settings.
- [ ] Add sub-workflow reference browser.
- [ ] Add review-loop editor.
- [ ] Prevent DAG cycles in the UI.
- [ ] Display server validation errors.
- [ ] Save through workflow-definition MR endpoint.

**Exit condition:** A user can visually construct the complete E2E review-loop example.

## Phase 17 — Deployment and Hardening

- [ ] Build frontend into Caddy image.
- [ ] Validate adapted Caddy config.
- [ ] Confirm backend uses one worker and no reload.
- [ ] Remove host port exposure for internal services.
- [ ] Configure backups.
- [ ] Configure output retention.
- [ ] Add operational runbook.
- [ ] Run all acceptance tests.
- [ ] Document trusted internal execution assumptions prominently.

**Exit condition:** Production-like internal deployment passes acceptance criteria.

---

# 29. Coding Assistant Working Rules

The coding assistant implementing this system should follow these rules:

1. Implement one phase at a time.
2. Run and extend tests before moving to the next phase.
3. Do not silently change state-machine semantics.
4. Do not add arbitrary graph cycles.
5. Do not persist decrypted credentials anywhere.
6. Do not use mutable repository refs after the run snapshot is created.
7. Do not overwrite attempt history.
8. Do not mark a run completed while reachable nodes remain non-terminal.
9. Do not continue after an intermediate approval unless approval reset succeeds.
10. Do not accept workflow-controlling feedback from identities outside the current gate's eligibility snapshot.
11. Do not expose backend, database, or auth-service ports to the host.
12. Keep Uvicorn at one worker until a durable worker architecture is intentionally introduced.
13. Commit implementation work in small, reviewable units.
14. Maintain an `AGENTS.md` with project-specific build and test instructions.
15. Update this specification or an explicit decision log when implementation requires a behavioral deviation.

---

# 30. Verified External Integration Assumptions

The implementation should be rechecked against the installed GitLab and Pi versions during development.

Verified against current official documentation when this specification was prepared:

- Pi npm package: `@earendil-works/pi-coding-agent`.
- Pi one-shot mode: `pi -p "..."`.
- Pi structured event mode: `pi --mode json "..."`.
- Pi RPC mode: `pi --mode rpc`.
- Pi non-interactive project trust can be controlled with `--approve` or `--no-approve`.
- GitLab merge-request webhook action `approval` means one user added approval.
- GitLab action `approved` means all required approvals are satisfied.
- GitLab webhook actors are in the top-level `user` object.
- GitLab approval reset endpoint is `PUT /projects/:id/merge_requests/:merge_request_iid/reset_approvals` and requires a valid bot project/group token.
- GitLab webhook deliveries provide retry-stable identifiers such as `webhook-id` or `Idempotency-Key` on supported versions.
- Caddy `forward_auth` copies selected response headers into the original request after successful verification.
- Caddy `reverse_proxy` supports WebSocket upgrades without a separate WebSocket proxy directive.

Official references:

- https://pi.dev/docs/latest/quickstart
- https://pi.dev/docs/latest/json
- https://pi.dev/docs/latest/rpc
- https://pi.dev/docs/latest/settings
- https://docs.gitlab.com/user/project/integrations/webhook_events/
- https://docs.gitlab.com/user/project/integrations/webhooks/
- https://docs.gitlab.com/api/merge_requests/
- https://docs.gitlab.com/api/merge_request_approvals/
- https://caddyserver.com/docs/caddyfile/directives/forward_auth
- https://caddyserver.com/docs/caddyfile/directives/reverse_proxy
- https://caddyserver.com/docs/caddyfile/directives

---

# 31. Final Summary of Normative Design Decisions

1. The system is internal and trusted, behind OAuth.
2. No project-membership authorization model is required.
3. Project approval policies control workflow approval and feedback checkpoints using
   snapshotted identities, quorum requirements, and configurable initiator participation.
4. Every run pins an exact repository commit SHA.
5. The root workflow and all child workflows are snapshotted from that same commit.
6. Ordinary workflow graphs are DAGs.
7. Reuse is implemented through `subworkflow` nodes.
8. Iteration is implemented through `review_loop` nodes, not arbitrary graph cycles.
9. Review loops invoke an initial child workflow, pause, and invoke a revision child workflow after feedback.
10. Nodes in a ready wave may run in parallel against the same worktree.
11. The workflow author is responsible for ensuring parallel nodes do not conflict.
12. Each execution wave has a Git start checkpoint.
13. Failure rolls back the entire wave and resume reruns the entire wave.
14. Earlier successful waves are preserved as commits.
15. Credentials remain encrypted at rest and are decrypted only to build an ephemeral process environment.
16. All triggering-user credentials are injected into every subprocess.
17. Credential values are not part of public template expansion or persisted graph state.
18. Pi uses official JSON mode and current CLI/package naming.
19. GitLab individual approval events are accepted only from the triggering reviewer.
20. Intermediate approval reset must succeed before the workflow continues.
21. A fresh final GitLab approval is required before merge.
22. The prototype engine runs in-process with exactly one Uvicorn worker.
23. PostgreSQL and Git checkpoints provide durable recovery information.
24. Worktrees remain until MR merge or close; output follows a separate retention policy.
25. Implementation proceeds in the phased order in Section 28.
