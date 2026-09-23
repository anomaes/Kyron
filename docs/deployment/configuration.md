---
title: Configuration
description: Environment variables and limits for the Kyron production stack.
---

# Configuration

The repository `.env.example` is the authoritative production deployment
template. Keep `.env` aligned with it and never commit real values. Defaults
below are the shipped template/runtime defaults; placeholders such as
`replace-me` are deliberately invalid production choices and must be replaced.

Unless a section says otherwise, an environment change requires recreating the
service that consumes it. `docker compose up -d` performs that recreation after
Compose validation. `PI_VERSION`, frontend source, and Caddyfile changes require
an image rebuild. Database-managed AI-provider revisions take effect for newly
queued runs without a container restart.

## Application and database

| Variable | Default/template value | Constraints and purpose |
| --- | --- | --- |
| `APP_ENV` | `production` in `.env.example` | Use `production` for a deployment; `development` relaxes secure-cookie behavior and is not a production option |
| `APP_HOST` | `workflow.example.internal` | Hostname only, without scheme, port, or path; served by Caddy |
| `LOG_LEVEL` | `INFO` | `CRITICAL`, `ERROR`, `WARNING`, `INFO`, or `DEBUG` |
| `DATABASE_URL` | Compose PostgreSQL URL | Async SQLAlchemy URL; password must match `POSTGRES_PASSWORD` |
| `POSTGRES_PASSWORD` | placeholder | Required PostgreSQL container password |
| `DB_POOL_SIZE` | `20` | Integer ≥ 1; persistent database pool size |
| `DB_MAX_OVERFLOW` | `10` | Integer ≥ 0; temporary connections above the pool size |

The OAuth callback, Caddy host, and provider application URLs must describe the same public origin.

## Encryption and sessions

| Variable | Default/template value | Constraints and purpose |
| --- | --- | --- |
| `CREDENTIALS_ENCRYPTION_KEY` | placeholder | URL-safe Fernet key; mandatory in production |
| `CREDENTIALS_ENCRYPTION_KEY_VERSION` | `1` | Integer ≥ 1; metadata version for controlled key rotation |
| `SESSION_SIGNING_KEY` | placeholder | Required, at least 32 random characters |
| `SESSION_PREVIOUS_SIGNING_KEY` | empty | Optional previous key during a bounded rotation window |
| `SESSION_MAX_AGE_SECONDS` | `28800` | Signed browser-session lifetime |
| `AUTH_USER_TOUCH_INTERVAL_SECONDS` | `300` | Integer ≥ 0; minimum durable user-metadata refresh interval |
| `VSCODE_DEVICE_CODE_TTL_SECONDS` | `600` | 60–1800 seconds; one-time connection-code lifetime |
| `VSCODE_DEVICE_POLL_INTERVAL_SECONDS` | `3` | 1–30 seconds; minimum authorization polling interval |
| `VSCODE_ACCESS_TOKEN_TTL_SECONDS` | `900` | 60–86400 seconds; short-lived bearer credential |
| `VSCODE_REFRESH_TOKEN_TTL_DAYS` | `30` | 1–365 days; maximum client session without reconnecting |

Generate the two keys independently and back them up through a secret channel separate from the database backup.

## Provider configuration

| Variable | Default/template value | Constraints and purpose |
| --- | --- | --- |
| `GITLAB_URL` | instance-specific placeholder | HTTPS GitLab web root; use `https://gitlab.com` for SaaS |
| `GITLAB_OAUTH_CLIENT_ID` / `GITLAB_OAUTH_CLIENT_SECRET` | placeholders | Configure both to enable GitLab, or leave both empty |
| `GITHUB_WEB_URL` | `https://github.com` | GitHub or GHES web root |
| `GITHUB_API_URL` | `https://api.github.com` | GitHub REST API root; change both GitHub URLs for GHES |
| `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` | placeholders | Configure both to enable GitHub, or leave both empty |
| `OAUTH_REDIRECT_URI` | hostname-specific placeholder | Required exact HTTPS callback ending in `/auth/callback` |

A provider is enabled on the sign-in page only when both its OAuth ID and secret are present. See [provider setup](/deployment/providers).

