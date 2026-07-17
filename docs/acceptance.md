# Acceptance verification

## Local release record — 2026-07-16

The implementation release gate completed successfully:

- Ruff passed and strict MyPy reported no issues in 88 Python source files.
- Pytest passed all 52 backend unit, API, and integration tests.
- Frontend and OAuth service strict TypeScript checks and production builds
  passed; both dependency trees reported zero npm audit vulnerabilities.
- Backend, OAuth service, and frontend/Caddy production images built.
- The backend image reports the pinned Pi CLI version `0.80.9`.
- Alembic upgraded a clean PostgreSQL 16 database and created the complete
  twelve-table domain plus `alembic_version`.
- Docker Compose rendered successfully, publishes only ports 80 and 443, and
  the built Caddy image validated without warnings.

Run `./scripts/verify.sh` to repeat the repository-local portion of this gate.

## Automated coverage

- Backend: unit/API/integration tests cover models, atomic state transitions,
  encryption/redaction, auth identity, Git/GitLab adapters, exact snapshots,
  workflow validation, scheduling/joins, conditions, process timeout/output,
  Pi JSON events, worktree checkpoint rollback, webhook authentication and
  feedback actor/approval-reset semantics.
- Frontend: strict TypeScript check and production Vite build.
- Auth service: strict TypeScript check and production build.
- Supply chain: both Node package trees pass `npm audit --audit-level=high`.

For workflow catalog and visualization changes, additionally verify that tags survive
definition serialization; catalog search, tag filtering, and grouping agree; composite
workflow selectors expose the exact default-branch catalog; declared child mappings are
editable without raw JSON; and a multi-round review run displays each child invocation
and feedback transition in order.

## Environment-dependent acceptance

The following checks require the target GitLab instance, OAuth application,
project bot token, Pi provider credential, TLS hostname, and a PostgreSQL-backed
production-like VM. Run them before the first production promotion:

- Trigger Bash → Pi → test and verify branch, commits, reviewer, logs and MR.
- Complete two review-loop feedback rounds, approve, verify approval reset, then
  confirm a fresh final GitLab approval is required.
- Fail one member of a parallel wave, verify full rollback, resume, and confirm
  both attempts increment.
- Restart the backend during a root wave and a child wave; confirm `INTERRUPTED`
  classification and clean resume.
- Replay an identical webhook delivery key and confirm one feedback event.
- Inspect a database dump, snapshot, engine log, and output metadata for absence
  of decrypted credentials.
- Validate/adapt the final Caddy configuration and test spoofed identity headers.

Record the date, operator, GitLab version, Pi version, and result for each item in
the deployment change record.
