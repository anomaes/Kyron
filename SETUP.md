# Deploying Kyron on a VM

This guide deploys Kyron on one Linux VM with the production Docker Compose
stack included in this repository. It covers the host, DNS, TLS, OAuth,
webhooks, secrets, persistent storage, startup, validation, upgrades, and
backups.

Kyron executes Bash, Python, and Pi processes against checked-out repositories.
Pi Prompt processes are write-confined to their run worktree and ephemeral
scratch space; Bash and Python processes are unrestricted, and Pi retains read,
credential, network, and compute access. Kyron is therefore an internal
orchestration service rather than a hostile-code sandbox. Deploy it only for
trusted users and repositories, and keep every service behind the included
Caddy/OAuth boundary.

## What the deployment runs

`deploy/docker-compose.yml` starts four services:

| Service | Purpose | Host exposure |
| --- | --- | --- |
| `caddy` | TLS, OAuth enforcement, API proxy, and static React UI | TCP 80 and 443 |
| `auth-service` | GitLab/GitHub OAuth login and signed sessions | Internal only |
| `backend` | FastAPI API and the single in-process workflow worker | Internal only |
| `postgres` | PostgreSQL 16 | Internal only |

Caddy is already part of the stack. `deploy/Caddy.Dockerfile` builds the React
frontend and copies it into the Caddy image, while `deploy/Caddyfile` routes
requests and enforces authentication. Do not install a second Caddy instance on
the host unless you intentionally redesign the proxy and trusted-header
boundary.

The deployment persists:

- PostgreSQL in the `postgres_data` named Docker volume;
- Caddy certificates and state in the `caddy_data` and `caddy_config` named
  volumes; and
- repository clones, worktrees, run logs, and artifacts in the host directory
  configured by `WORKFLOW_DATA_HOST_PATH` (normally `/var/workflowengine`).

Production must run exactly **one `backend` container and one Uvicorn worker**.
Do not use `docker compose up --scale backend=...`, and do not add a separate
worker process.

## 1. Plan the VM and network

### Suggested starting size

For a small internal installation, start with:

- Ubuntu Server 24.04 LTS, 64-bit x86, with the standard Landlock-enabled kernel;
- 4 vCPU;
- 8 GB RAM; and
- at least 50 GB of SSD storage.

This is a starting point, not a hard requirement. Repository size, concurrent
runs, build tools invoked by workflows, and retained output usually determine
the real capacity. On a small VM, reduce `MAX_CONCURRENT_RUNS` from its default
of 10. Monitor memory, disk usage, and `/var/lib/docker` before increasing it.

### Required connectivity

Allow these inbound connections at the cloud firewall/security-group layer:

- TCP 22 from administrator IP ranges only;
- TCP 80 from users and the public internet when Caddy obtains public
  certificates; and
- TCP 443 from users, GitLab/GitHub webhook senders, and the public internet
  when using public OAuth providers.

The VM needs outbound DNS and HTTPS access to:

- the configured GitLab and/or GitHub host;
- the model providers used by Pi prompt nodes;
- Docker registries, package registries, and Git hosts during image builds and
  upgrades; and
- a public ACME certificate authority when using Caddy automatic HTTPS.