Webhook secrets are encrypted project settings managed from the Projects page. They are
not deployment environment variables and do not need to be copied into Kubernetes Secrets
or container environment files.

## Filesystem roots

| Variable | Default production path | Content |
| --- | --- | --- |
| `PROJECT_CLONE_BASE_PATH` | `/var/workflowengine/repos` | Cached repository clones |
| `WORKTREE_BASE_PATH` | `/var/workflowengine/worktrees` | Isolated run worktrees |
| `RUN_DATA_BASE_PATH` | `/var/workflowengine/run_data` | Output, Pi events, logs, artifacts |
| `WORKFLOW_DATA_HOST_PATH` | `/var/workflowengine` | Host path mounted into the backend |

All paths must be explicit, durable, writable by UID/GID `10001`, and dedicated to Kyron. The backend validates derived paths against these configured roots.

## Execution limits

| Variable | Default | Effect and valid range |
| --- | ---: | --- |
| `MAX_CONCURRENT_RUNS` | `10` | Integer ≥ 1; in-process run semaphore |
| `MAX_NODE_TIMEOUT_SECONDS` | `14400` | Integer ≥ 1; maximum workflow-requested timeout |
| `MAX_REVIEW_ITERATIONS` | `10` | Integer ≥ 1; server cap for review loops |
| `MAX_SUBWORKFLOW_DEPTH` | `8` | Integer ≥ 1; server cap for nested invocations |
| `MAX_OUTPUT_VARIABLE_BYTES` | `65536` | Integer ≥ 1024; public output preview bound |
| `MAX_ATTEMPT_OUTPUT_BYTES` | `104857600` | Integer ≥ 1024; combined stdout/stderr persisted per attempt |
| `PROCESS_STREAM_DRAIN_TIMEOUT_SECONDS` | `30` | Number > 0; pipe-drain timeout after the direct child exits |
| `WORKFLOW_CATALOG_CACHE_TTL_SECONDS` | `30` | Integer ≥ 0; `0` disables process-local catalog caching |
| `PROCESS_TERMINATION_GRACE_SECONDS` | `10` | Number ≥ 0; delay between `SIGTERM` and `SIGKILL` |

Workflow settings may request smaller limits but cannot bypass server caps.

## Reconciliation and retention

| Variable | Default | Effect and valid range |
| --- | ---: | --- |
| `QUEUE_RECONCILIATION_INTERVAL_SECONDS` | `60` | Integer ≥ 1; detect queued work requiring scheduling |
| `STALE_RESOURCE_RECONCILIATION_INTERVAL_SECONDS` | `3600` | Integer ≥ 60; repair missed cleanup and inspect orphans |
| `STALE_FAILED_RUN_DAYS` | `7` | Integer ≥ 1; failed-run cleanup age |
| `TERMINAL_WORKTREE_RETENTION_DAYS` | `1` | Integer ≥ 0; retain terminal worktrees without a change request |
| `ORPHAN_WORKTREE_GRACE_HOURS` | `24` | Integer ≥ 1; grace after orphan detection and last activity |
| `RUN_OUTPUT_RETENTION_DAYS` | `30` | Integer ≥ 1; attempt-output retention |
| `LONG_OPEN_CHANGE_REQUEST_WARNING_DAYS` | `14` | Integer ≥ 1; age at which an open PR/MR emits a warning |
| `LONG_OPEN_CHANGE_REQUEST_WARNING_REPEAT_DAYS` | `7` | Integer ≥ 1; repeated-warning interval |
| `WORKTREE_USAGE_WARNING_BYTES` | `53687091200` | Integer ≥ 0; worktree-root warning threshold, `0` disables |
| `RUN_DATA_USAGE_WARNING_BYTES` | `53687091200` | Integer ≥ 0; run-data warning threshold, `0` disables |
| `FILESYSTEM_USAGE_WARNING_PERCENT` | `85` | Integer 1–100; filesystem utilization warning threshold |

Database metadata and durable engine logs are not automatically governed by the output-file retention value.

