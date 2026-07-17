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
