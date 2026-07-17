# Implementation plan

This plan translates the normative 17-phase specification into eight reviewable
milestones. A milestone is complete only when its listed verification gate is
green. The checklist in the specification remains authoritative where this plan
is less specific.

## Delivery status

All eight implementation milestones were completed on 2026-07-16. The local
release gate, production image builds, Caddy validation, and a clean PostgreSQL
16 migration pass. The target-environment scenarios that require a real GitLab
instance, OAuth application, TLS hostname, and Pi provider credentials remain a
deployment acceptance activity; they are listed in `docs/acceptance.md`.

| Milestone | Status | Primary evidence |
| --- | --- | --- |
| 1. Foundations and durable domain | Complete | PostgreSQL migration and model/repository tests |
| 2. Identity, secrets, projects, provider primitives | Complete | Auth, crypto, credential, Git and GitLab adapter tests |
| 3. Workflow language and snapshots | Complete | Validation and exact-SHA snapshot tests |
| 4. Execution substrate and DAG engine | Complete | Scheduler, process, Pi, condition and rollback tests |
| 5. Composition, review and recovery | Complete | Feedback, webhook, resume and lifecycle implementation/tests |
| 6. HTTP and WebSocket API | Complete | OpenAPI/WebSocket route inventory and API tests |
| 7. Operator UI and visual builder | Complete | Strict TypeScript check and Vite production build |
| 8. OAuth, deployment and hardening | Complete | Auth build, audits, three image builds, Compose/Caddy validation |

## Milestone 1 — Foundations and durable domain

Deliver the repository layout, contributor instructions, typed environment
configuration, async SQLAlchemy session management, all specification tables,
Alembic migrations, status constants, atomic transition repositories, health
endpoint, formatting/type/test tools, and a local verification script.

Verification gate: migrations upgrade a clean PostgreSQL database; model and
transition tests pass; health distinguishes database failure; documentation
states the trust boundary and one-worker constraint.

## Milestone 2 — Identity, secrets, projects, and provider primitives

Implement trusted-header user resolution and upsert, WebSocket identity checks,
Fernet encryption with key versions, credential CRUD with write-only values,
project registration, per-project async Git locks, safe token use through a
temporary askpass helper, repository clone/fetch, and the pooled GitLab client.

Verification gate: API tests prove auth is required, secrets never appear in
responses/logs/remotes, and a local bare repository supports clone/fetch/push.

## Milestone 3 — Workflow language and immutable snapshots

Implement Pydantic models for all six nodes, inputs/outputs/settings and edge
conditions. Add structural DAG validation, path checks, condition/operator
validation, child input/output validation, reference-cycle/depth checks, nested
checkpoint rejection, exact-SHA `git show` loading, and deterministic bundle
snapshots.

Verification gate: the validation matrix in specification section 27.1 passes,
including indirect recursion and exact-revision bundle reproducibility.

## Milestone 4 — Execution substrate and basic DAG engine

Implement worktree/branch lifecycle, clean checkpoints, commits and rollback;
process groups, termination escalation, bounded/redacted output, attempt files,
engine logs and live broadcast; variable contexts; condition evaluation; AND/OR
joins; deterministic process waves; Bash, Script, and Pi JSON node adapters.

Verification gate: temporary-repository integration tests cover linear,
fan-out/fan-in, skip, timeout, cancellation, Pi fixtures, checkpoint commits, and
whole-wave rollback.

## Milestone 5 — Composition, review, recovery, and lifecycle

Implement nested invocation paths and mappings, standalone feedback, review-loop
iterations, MR checkpoints, frontend/GitLab actor enforcement, approval reset,
webhook authentication and deduplication, cancellation, new-attempt resume,
startup interruption recovery, queue scheduling, and stale-resource cleanup.

Verification gate: nested workflows, two-round review, duplicate webhook,
parallel failure/resume, and simulated backend restart scenarios pass.

## Milestone 6 — Complete HTTP and WebSocket API

Expose project, credential, workflow, trigger, run graph/detail/log/output,
cancel/resume/feedback, and webhook routes with pagination and stable errors.
Implement workflow save/delete through temporary branches and GitLab MRs with
optimistic default-branch concurrency.

Verification gate: route inventory matches specification section 14 and API
tests cover state conflicts, path safety, identity restrictions, and replay.

## Milestone 7 — Operator UI and visual builder

Build the authenticated shell, projects, credentials, workflow list/run dialog,
run list/detail, graphs, waves, attempts, logs, and feedback. Build the React Flow
editor for every node/condition/settings field, reject cycles client-side, show
server validation, and save through definition MRs. Workflow definitions carry
versioned tags used by catalog search/filter/group controls. Composite-node editors
use searchable catalog selectors and schema-driven input/output mapping fields. Run
graphs expand all durable child invocation instances and connect review iterations in
feedback order.

Verification gate: TypeScript checks and component tests pass, production build
succeeds, and the documented review-loop example can be constructed and saved.

## Milestone 8 — OAuth, deployment, and release hardening

Finish the GitLab OAuth service with signed rotating cookies, trusted-header
Caddy routes, single-worker backend image with pinned Pi, deterministic frontend
Caddy image, Compose health/dependencies/volumes, backup and restore runbook,
retention/reconciliation operations, and production-like acceptance checks.

Verification gate: all local checks and container builds pass; Caddy adapts and
validates; only ports 80/443 are published; the acceptance checklist in section
27.12 is documented with results.

## Cross-cutting completion rules

- Preserve state-machine semantics and immutable attempt history.
- Persist before publishing success or scheduling continuation.
- Sanitize every externally derived error and all persisted process output.
- Treat exact Git SHAs and the bundle snapshot as the execution source of truth.
- Add or update docs and tests in the same change as behavior.
- Record any normative deviation in `docs/decisions.md`.
