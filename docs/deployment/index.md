---
title: Production deployment
description: Deploy Kyron's supported single-VM architecture with Docker Compose.
---

# Production deployment

Kyron's supported deployment is one Linux VM running the included Docker Compose stack. Caddy is the only exposed service and exactly one backend worker owns orchestration.

## Topology

| Service | Responsibility | Host exposure |
| --- | --- | --- |
| Caddy | TLS, OAuth enforcement, trusted-header boundary, API proxy, React UI | TCP 80/443 |
| Auth service | GitLab/GitHub OAuth and signed sessions | Internal only |
| Backend | FastAPI, migrations, workflow coordinator, one worker | Internal only |
| PostgreSQL | Durable domain and execution state | Internal only |

Persistent state includes PostgreSQL, Caddy certificate data, and the host directory configured by `WORKFLOW_DATA_HOST_PATH` for clones, worktrees, logs, and run artifacts.

::: danger Single-worker invariant
Do not scale the backend container and do not add Uvicorn workers. The current coordinator and process registries are in-process. Multiple workers can execute the same run concurrently.
:::

## 1. Prepare the VM

A reasonable starting point for a small internal installation is Ubuntu Server 24.04 LTS, 4 vCPU, 8 GB RAM, and 50 GB SSD. Repository size, build tooling, concurrent runs, and retention determine real capacity. Hosts that execute Prompt nodes must expose Landlock ABI 3 or newer to the backend container; Ubuntu 24.04's standard kernel satisfies this requirement.

Allow inbound:

- TCP 22 from administrator ranges only;
- TCP 80 for ACME HTTP validation; and
- TCP 443 for users, OAuth callbacks, and provider webhooks.

The VM needs outbound HTTPS to the configured code host, model providers, container/package registries, and an ACME certificate authority.

Choose a stable hostname and point DNS to the VM before starting Caddy.

## 2. Install Docker

Install Docker Engine and the Compose v2 plugin from Docker's official Ubuntu repository. Verify Compose 2.24 or newer:

```bash
sudo docker version
sudo docker compose version
```

Keep the Docker socket private. Membership in the `docker` group is effectively root access.

## 3. Install Kyron and storage

Use a stable checkout path and a reviewed tag or commit:

```bash
sudo git clone <KYRON_REPOSITORY_URL> /opt/kyron
cd /opt/kyron
```

Create the backend data root. The image runs as UID/GID `10001`:

```bash
sudo install -d -m 0750 -o 10001 -g 10001 /var/workflowengine
sudo install -d -m 0750 -o 10001 -g 10001 \
  /var/workflowengine/repos \
  /var/workflowengine/worktrees \
  /var/workflowengine/run_data
```

Use durable storage. Budget for complete clones, concurrent worktrees, build output, and retained process output.

## 4. Configure identity and secrets

Create at least one GitLab or GitHub OAuth application. The external callback must exactly match:

```text
https://kyron.example.com/auth/callback
```

Copy and protect the environment file:

```bash
sudo cp .env.example .env
sudo chown root:root .env
sudo chmod 600 .env
```

Follow [configuration](/deployment/configuration) for every setting and [provider setup](/deployment/providers) for OAuth, repository token, and webhook permissions.

## 5. Validate before startup

```bash
sudo docker compose -f deploy/docker-compose.yml --env-file .env config --quiet
sudo docker compose -f deploy/docker-compose.yml build
sudo docker compose -f deploy/docker-compose.yml --env-file .env run --rm \
  --no-deps --entrypoint python backend \
  /app/backend/engine/pi/write_sandbox.py --check
```

The compatibility check must report a supported Landlock ABI. Inspect the resolved Compose configuration. Only Caddy should publish ports. Confirm the backend command starts one Uvicorn worker and does not enable reload.

## 6. Start and verify

```bash
sudo docker compose -f deploy/docker-compose.yml up -d
sudo docker compose -f deploy/docker-compose.yml ps
sudo docker compose -f deploy/docker-compose.yml logs --tail=200 backend auth-service caddy
```

The backend entrypoint runs `alembic upgrade head` before starting. Do not start another backend while migrations or startup reconciliation are active.

Verify:

1. HTTPS is valid at `APP_BASE_URL`.
2. Each configured provider appears on the sign-in page.
3. OAuth returns to the exact callback URL.
4. `/api/health` reports a healthy backend and database.
5. A test project validates, fetches, and lists merged workflows.
6. Signed provider webhooks are accepted and duplicate deliveries are ignored.
7. A disposable run can checkpoint, pause for feedback, resume, and clean up after merge/close.

## Back up before inviting users

Back up these as one recoverable system:

- PostgreSQL;
- `/var/workflowengine/run_data` and required worktree/clone state;
- the credential encryption key;
- current and previous session-signing keys; and
- Caddy state if certificate continuity matters.

Restoring encrypted credential rows without the Fernet key makes them permanently unreadable.

## Production checklist

- [ ] Only Caddy exposes host ports.
- [ ] Exactly one backend container and one Uvicorn worker run.
- [ ] `.env` is root-owned, mode `0600`, and excluded from version control.
- [ ] Database and filesystem backups were restored in a rehearsal.
- [ ] GitLab/GitHub webhook signatures and replay protection were tested.
- [ ] Protected branches require a fresh approval.
- [ ] The Kyron provider identity can consume intermediate approvals.
- [ ] The backend container reports Landlock ABI 3 or newer.
- [ ] Storage, memory, and retention alerts are configured.
- [ ] Only trusted authors and repositories have access.
- [ ] A release-specific `./scripts/verify.sh` record exists.

For exhaustive host commands, private TLS, upgrades, and restore rehearsal, use the repository's [VM setup runbook](https://github.com/anomaes/Kyron/blob/main/SETUP.md).