Authenticated operators can scrape `/api/metrics` in Prometheus text format. It
reports bytes and file counts beneath both managed roots, filesystem capacity and
utilization, and threshold-state gauges. Threshold transitions and orphan cleanup
events are also persisted in `resource_audit_logs`.

## Pi version

`PI_VERSION` defaults to the version pinned in `.env.example` and selects the
coding-agent build installed in the backend image. Treat a change as a
dependency upgrade: review release behavior, rebuild the image, and run
prompt-node integration checks before production promotion.

## Custom Pi providers

System administrators manage custom Pi providers from **Administration → AI providers**. The backend validates every proposed configuration with the installed Pi version before activation, records an audit event, and retains earlier revisions for rollback. A run snapshots the active revision when it is queued, so later administrative changes affect new runs only.

The active configuration and its history live in PostgreSQL. An independently
maintained Kubernetes adaptation therefore needs no `models.json` volume or
ConfigMap for normal administration, although Kubernetes itself is not a
supported Kyron deployment mode. Save and activate the configuration in the UI
after the database migration is deployed.

The guided editor covers common OpenAI-compatible, Anthropic-compatible, and Google-compatible endpoints. Its bearer and `x-api-key` credential fields may be used independently or together. Both accept Kyron credential names rather than secret values. Pi requires every custom model to resolve provider authentication even when a gateway authenticates only through a custom header, so Kyron also uses an `x-api-key`-only credential as Pi's provider key while sending it in the explicit `x-api-key` header. The advanced JSON editor supports the complete Pi [models configuration](https://github.com/earendil-works/pi-mono/blob/main/packages/coding-agent/docs/models.md):

```json
{
  "providers": {
    "private-gateway": {
      "baseUrl": "https://llm.example.com/v1",
      "api": "openai-completions",
      "apiKey": "$CUSTOM_LLM_BEARER_TOKEN",
      "authHeader": true,
      "headers": { "x-api-key": "$CUSTOM_LLM_API_KEY" },
      "models": [{ "id": "example-chat-model", "contextWindow": 128000, "maxTokens": 16384 }]
    }
  }
}
```

The configured providers and declared models appear as suggestions in project defaults, workflow settings, and prompt nodes. These fields continue to accept Pi built-ins and follow the normal node → workflow → project inheritance order.

Every prompt attempt runs with a fresh, empty Pi agent directory, so an operator's `~/.pi/agent/models.json` is never visible to a run. Kyron materializes the run's snapshotted configuration as a mode `0600` `models.json` immediately before Pi starts.

### Optional file bootstrap

`PI_MODELS_CONFIG_PATH` is an optional bootstrap/fallback path. It does **not** need to be populated when providers are managed through Administration. Kyron reads it only when no database revision is active; database and file configurations are never silently merged.

For file-managed or GitOps bootstrapping, mount the file into the backend container and set its absolute container path:

Place the file inside the mounted data root so the backend container can read it, and restrict it to the runtime user:

```bash
sudo install -d -m 0750 -o 10001 -g 10001 /var/workflowengine/pi
sudo install -m 0600 -o 10001 -g 10001 models.json /var/workflowengine/pi/models.json
```

```dotenv
PI_MODELS_CONFIG_PATH=/var/workflowengine/pi/models.json
```

Operational notes:

- An `apiKey` or secret-like header must reference one or more environment variables, such as `$CUSTOM_LLM_API_KEY`; inline and command-based (`!command`) keys are rejected because the Pi agent can read its own configuration file. Add a Kyron credential for every referenced variable. The run's credential policy must make those credentials available, which also ensures their values are redacted from persisted process output. Backend container variables and public workflow context cannot satisfy this requirement.
- A missing or invalid optional bootstrap file fails prompt nodes rather than silently falling back to the built-in catalog. The parser accepts the same `//` comments and trailing commas as the pinned Pi version.

## Safe configuration changes

1. Back up `.env` securely and record the current image/commit.
2. Change one configuration group at a time.
3. Run Compose configuration validation.
4. Rebuild only when image inputs changed.
5. Restart exactly one backend.
6. Verify health, authentication, and a disposable workflow.

Never use an environment change to bypass a failed durable state transition. Repair the underlying provider, credential, or worktree condition and continue through Kyron's API.