Only Caddy should publish host ports. The backend, auth service, and PostgreSQL
must not be reachable directly from another machine. Docker-published ports can
bypass some host firewall rule paths, including common UFW configurations, so
enforce the same restrictions in the VM provider's network firewall. See
[Docker's firewall warning](https://docs.docker.com/engine/install/ubuntu/#firewall-limitations).

### DNS and hostname

Choose one stable hostname, for example `kyron.example.com`, and create an `A`
record pointing to the VM's public IPv4 address. Create an `AAAA` record only if
IPv6 is configured and inbound TCP 80/443 works over IPv6 too.

Check the result before starting Caddy:

```bash
getent ahosts kyron.example.com
```

For a publicly trusted certificate, the hostname must resolve correctly and the
VM must be externally reachable on ports 80 and 443. Caddy then obtains and
renews the certificate automatically. These are the prerequisites documented in
Caddy's [HTTPS quick start](https://caddyserver.com/docs/quick-starts/https).

Private-only DNS is covered in [Private networks and internal TLS](#private-networks-and-internal-tls).

## 2. Prepare Ubuntu

Log in with an administrative account and update the host:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y ca-certificates curl git openssl
sudo timedatectl set-ntp true
```

Keep time synchronization enabled. OAuth state and optional signed GitLab
webhook timestamps are time-sensitive.

Configure the provider firewall before enabling a host firewall so that the SSH
session cannot be locked out. A minimal UFW policy, when UFW is part of the host
design, is:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

Restrict the SSH rule to the actual administrator CIDR where possible. Remember
that the cloud firewall remains important for Docker-published ports.

## 3. Install Docker Engine and Compose

Install Docker from Docker's official Ubuntu repository rather than the distro's
legacy `docker.io`/`docker-compose` packages:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

These commands follow Docker's current
[Ubuntu installation instructions](https://docs.docker.com/engine/install/ubuntu/).
Verify both the daemon and the Compose v2 plugin:

```bash
sudo docker version
sudo docker compose version
sudo docker run --rm hello-world
```

Kyron requires Docker Compose 2.24.0 or newer because the Compose file uses the
required `env_file` syntax. The current plugin from Docker's repository satisfies
this requirement.

All commands below use `sudo docker`. Membership in the `docker` group is
effectively root-level access to the host, so grant it only as an explicit
administrative decision. Do not expose the Docker socket over TCP.

## 4. Install the Kyron checkout

Use a fixed path so operating procedures and backup jobs do not depend on an
administrator's home directory. Replace `<KYRON_REPOSITORY_URL>` with the source
or release repository URL:

```bash
sudo git clone <KYRON_REPOSITORY_URL> /opt/kyron
cd /opt/kyron
sudo git status --short
```

Prefer a tagged release or a reviewed commit rather than an unpinned moving
branch. Never put a personal access token directly in the clone URL; use an SSH
deploy key or an interactive credential mechanism if the source repository is
private.

Create the backend's persistent host directory. The backend image runs as UID
and GID `10001`, so this ownership is required for clones, worktrees, and run
data to be writable:

```bash
sudo install -d -m 0750 -o 10001 -g 10001 /var/workflowengine
sudo install -d -m 0750 -o 10001 -g 10001 \
  /var/workflowengine/repos \
  /var/workflowengine/worktrees \
  /var/workflowengine/run_data
```

Do not place `/var/workflowengine` on temporary storage. Estimate space for full
repository clones, concurrent worktrees, build output, and retained run data.

## 5. Create OAuth applications

Kyron requires at least one provider. You can enable GitLab, GitHub, or both.
The browser identity is separate from the per-project token used for Git and API
operations.

Use the exact external callback URL everywhere:

```text
https://kyron.example.com/auth/callback
```

Do not use a trailing slash, a VM IP address, or a different host alias.

### GitLab OAuth

Create an OAuth application in the GitLab instance used by the team:

- redirect/callback URI: `https://kyron.example.com/auth/callback`;
- scope: `read_user`; and
- confidential client: enabled.

Record the application/client ID and secret for `.env`. Set `GITLAB_URL` to the
GitLab web root, such as `https://gitlab.com` or the root URL of a self-managed
instance.

### GitHub OAuth

Create a GitHub OAuth App:

- homepage URL: `https://kyron.example.com`; and
- authorization callback URL:
  `https://kyron.example.com/auth/callback`.

Record the client ID and client secret for `.env`. Kyron requests the
`read:user user:email` scopes. For GitHub Enterprise Server, set both its web URL
and API URL rather than retaining the public GitHub defaults.

## 6. Configure production secrets

Copy the complete environment template and protect it before editing:

```bash
cd /opt/kyron
sudo cp .env.example .env
sudo chown root:root .env
sudo chmod 600 .env
sudoedit .env
```

Generate each secret independently. Run each command separately and paste its
output directly into the corresponding `.env` value:

```bash
# CREDENTIALS_ENCRYPTION_KEY (valid Fernet key)
openssl rand -base64 32 | tr '/+' '_-'

# SESSION_SIGNING_KEY
openssl rand -hex 48

# POSTGRES_PASSWORD (also used inside DATABASE_URL)
openssl rand -hex 24

# One independent value for each enabled provider's webhook secret
openssl rand -hex 32
```

Do not reuse the session, database, webhook, or credential-encryption keys. Keep
an encrypted copy of `.env` in a separate secret manager or backup system. If
`CREDENTIALS_ENCRYPTION_KEY` is lost, credentials stored by Kyron cannot be
recovered from the database.

At minimum, review every value below:

```dotenv
APP_ENV=production
APP_BASE_URL=https://kyron.example.com
APP_HOST=kyron.example.com
LOG_LEVEL=INFO

POSTGRES_PASSWORD=<DATABASE_PASSWORD>
DATABASE_URL=postgresql+asyncpg://workflow_engine:<DATABASE_PASSWORD>@postgres:5432/workflow_engine

CREDENTIALS_ENCRYPTION_KEY=<FERNET_KEY>
CREDENTIALS_ENCRYPTION_KEY_VERSION=1

WORKFLOW_DATA_HOST_PATH=/var/workflowengine
PROJECT_CLONE_BASE_PATH=/var/workflowengine/repos
WORKTREE_BASE_PATH=/var/workflowengine/worktrees
RUN_DATA_BASE_PATH=/var/workflowengine/run_data

OAUTH_REDIRECT_URI=https://kyron.example.com/auth/callback
SESSION_SIGNING_KEY=<SESSION_KEY>
SESSION_PREVIOUS_SIGNING_KEY=
SESSION_MAX_AGE_SECONDS=28800
```

Important details:

- `APP_HOST` is only the hostname. Do not include `https://`, a port, or a path.
- `APP_BASE_URL` and `OAUTH_REDIRECT_URI` use HTTPS and the same hostname.
- `POSTGRES_PASSWORD` and the password inside `DATABASE_URL` must be identical.
  The hexadecimal generation command above avoids URL-encoding problems.
- All three in-container data paths should remain beneath
  `/var/workflowengine`, matching the one host bind mount.
- Do not change `PI_VERSION` casually. The repository pins a tested Pi protocol
  version.
- Tune `MAX_CONCURRENT_RUNS` to VM capacity. The one-worker invariant refers to
  the backend server process, not the number of workflow runs it may schedule.

Configure each enabled provider as follows.

For GitLab:

```dotenv
GITLAB_URL=https://gitlab.example.com
GITLAB_OAUTH_CLIENT_ID=<GITLAB_CLIENT_ID>
GITLAB_OAUTH_CLIENT_SECRET=<GITLAB_CLIENT_SECRET>
GITLAB_WEBHOOK_SECRET=<INDEPENDENT_GITLAB_WEBHOOK_TOKEN>
GITLAB_WEBHOOK_SIGNING_SECRET=
```

For public GitHub:

```dotenv
GITHUB_WEB_URL=https://github.com
GITHUB_API_URL=https://api.github.com
GITHUB_OAUTH_CLIENT_ID=<GITHUB_CLIENT_ID>
GITHUB_OAUTH_CLIENT_SECRET=<GITHUB_CLIENT_SECRET>
GITHUB_WEBHOOK_SECRET=<INDEPENDENT_GITHUB_WEBHOOK_SECRET>
```

For a provider that is not enabled, leave all of its OAuth values and webhook
secrets empty. Do not retain `replace-me`: the auth service treats non-empty
placeholder client values as an enabled provider.

```dotenv
GITLAB_OAUTH_CLIENT_ID=
GITLAB_OAUTH_CLIENT_SECRET=
GITLAB_WEBHOOK_SECRET=
GITLAB_WEBHOOK_SIGNING_SECRET=
```

or:

```dotenv
GITHUB_OAUTH_CLIENT_ID=
GITHUB_OAUTH_CLIENT_SECRET=
GITHUB_WEBHOOK_SECRET=
```

At least one complete OAuth client pair must remain configured.

## 7. Build and validate Caddy and Compose

Compose requires `.env`; configuration should fail rather than silently run
without it. Render and inspect the resolved configuration:

```bash
cd /opt/kyron
sudo docker compose -f deploy/docker-compose.yml config --quiet
sudo docker compose -f deploy/docker-compose.yml config --services
```

The service list should contain only `caddy`, `auth-service`, `postgres`, and
`backend`.

Build all application images:

```bash
sudo docker compose -f deploy/docker-compose.yml build --pull
```

The first build downloads base images and installs Python, Node, frontend, auth,
and Pi dependencies, so it can take several minutes.

Verify that the host kernel and container runtime expose the filesystem boundary
required by Prompt nodes:

```bash
sudo docker compose -f deploy/docker-compose.yml run --rm --no-deps \
  --entrypoint python backend \
  /app/backend/engine/pi/write_sandbox.py --check
```

The command must report Landlock ABI 3 or newer. Prompt execution fails closed
when this support is unavailable; Bash and Script nodes are unaffected.

Validate the packaged Caddy configuration before startup:

```bash
sudo docker compose -f deploy/docker-compose.yml run --rm --no-deps \
  --entrypoint caddy caddy \
  validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

The included Caddy configuration deliberately:

- allows unauthenticated access only to health and authenticated webhook
  endpoints;
- routes `/auth/*` to the OAuth service;
- strips any client-supplied trusted identity headers;
- gets verified identity headers from `forward_auth` before proxying `/api/*`;
  and
- serves the compiled React single-page application after authentication.

Do not expose the backend directly or place an alternate proxy route around this
boundary.

## 8. Start Kyron

Start the stack in the background:

```bash
cd /opt/kyron
sudo docker compose -f deploy/docker-compose.yml up -d
sudo docker compose -f deploy/docker-compose.yml ps
```

The backend entrypoint runs `alembic upgrade head` before starting Uvicorn with
exactly one worker. Caddy waits for the backend and auth-service health checks.
All services use `restart: unless-stopped`, and Docker is enabled at boot, so no
additional Kyron systemd unit is required.

Follow startup logs until all services are healthy:

```bash
sudo docker compose -f deploy/docker-compose.yml logs -f --tail=200
```

Press `Ctrl-C` to stop following logs; the containers continue running.

Check the unauthenticated health endpoint:

```bash
curl --fail --show-error https://kyron.example.com/api/health
```

A healthy response reports the database and single-worker mode:

```json
{"status":"ok","database":"ok","worker_mode":"in_process_single_worker"}
```

Then open `https://kyron.example.com` in a browser. Confirm that:

1. Caddy presents a trusted certificate for the expected hostname.
2. Kyron redirects to its provider chooser/login page.
3. Each configured OAuth provider returns to `/auth/callback` successfully.
4. The UI loads and `/api/auth/me` reflects the expected provider identity.

Verify host exposure:

```bash
sudo docker compose -f deploy/docker-compose.yml ps
sudo ss -lntp
```

Only Caddy should publish `0.0.0.0:80`/`:443` (and optionally their IPv6
equivalents). PostgreSQL port 5432, backend port 8000, and auth port 3001 must
not be published.

## 9. Configure repository access and webhooks

OAuth signs users into Kyron; it is not the token used to clone and modify a
repository. In the Kyron UI, register each project with an HTTPS clone URL and a
dedicated per-project token. Kyron encrypts that token before persistence and
uses temporary Git askpass credentials instead of authenticated Git URLs.

The token must be able to:

- read, fetch, and push repository contents and branches;
- create and update merge requests or pull requests;
- request reviewers and post comments; and
- consume intermediate approval as required by the provider integration.

Use the least-privileged dedicated bot/project identity that satisfies those
operations. Do not use a developer's personal long-lived token.

For GitLab, the intended credential is a project access token (which creates a
bot user) with the `api` and `write_repository` scopes. Start with the Developer
role and grant a higher project role only if the repository's branch or approval
policy requires it. The `api` scope provides project API access and
`write_repository` permits HTTPS pull/push; see GitLab's
[access-token scope reference](https://docs.gitlab.com/security/tokens/access_token_scopes/).
Approval reset specifically requires a project/group-token bot, as documented by
the [merge-request approvals API](https://docs.gitlab.com/api/merge_request_approvals/#reset-approvals-for-a-merge-request).

For GitHub, use a dedicated machine/bot account with repository write access and
a token limited to the selected repository. A fine-grained token should allow
repository **Contents: read and write** and **Pull requests: read and write**;
the Pull requests permission also permits Kyron to post pull-request comments.
Organization policy may also have to approve the token. GitHub's
[review-dismissal endpoint](https://docs.github.com/en/rest/pulls/reviews#dismiss-a-review-for-a-pull-request)
requires Pull requests write permission. For a protected branch, the bot user
must additionally be a repository administrator or be explicitly included among
the people/teams allowed to dismiss reviews. Confirm the effective role and
ruleset permissions in the target organization rather than assuming the token
scope alone grants them.

Protected target branches must require a fresh approving review. For GitHub,
the Kyron token identity also needs permission to dismiss pull-request reviews.
For GitLab, its project token identity must be able to reset merge-request
approvals. Validate this behavior in the real provider before relying on review
checkpoints.

### GitLab webhook

For every registered GitLab project, create a webhook with:

- URL: `https://kyron.example.com/api/webhook/gitlab`;
- secret token: the exact `GITLAB_WEBHOOK_SECRET` value;
- merge request events: enabled;
- comment/note events: enabled; and
- SSL verification: enabled.

If the GitLab instance emits Standard Webhooks signature headers and you set
`GITLAB_WEBHOOK_SIGNING_SECRET`, configure the same signing secret at both ends.
The normal GitLab secret-token check remains required.

### GitHub webhook

For every registered GitHub repository, create a webhook with:

- payload URL: `https://kyron.example.com/api/webhook/github`;
- content type: `application/json`;
- secret: the exact `GITHUB_WEBHOOK_SECRET` value;
- SSL verification: enabled; and
- individual events: pull requests, pull-request reviews, and issue comments.

Use the provider's delivery test and confirm a 2xx response. A 401 normally
indicates a mismatched webhook secret/signature; a 404 commonly indicates an
incorrect path or proxy route.

## 10. Configure model credentials

Prompt nodes invoke the Pi CLI inside the backend container. After signing in,
use Kyron's **Credentials** page to add the environment keys expected by the
selected model provider, for example `ANTHROPIC_API_KEY`. Credentials are scoped
to the Kyron/provider identity, encrypted at rest, injected only for process
execution, and write-only through the API.

Do not add model API keys to workflow JSON, `.env`, Docker images, Git remotes,
or shell command arguments. Run a small non-production workflow to verify model
access, Git push, change-request creation, reviewer assignment, and live logs.

## Private networks and internal TLS

The default `deploy/Caddyfile` uses a hostname site address, which enables Caddy
automatic HTTPS. The supported, simplest production option is a real domain
whose DNS and ports 80/443 satisfy public certificate issuance, even when access
to the application is otherwise limited by network policy.

For a hostname that is private and cannot receive a publicly trusted
certificate, explicitly use Caddy's internal CA. Add `tls internal` inside the
site block in `deploy/Caddyfile`:

```caddyfile
{$APP_HOST:workflow.example.internal} {
	tls internal
	encode zstd gzip

	# Keep all existing handlers unchanged.
}
```

Rebuild the Caddy image after changing the file:

```bash
cd /opt/kyron
sudo docker compose -f deploy/docker-compose.yml build caddy
sudo docker compose -f deploy/docker-compose.yml up -d caddy
```

Every browser and webhook sender must trust that private CA. Copy the root
certificate out of the running container and distribute it through the
organization's trusted certificate-management process:

```bash
sudo docker compose -f deploy/docker-compose.yml cp \
  caddy:/data/caddy/pki/authorities/local/root.crt \
  /tmp/kyron-caddy-root.crt
```

Do not bypass certificate verification. Public GitHub/GitLab SaaS cannot deliver
webhooks to a private-only address; use an approved ingress path or a publicly
reachable deployment in that case. A corporate certificate can alternatively
be mounted and referenced with Caddy's `tls <cert> <key>` directive, but the key
must be managed as a secret and never committed.

## Routine operations

Run Compose commands from `/opt/kyron` so it loads the intended `.env` and uses
the fixed Compose project name `kyron`.

### Status and logs

```bash
cd /opt/kyron
sudo docker compose -f deploy/docker-compose.yml ps
sudo docker compose -f deploy/docker-compose.yml logs --tail=200 backend
sudo docker compose -f deploy/docker-compose.yml logs --tail=200 caddy
```

### Stop and restart

```bash
# Stop containers but preserve all volumes and host data
sudo docker compose -f deploy/docker-compose.yml down

# Start them again
sudo docker compose -f deploy/docker-compose.yml up -d

# Restart one service without changing its configuration
sudo docker compose -f deploy/docker-compose.yml restart caddy
```

Never add `--volumes` to `docker compose down` during normal operations. That
would delete PostgreSQL and Caddy named volumes.

### Upgrade

Before an upgrade, read the release notes and make a database, data-directory,
and secret backup. Then update to a reviewed tag or commit:

```bash
cd /opt/kyron
sudo git fetch --tags --prune
sudo git checkout <REVIEWED_RELEASE_TAG_OR_COMMIT>
sudo docker compose -f deploy/docker-compose.yml config --quiet
sudo docker compose -f deploy/docker-compose.yml build --pull
sudo docker compose -f deploy/docker-compose.yml up -d --remove-orphans
sudo docker compose -f deploy/docker-compose.yml ps
curl --fail --show-error https://kyron.example.com/api/health
```

The backend applies database migrations automatically at startup. Do not start a
second backend while migrations or startup reconciliation are active. A source
rollback may not be compatible with a migrated database; restore the matching
pre-upgrade database backup when the release notes require it.

### Secret rotation

- Rotate `POSTGRES_PASSWORD` in PostgreSQL itself and update both `.env` values
  in one maintenance operation.
- To rotate session signing, move the current `SESSION_SIGNING_KEY` to
  `SESSION_PREVIOUS_SIGNING_KEY`, set a new signing key, restart auth-service,
  and clear the previous key after the maximum session age has passed.
- Credential-encryption key rotation requires application-level re-encryption;
  do not merely replace `CREDENTIALS_ENCRYPTION_KEY` or existing credentials
  become unreadable.
- Rotate provider client and webhook secrets in coordinated provider/application
  changes to avoid authentication gaps.

## Backups and restore readiness

A usable backup set contains all of the following from approximately the same
point in time:

1. a PostgreSQL dump;
2. `/var/workflowengine`, especially `run_data` and active worktrees;
3. the protected `.env`, stored through a separate encrypted secret channel; and
4. optionally Caddy's `caddy_data` volume for certificate continuity.

First confirm through the UI/API that no workflow process is running. Stopping
the backend prevents database and worktree changes while the maintenance backup
is made. Then create a PostgreSQL custom-format dump:

```bash
sudo install -d -m 0700 /var/backups/kyron
cd /opt/kyron
sudo docker compose -f deploy/docker-compose.yml stop backend
sudo sh -c 'docker compose -f deploy/docker-compose.yml exec -T postgres \
  pg_dump -U workflow_engine -d workflow_engine -Fc \
  > /var/backups/kyron/postgres.dump'
```

Archive the filesystem data while the backend remains stopped:

```bash
sudo tar -C /var/workflowengine -czf \
  /var/backups/kyron/workflowengine.tar.gz .
```

Then restart the backend and verify health:

```bash
cd /opt/kyron
sudo docker compose -f deploy/docker-compose.yml start backend
curl --fail --show-error https://kyron.example.com/api/health
```

If certificate continuity is part of the recovery objective, stop Caddy briefly
and archive its named data volume too:

```bash
cd /opt/kyron
sudo docker compose -f deploy/docker-compose.yml stop caddy
sudo docker compose -f deploy/docker-compose.yml run --rm --no-deps \
  --volume /var/backups/kyron:/backup \
  --entrypoint tar caddy -C /data -czf /backup/caddy-data.tar.gz .
sudo docker compose -f deploy/docker-compose.yml start caddy
```

Test backups by restoring them on an isolated VM. At a high level, stop Kyron,
restore the database and `/var/workflowengine`, restore the exact encryption and
session keys, ensure UID/GID `10001` owns the filesystem data, and then start
exactly one backend. Startup reconciliation will classify interrupted runs.

Do not treat Docker named volumes as a backup strategy. Store backup copies off
the VM with encryption, access controls, retention, and restore testing. See the
[operations runbook](docs/operations.md) for incident and retention behavior.

## Troubleshooting

### Caddy cannot obtain a certificate

Check:

- `APP_HOST` contains only the intended hostname;
- public DNS resolves to this VM, including any `AAAA` record;
- inbound TCP 80 and 443 reach the VM and are not occupied by another service;
- outbound HTTPS and DNS work; and
- the hostname is eligible for a public certificate.

Inspect Caddy logs:

```bash
sudo docker compose -f deploy/docker-compose.yml logs --tail=300 caddy
```

Do not repeatedly delete `caddy_data`; repeated issuance attempts can encounter
certificate-authority rate limits.

### Caddy reports address already in use

Find the host process already bound to 80/443:

```bash
sudo ss -lntp '( sport = :80 or sport = :443 )'
```

Stop or reconfigure the conflicting Nginx, Apache, host Caddy, or another
container. Kyron's Compose Caddy must own these ports in the documented setup.

### Backend is unhealthy or restarting

```bash
sudo docker compose -f deploy/docker-compose.yml ps
sudo docker compose -f deploy/docker-compose.yml logs --tail=300 backend postgres
sudo stat -c '%u:%g %a %n' /var/workflowengine
```

Common causes are a mismatched database password/URL, PostgreSQL not becoming
healthy, an invalid/missing Fernet key, migration failure, or data directories
not owned by UID/GID `10001`.

### OAuth callback fails

Compare all four locations character-for-character:

- the browser URL;
- `APP_BASE_URL`;
- `OAUTH_REDIRECT_URI`; and
- the provider OAuth application's callback URL.

Also confirm the provider client ID/secret pair belongs to the same application,
the VM can reach the provider over HTTPS, and the server clock is synchronized.
Cookies are secure in production and therefore require HTTPS.

### Webhook returns 401

For GitLab, confirm the provider secret token equals
`GITLAB_WEBHOOK_SECRET`. If signed webhook validation is enabled, confirm the
signing secret and clock too. For GitHub, confirm the webhook secret equals
`GITHUB_WEBHOOK_SECRET` and that the webhook sends `application/json` with the
normal GitHub signature headers.

### Workflow cannot write its clone/worktree

Restore the backend ownership without following paths outside the configured
root:

```bash
sudo chown -R 10001:10001 /var/workflowengine
sudo chmod 0750 /var/workflowengine
```

If a run is already active or failed during a wave, inspect it before deleting or
changing any worktree. Follow the recovery procedure in
[`docs/operations.md`](docs/operations.md); do not manually force state-machine
transitions.

### Disk usage grows

Inspect both application and Docker storage:

```bash
sudo du -xh -d 2 /var/workflowengine | sort -h
sudo docker system df
sudo journalctl --disk-usage
```

Do not run broad Docker prune or delete worktrees while Kyron is active. Kyron's
retention and reconciliation rules distinguish active, failed, and completed run
data. Configure Docker log rotation at the host level and monitor free space;
apply cleanup only after identifying data that is safe to remove.

## Production checklist

Before declaring the VM ready, confirm:

- [ ] The VM is patched, time-synchronized, backed up, and monitored.
- [ ] DNS resolves only to the intended ingress addresses.
- [ ] SSH is restricted; inbound 80/443 follow the intended public/private design.
- [ ] Docker Engine and the Compose v2 plugin come from a maintained repository.
- [ ] `/opt/kyron` is at a reviewed release tag or commit.
- [ ] `/var/workflowengine` is persistent and owned by UID/GID `10001`.
- [ ] `.env` is root-owned, mode `0600`, absent from Git, and backed up securely.
- [ ] No `replace-me` values remain; unused providers are truly blank.
- [ ] Caddy validates, TLS is trusted, and only ports 80/443 are published.
- [ ] `/api/health` reports `ok`, database `ok`, and single-worker mode.
- [ ] OAuth login works for every enabled provider.
- [ ] Dedicated project tokens can clone, push, create change requests, request
      reviews, post comments, and consume intermediate approval.
- [ ] GitLab/GitHub webhook delivery tests return 2xx.
- [ ] Protected branches require a fresh final approval.
- [ ] Model credentials are stored through Kyron and a smoke workflow succeeds.
- [ ] Database, filesystem, and secret backups have been restored in a test
      environment.
- [ ] Alerts cover VM reachability, health endpoint failure, disk pressure,
      container restarts, and backup failure.
