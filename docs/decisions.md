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

Accepted. Workflow tags are stored in each `.workflowEngine/<workflow_id>.json`
definition and travel with Git review, exact-SHA snapshots, and exports. They are not
duplicated into database catalog tables because they have no runtime semantics. The
catalog derives search, filtering, and grouping from the exact default-branch
definitions already returned by the workflow API.

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
