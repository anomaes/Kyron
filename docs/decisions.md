# Decision log

## D-001 — Specification is normative

Accepted. `workflow_orchestration_engine_spec.md` revision 2.0 defines product
behavior. Implementation documentation may clarify but cannot silently alter it.

## D-002 — Package layout

Accepted. The Python application is imported as `backend`, so local commands use
`uvicorn backend.main:app` and the backend image copies the repository package.
This avoids import behavior that depends on the current working directory.

## D-003 — Portable test database types

Accepted. Models use SQLAlchemy's portable UUID and JSON types with PostgreSQL
JSONB variants. Production migrations still create PostgreSQL-native JSONB and
UUID columns; unit tests can use SQLite without weakening production behavior.

## D-004 — Pi build pin

Accepted. Production images pin `@earendil-works/pi-coding-agent` 0.80.9 and use
Node 22.20 or newer, matching the package's declared engine requirement at the
time of implementation. Upgrade the pin only with JSON-event fixture and smoke
test verification.

## D-005 — Workflow tags remain definition metadata

Accepted. Workflow tags are stored in each `.workflowEngine/**/<workflow_id>.json`
definition and travel with Git review, exact-SHA snapshots, and exports. They are not
duplicated into database catalog tables because they have no runtime semantics. The
catalog derives search, filtering, and grouping from the exact default-branch
definitions already returned by the workflow API.

Repository folders are separate catalog location metadata. Workflows may be nested below
`.workflowEngine/`, and the catalog mirrors that tree without converting folder names into
definition tags. IDs remain globally unique and references remain ID-based, so moving a
workflow does not require editing its callers.

## D-006 — Run visualization is derived from durable invocation state

Accepted. Expanded child workflows and review-loop history are reconstructed from the
snapshotted definitions, invocation parent links, iteration numbers, node executions,
and feedback events. The UI does not persist a second visualization-specific history.

## D-007 — Definition authoring uses project-local layers

Accepted. Builder saves are validated project-scoped files, not commits. The catalog
overlays outgoing and in-review layers on the exact default-branch catalog. An explicit
review action materializes all outgoing workflows and node templates as one Git commit
and one code-host change request. This keeps save frequency out of repository history.

Local-definition test runs materialize an exact local Git commit so the workflow bundle
and run base remain reproducible. They are marked durably and cannot push a run branch
or create a code-host change request.

## D-008 — Authorization and gate governance are separate

Accepted. A global system administrator bootstraps project access. Project memberships
receive one or more project-scoped roles made from a fixed permission catalogue; custom
roles are permitted. Membership controls project visibility and backend authorization is
enforced independently of frontend controls.

Human gates reference reusable project approval-policy keys rather than environment-bound
user IDs in workflow JSON. Each gate opening snapshots its policy, eligible provider
identities, quorum requirements, and exact checkpoint commit. Approval decisions accumulate
until every requirement is satisfied. Feedback closes that gate, supersedes its approvals,
and a later revision opens a new gate. Administrative overrides require a reason and are
append-only audit events.

Each project receives a `default` policy with a dynamic workflow-triggerer requirement and
quorum 1. Gate node schemas select it when `approval_policy` is omitted; stricter workflows
replace that stable key with a project-managed policy.

Terminal execution reports are immutable database snapshots. Provider merge/close events
arriving after completion are append-only post-run lifecycle addenda.

## D-009 — Parallel composition uses invocation-owned Git workspaces

Accepted. A sub-workflow declares `shared`, `isolated`, or
`isolated_parallel` execution. `shared` remains the default and preserves
serialized execution in the parent workspace. Both isolated modes fork an exact
parent checkpoint into a child branch and worktree; the parallel mode allows
ready siblings to execute concurrently.

The parent workspace is immutable for the lifetime of a parallel batch.
Successful child heads integrate through explicit merge commits in parent
node-ID order, and any conflict restores the exact batch base. Mapped outputs
publish only after the complete Git transition succeeds. This makes filesystem,
checkpoint, rollback, and public-context ownership coincide at the invocation
boundary.

Workspace review requests target the immediate parent branch and are distinct
from the root final request. Gates link to workspace-review identities rather
than a run-global current pointer, so simultaneous child approvals remain
independent. Child request lifecycle events remain report evidence and never
trigger whole-run cleanup.

## D-010 — Verification separates the code subject from trusted definitions

Accepted. A run subject is a branch or an open provider change request resolved
to an immutable source commit. The executable workflow bundle has its own pinned
definition revision. A `report_only` workflow takes that revision from the
project default branch or an authorized Kyron local snapshot, so unreviewed
subject code cannot replace the workflow or its credential policy.

Report-only worktrees are disposable execution state: tools may write and Kyron
may checkpoint locally, but no result branch or change request is published.
Stored credentials resolve to none unless the trusted workflow explicitly
selects an allowlist or all. Reports retain the subject identity, checked SHA,
definition SHA, conclusion, and freshness as separate evidence.
