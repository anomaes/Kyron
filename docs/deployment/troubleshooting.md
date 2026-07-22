---
title: Troubleshooting
description: Diagnose common deployment, OAuth, webhook, storage, and run failures.
---

# Troubleshooting

Start with the smallest safe observation. Avoid deleting volumes, resetting worktrees, or mutating durable state until the exact target and recovery boundary are known.

## Caddy cannot obtain a certificate

Check:

1. `APP_HOST` resolves to the VM's public address.
2. TCP 80 and 443 reach the VM through cloud and host firewalls.
3. No second proxy owns those ports.
4. An `AAAA` record is not pointing at broken IPv6 connectivity.
5. Caddy data is writable and the hostname is valid for public ACME.

For private-only DNS, use an intentional internal TLS design and distribute trust to clients; do not expose backend ports as a shortcut.

## Address already in use

Inspect host listeners and existing containers. The included Caddy instance should own 80/443. Stop or reconfigure the conflicting service deliberately instead of adding another proxy layer without revisiting trusted-header handling.

## Backend is unhealthy or restarting

Review backend and PostgreSQL logs together. Common causes are:

- missing production encryption key;
- database password mismatch;
- unavailable PostgreSQL;
- migration failure;
- unwritable configured storage roots; or
- invalid execution limits.

Do not scale the backend to “fix” availability. Start exactly one healthy instance.

## OAuth callback fails

Verify the external origin and callback match character-for-character across:

- `APP_BASE_URL`;
- `APP_HOST`;
- `OAUTH_REDIRECT_URI`;
- provider application callback; and
- the browser URL.

Check session-signing key consistency and system time. OAuth state is provider-bound and time-limited.

## Provider is missing from sign-in

A provider appears only when both its OAuth client ID and client secret are configured. Check the container's resolved environment, then restart the auth service after correcting it.

## Webhook returns 401

For GitLab, compare the shared token and optional signing secret. For GitHub, confirm the webhook sends JSON and that `GITHUB_WEBHOOK_SECRET` matches. Reverse proxies must preserve the raw body; signature validation happens before JSON normalization.

Use a new provider delivery for each manual test. A previously accepted delivery ID is correctly treated as a duplicate.

## Webhook is accepted but run does not continue

Confirm:

- the event belongs to the registered provider project;
- the run is currently awaiting feedback;
- the top-level actor is the triggering reviewer;
- the comment is non-system and addresses `@kyron`, when applicable; and
- approval reset/dismissal permissions are present.

A stale transition returns conflict rather than advancing twice.

## Clone or worktree is not writable

The backend image uses UID/GID `10001`. Verify the host data root and its child directories are owned accordingly and mounted at the paths configured inside the container.

Do not fix permissions by making the entire host path world-writable.

## Run fails immediately

Inspect the first durable engine error and the workflow snapshot. Common authoring causes include:

- missing required trigger input;
- a child workflow absent at the selected base commit;
- unknown public template variable;
- script or file path escaping the repository;
- timeout above the server maximum; or
- unavailable Pi/model credentials.

If the definition itself is wrong, merge a fix and start a new run. Existing snapshots do not change.

## Prompt exits before Pi starts

An error beginning with `Kyron Pi write sandbox` means the backend could not enforce
the Prompt process's worktree write boundary. Check the deployment directly:

```bash
sudo docker compose -f deploy/docker-compose.yml --env-file .env run --rm \
  --no-deps --entrypoint python backend \
  /app/backend/engine/pi/write_sandbox.py --check
```

Prompt execution requires Linux Landlock ABI 3 or newer and a container runtime whose
security profile permits the Landlock syscalls. Use the supported Linux VM deployment,
or upgrade the host kernel and container runtime. Some Linux virtual machines used by
desktop container products do not expose Landlock even when the physical host is
current. Kyron fails closed instead of running Pi without the write boundary.

## Resume repeats successful-looking nodes

This is expected when nodes shared a failed wave. Their combined filesystem changes were rolled back to the wave start. Resume creates fresh attempts for the whole wave to preserve a coherent checkpoint.

## Disk usage grows

Inspect PostgreSQL, Docker layers, repository clones, active worktrees, and run output separately. Worktrees remain while a change request is open. Output cleanup uses `RUN_OUTPUT_RETENTION_DAYS`; durable database metadata follows its own policy.

Do not recursively delete the workflow data root. Use Kyron cleanup/reconciliation, validate each orphan path against the configured roots, and preserve open-run resources.

## Escalation bundle

Before escalating an incident, capture:

- Kyron commit or release;
- sanitized Compose configuration;
- container status and restart counts;
- run ID, base SHA, status, failed wave, and attempt number;
- relevant durable engine log sequence IDs;
- provider delivery ID and event type; and
- storage/memory capacity.

Never include `.env`, credential values, project tokens, or authenticated URLs.
