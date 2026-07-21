# Operations runbook

This service must remain behind Caddy/OAuth and must run exactly one backend
worker. Do not enable Uvicorn reload in production and do not publish backend,
auth-service, or PostgreSQL ports on the host.

## Deployment

Copy `.env.example` to a root-readable protected `.env`, configure GitLab and/or GitHub OAuth
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

Configure GitLab webhooks for merge-request and note events at
`/api/webhook/gitlab`. Configure GitHub webhooks for pull requests, pull-request
reviews, and issue comments at `/api/webhook/github`; GitHub must send JSON and
use `GITHUB_WEBHOOK_SECRET`. The GitHub project token needs repository contents
and pull-request write access. Its bot/app identity must also be allowed to
dismiss pull-request reviews so Kyron can consume intermediate approval.

Every protected target branch must require a fresh approving review. On GitHub,
grant the Kyron identity review-dismissal authority explicitly; do not rely only
on the optional “dismiss stale approvals on new commits” repository setting.

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

Worktrees remain while a change request is open. Merge/close events trigger worktree and
local-branch cleanup. Run output is retained independently for the configured
number of days; database metadata and engine logs remain until an explicit
policy is introduced. Terminal runs without a change request are cleaned after
`TERMINAL_WORKTREE_RETENTION_DAYS`; failed and interrupted runs retain their
separate resumability window. Hourly reconciliation repairs missed webhook
cleanup, warns about long-open change requests, and deletes only Kyron-shaped
orphans that have passed both the detection and filesystem-activity grace period.

Monitor the authenticated `/api/metrics` endpoint. Root-byte and filesystem-use
threshold transitions are written to `resource_audit_logs` and emitted through
the backend logger for alert routing.

## Release verification

Run `./scripts/verify.sh`, `npm audit` in both Node packages, and
`docker compose -f deploy/docker-compose.yml config`. Build all three images and
validate the Caddyfile inside the Caddy image before promoting it. Verify that
only 80/443 are published with `docker compose ps`.

## Publishing a GitHub prerelease

Prepare the release metadata and notes in a normal reviewed commit, merge that commit to
`main`, and wait for the `verify` and `Documentation` workflows to pass. Tag that exact
commit rather than a local commit that has not reached `main`:

```bash
git switch main
git pull --ff-only
git status --short
git tag -a v1.0-alpha -m "Kyron 1.0-alpha"
git push origin v1.0-alpha
```

In GitHub, open **Releases**, choose **Draft a new release**, select `v1.0-alpha`, use
`Kyron 1.0-alpha` as the title, and mark it as a prerelease. Summarize the release from
the [1.0-alpha notes](/releases/1.0-alpha) and link the acceptance record. Publish only
after the tag's verification workflow is green.

GitHub Pages is deployed from `main` whenever files under `docs/` change. The release
commit updates the version selector and release-notes page; the tag itself does not need
a separate Pages deployment. Confirm the `Documentation` workflow's `github-pages`
environment URL after the release commit is pushed.
