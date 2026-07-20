---
title: Configuration
description: Environment variables and limits for the Kyron production stack.
---

# Configuration

The repository `.env.example` is the authoritative deployment template. Keep `.env` aligned with it and never commit real values.

## Application and database

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | Use `production` on a deployed instance |
| `APP_BASE_URL` | External origin, including scheme |
| `APP_HOST` | Hostname served by Caddy |
| `LOG_LEVEL` | Backend log level |
| `DATABASE_URL` | Async SQLAlchemy PostgreSQL URL |
| `POSTGRES_PASSWORD` | PostgreSQL container password; must match `DATABASE_URL` |
| `DB_POOL_SIZE` | Persistent database pool size |
| `DB_MAX_OVERFLOW` | Temporary connections above the pool size |

`APP_BASE_URL`, OAuth callback, Caddy host, and provider application URLs must describe the same public origin.

## Encryption and sessions

| Variable | Purpose |
| --- | --- |
| `CREDENTIALS_ENCRYPTION_KEY` | Fernet key for stored credentials; mandatory in production |
| `CREDENTIALS_ENCRYPTION_KEY_VERSION` | Metadata version for the current encryption key |
| `SESSION_SIGNING_KEY` | Current auth-session signing key, at least 32 random characters |
| `SESSION_PREVIOUS_SIGNING_KEY` | Optional previous key during a bounded rotation window |
| `SESSION_MAX_AGE_SECONDS` | Signed browser session lifetime |
| `AUTH_USER_TOUCH_INTERVAL_SECONDS` | Minimum interval between durable user metadata refreshes |

Generate the two keys independently and back them up through a secret channel separate from the database backup.

## Provider configuration

| Variable | Purpose |
| --- | --- |
| `GITLAB_URL` | GitLab web root |
| `GITLAB_OAUTH_CLIENT_ID` / `GITLAB_OAUTH_CLIENT_SECRET` | GitLab OAuth application |
| `GITLAB_WEBHOOK_SECRET` | Shared token for GitLab webhook authentication |
| `GITLAB_WEBHOOK_SIGNING_SECRET` | Optional Standard Webhooks signature secret |
| `GITHUB_WEB_URL` | GitHub or GHES web root |
| `GITHUB_API_URL` | GitHub REST API root |
| `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` | GitHub OAuth application |
| `GITHUB_WEBHOOK_SECRET` | HMAC secret for `X-Hub-Signature-256` |
| `OAUTH_REDIRECT_URI` | Exact shared callback ending in `/auth/callback` |

A provider is enabled on the sign-in page only when both its OAuth ID and secret are present. See [provider setup](/deployment/providers).

## Filesystem roots

| Variable | Default production path | Content |
| --- | --- | --- |
| `PROJECT_CLONE_BASE_PATH` | `/var/workflowengine/repos` | Cached repository clones |
| `WORKTREE_BASE_PATH` | `/var/workflowengine/worktrees` | Isolated run worktrees |
| `RUN_DATA_BASE_PATH` | `/var/workflowengine/run_data` | Output, Pi events, logs, artifacts |
| `WORKFLOW_DATA_HOST_PATH` | `/var/workflowengine` | Host path mounted into the backend |

All paths must be explicit, durable, writable by UID/GID `10001`, and dedicated to Kyron. The backend validates derived paths against these configured roots.

## Execution limits

| Variable | Example | Effect |
| --- | ---: | --- |
| `MAX_CONCURRENT_RUNS` | `10` | In-process run semaphore |
| `DEFAULT_NODE_TIMEOUT_SECONDS` | `1800` | Default process timeout |
| `MAX_NODE_TIMEOUT_SECONDS` | `14400` | Maximum workflow-requested timeout |
| `MAX_REVIEW_ITERATIONS` | `10` | Server cap for review loops |
| `MAX_SUBWORKFLOW_DEPTH` | `8` | Server cap for nested invocations |
| `MAX_OUTPUT_VARIABLE_BYTES` | `65536` | Public output preview bound |
| `PROCESS_TERMINATION_GRACE_SECONDS` | `10` | Delay between `SIGTERM` and `SIGKILL` |

`MAX_NODE_TIMEOUT_SECONDS` must be at least the default. Workflow settings may request smaller limits but cannot bypass server caps.

## Reconciliation and retention

| Variable | Example | Effect |
| --- | ---: | --- |
| `QUEUE_RECONCILIATION_INTERVAL_SECONDS` | `60` | Detect queued work requiring scheduling |
| `STALE_RESOURCE_RECONCILIATION_INTERVAL_SECONDS` | `3600` | Repair missed cleanup and inspect orphans |
| `STALE_FAILED_RUN_DAYS` | `7` | Failed-run cleanup age policy |
| `TERMINAL_WORKTREE_RETENTION_DAYS` | `1` | Retain terminal worktrees that have no change request |
| `ORPHAN_WORKTREE_GRACE_HOURS` | `24` | Minimum time after orphan detection and last activity before deletion |
| `RUN_OUTPUT_RETENTION_DAYS` | `30` | Attempt output retention |
| `LONG_OPEN_CHANGE_REQUEST_WARNING_DAYS` | `14` | Age at which an open PR/MR emits a run warning |
| `LONG_OPEN_CHANGE_REQUEST_WARNING_REPEAT_DAYS` | `7` | Minimum interval between repeated open-PR/MR warnings |
| `WORKTREE_USAGE_WARNING_BYTES` | `53687091200` | Worktree-root byte threshold; `0` disables it |
| `RUN_DATA_USAGE_WARNING_BYTES` | `53687091200` | Run-data-root byte threshold; `0` disables it |
| `FILESYSTEM_USAGE_WARNING_PERCENT` | `85` | Filesystem utilization warning threshold |

Database metadata and durable engine logs are not automatically governed by the output-file retention value.

Authenticated operators can scrape `/api/metrics` in Prometheus text format. It
reports bytes and file counts beneath both managed roots, filesystem capacity and
utilization, and threshold-state gauges. Threshold transitions and orphan cleanup
events are also persisted in `resource_audit_logs`.

## Pi version

`PI_VERSION` pins the coding-agent build installed in the backend image. Treat a change as a dependency upgrade: review release behavior, rebuild the image, and run prompt-node integration checks before production promotion.

## Safe configuration changes

1. Back up `.env` securely and record the current image/commit.
2. Change one configuration group at a time.
3. Run Compose configuration validation.
4. Rebuild only when image inputs changed.
5. Restart exactly one backend.
6. Verify health, authentication, and a disposable workflow.

Never use an environment change to bypass a failed durable state transition. Repair the underlying provider, credential, or worktree condition and continue through Kyron's API.
