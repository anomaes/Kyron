# Acceptance verification

## 1.0-alpha release preparation — 2026-07-21

- Ruff passed and strict MyPy reported no issues across 113 Python source files.
- All 100 backend tests passed.
- Frontend and auth-service TypeScript checks and production builds passed.
- The VitePress documentation build completed, including the 1.0-alpha release page.
- Frontend, auth-service, and documentation npm audits reported zero vulnerabilities.
- Docker Compose configuration validation passed with `.env.example`.
- Runtime inspection reported `1.0-alpha` from both the backend package and FastAPI.

Production image builds, Caddy image validation, and the live-provider scenarios below
remain promotion checks before the prerelease is used for a production installation.

## Dual-provider local record — 2026-07-17

- Ruff and strict MyPy passed across 94 Python source files; all 66 backend tests
  passed.
- GitHub adapter tests cover authentication, metadata, pull-request creation,
  reviewer request, approval discovery/dismissal, and sanitized failures.
- GitHub webhook tests cover HMAC verification, delivery identity, provider-scoped
  deduplication, and approved-review normalization.
- A clean PostgreSQL 16 migration and an upgrade of a populated legacy `0001`
  GitLab schema both reached revision `0002`; legacy provider identities and
  project IDs were preserved.
- Frontend and auth-service strict TypeScript checks and production builds passed;
  both npm audits reported zero vulnerabilities. Compose configuration rendered
  successfully with both provider configurations.

Live-provider OAuth, token permission, webhook, and protected-branch scenarios
remain environment-dependent and are listed below.

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
  encryption/redaction, provider identity, Git/GitLab/GitHub adapters, exact snapshots,
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

The following checks require each enabled target code host, OAuth applications,
project bot tokens, a Pi provider credential, TLS hostname, and a PostgreSQL-backed
production-like VM. Run them before the first production promotion for both GitLab
and GitHub:

- Trigger Bash → Pi → test and verify branch, commits, reviewer, logs and change request.
- Complete two review-loop feedback rounds, approve, verify approval reset, then
  confirm a fresh final provider approval is required.
- Fail one member of a parallel wave, verify full rollback, resume, and confirm
  both attempts increment.
- Restart the backend during a root wave and a child wave; confirm `INTERRUPTED`
  classification and clean resume.
- Replay an identical webhook delivery key and confirm one feedback event.
- Inspect a database dump, snapshot, engine log, and output metadata for absence
  of decrypted credentials.
- Validate/adapt the final Caddy configuration and test spoofed identity headers.

Record the date, operator, provider/version, Pi version, and result for each item in
the deployment change record.
