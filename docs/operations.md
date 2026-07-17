# Operations runbook

This service must remain behind Caddy/OAuth and must run exactly one backend
worker. Do not enable Uvicorn reload in production and do not publish backend,
auth-service, or PostgreSQL ports on the host.

## Deployment

Copy `.env.example` to a root-readable protected `.env`, configure GitLab OAuth
and webhook settings, choose the external URL, generate independent encryption
and session-signing keys, then run:

```bash
docker compose -f deploy/docker-compose.yml build
docker compose -f deploy/docker-compose.yml up -d
```

The Compose file treats `.env` as required. A missing file now fails during
configuration instead of allowing PostgreSQL and the OAuth service to enter
restart loops. `POSTGRES_PASSWORD` and the password component of `DATABASE_URL`
must be identical.

The backend entrypoint runs `alembic upgrade head` before starting the single
Uvicorn worker. Do not start a second backend container while migrations or run
recovery are active.

Validate Caddy before promotion with `caddy validate` and review `caddy adapt`
output for route ordering and trusted-header removal.

## Backup and restore

Back up PostgreSQL, `/var/workflowengine/run_data`, Caddy data when certificate
continuity matters, and the credential/session keys through a separate secret
backup channel. Restoring the database without the credential encryption key
makes stored credentials unrecoverable. Restore PostgreSQL and filesystem data,
restore keys, run migrations, then start exactly one backend instance so startup
recovery can classify interrupted work.

## Incident actions

- For a stuck process, request run cancellation through the API before host-level
  termination; Kyron escalates from process-group SIGTERM to SIGKILL.
- For `WORKTREE_RECOVERY_FAILED`, stop scheduling that run, inspect the stored
  wave start SHA, repair the worktree beneath the configured root, and only then
  resume.
- For approval-reset failures, repair the project token/bot permissions and retry
  approval. Never manually force the run to continue.
- If a second backend instance ran accidentally, stop both, inspect active rows
  and worktrees, then restart one instance and resume affected runs explicitly.

## Retention

Worktrees remain while an MR is open. Merge/close events trigger worktree and
local-branch cleanup. Run output is retained independently for the configured
number of days; database metadata and engine logs remain until an explicit
policy is introduced. Hourly reconciliation repairs missed webhook cleanup and
reports orphan paths before deletion.

## Release verification

Run `./scripts/verify.sh`, `npm audit` in both Node packages, and
`docker compose -f deploy/docker-compose.yml config`. Build all three images and
validate the Caddyfile inside the Caddy image before promoting it. Verify that
only 80/443 are published with `docker compose ps`.
