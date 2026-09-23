---
title: Quick start
description: Install, configure, and verify Kyron with Docker Compose.
---

# Quick start

This guide takes a fresh machine from an empty directory to a successful,
non-AI workflow run. It uses Kyron's supported Docker Compose topology: Caddy,
the OAuth service, exactly one FastAPI backend worker, PostgreSQL, and the React
operator UI.

For an internet-facing or long-lived installation, also complete the
[production checklist](/deployment/#production-checklist) before inviting users.

## Prerequisites

- Docker Engine and Docker Compose v2.24 or newer
- Git and OpenSSL
- a stable hostname for Kyron
- a GitLab or GitHub OAuth application
- a repository access token for a trusted test repository

Model-provider credentials are not required for the initial smoke test. Add
them only when you are ready to run Prompt nodes.

## 1. Clone Kyron

```bash
git clone https://github.com/anomaes/Kyron.git
cd Kyron
```

For production, check out a reviewed release tag or commit rather than an
arbitrary moving branch.

## 2. Choose the HTTPS origin

Kyron, its OAuth callback, and provider webhooks use one HTTPS origin.

**Publicly resolvable hostname:** point DNS to the host and allow Caddy to reach
the public certificate authority on ports 80 and 443. This is the simplest
option and is required when GitHub.com or GitLab.com must deliver webhooks
directly to Kyron.

**Private hostname:** make the hostname resolve to the host from every browser
and webhook sender. Add `tls internal` inside the existing site block in
`deploy/Caddyfile`, then distribute Caddy's root certificate through your
trusted certificate-management process. Public GitHub or GitLab SaaS cannot
deliver webhooks to a private-only address; use an approved ingress path or a
publicly reachable deployment.

Add only the marked line and keep all existing handlers unchanged:

```diff
{$APP_HOST:workflow.example.internal} {
+    tls internal
     encode zstd gzip
```

The complete certificate extraction and trust procedure is in
[Private networks and internal TLS](https://github.com/anomaes/Kyron/blob/main/SETUP.md#private-networks-and-internal-tls).
Do not bypass TLS verification.

## 3. Configure a code-host provider

Create at least one OAuth application before starting Kyron. For an origin such
as `https://kyron.example.com`, configure the callback URL on either provider:

```text
https://kyron.example.com/auth/callback
```

Set the GitHub OAuth App homepage to `https://kyron.example.com`. GitLab needs
the `read_user` scope; Kyron requests `read:user user:email` from GitHub. Record
the client ID and secret, then follow the exact
[GitLab or GitHub provider instructions](/deployment/providers) for repository
token permissions and webhook events.

## 4. Create the environment file

```bash
cp .env.example .env
openssl rand -base64 32 | tr '/+' '_-'
openssl rand -base64 48
```

Put the first generated value in `CREDENTIALS_ENCRYPTION_KEY` and the second in
`SESSION_SIGNING_KEY`. Generate each value independently and store production
keys in a backup channel separate from the database.

Set these groups in `.env`:

| Group | Required values |
| --- | --- |
| Public URL | `APP_HOST`, `OAUTH_REDIRECT_URI=https://<APP_HOST>/auth/callback` |
| Database | `POSTGRES_PASSWORD` and the same password inside `DATABASE_URL` |
| Secrets | `CREDENTIALS_ENCRYPTION_KEY`, `SESSION_SIGNING_KEY` |
| GitLab | `GITLAB_URL`, OAuth ID and secret—or leave both OAuth values empty |
| GitHub | web/API URLs, OAuth ID and secret—or leave both OAuth values empty |
| Storage | `WORKFLOW_DATA_HOST_PATH` and the three backend container roots |

At least one provider must have both OAuth values configured. A partially
configured provider is not offered on the sign-in page. Review defaults, valid
ranges, and optional settings in the [configuration reference](/deployment/configuration).

Create the host storage root and give the backend container's UID/GID ownership:

```bash
sudo install -d -m 0750 -o 10001 -g 10001 /var/workflowengine
```

If `WORKFLOW_DATA_HOST_PATH` names another absolute path, create and own that
path instead. On Docker Desktop, choose a host directory shared with Docker and
ensure container UID/GID `10001` can write it.

::: danger Never commit `.env`
It contains the keys that protect browser sessions and encrypted credentials.
Kyron intentionally refuses to start in production without required values.
:::

## 5. Validate and start Kyron

```bash
docker compose -f deploy/docker-compose.yml --env-file .env config --quiet
docker compose -f deploy/docker-compose.yml up --build -d
docker compose -f deploy/docker-compose.yml ps
```

Only Caddy should publish host ports. The backend, auth service, and PostgreSQL
must remain internal. If startup fails, inspect the service logs:

```bash
docker compose -f deploy/docker-compose.yml logs --tail=200 backend auth-service caddy postgres
```

For `tls internal`, extract Caddy's root certificate after startup and install
it through the operating system or organization's trusted-certificate process:

```bash
docker compose -f deploy/docker-compose.yml cp \
  caddy:/data/caddy/pki/authorities/local/root.crt \
  ./kyron-caddy-root.crt
```

Open `https://<APP_HOST>`, choose the configured provider, and sign in. The
first user created in a new database becomes the global system administrator;
that user can register projects, manage users, and configure AI providers.

## 6. Register a test repository

In **Projects**, choose **Add project** and provide:

- `gitlab` or `github` as the provider;
- the GitLab project ID/path or GitHub `owner/repository` path;
- an HTTPS clone URL without embedded credentials;
- a write-only project token with the permissions in the
  [provider guide](/deployment/providers); and
- the generated project webhook secret.

Copy the generated secret before saving and create the repository webhook:

| Provider | Endpoint | Events |
| --- | --- | --- |
| GitLab | `https://<APP_HOST>/api/webhook/gitlab` | Merge-request and note events |
| GitHub | `https://<APP_HOST>/api/webhook/github` | Pull requests, pull-request reviews, and issue comments |

Back in Kyron, use **Validate** and then **Fetch** on the project card. Project
validation, clone, and catalog loading should all succeed before continuing.

## 7. Run a non-AI smoke test

Add `.workflowEngine/smoke_test.yaml` to the repository's default branch and
merge it through the repository's normal review process:

```yaml
id: smoke_test
name: Smoke test
description: Verify the pinned repository and process runner without AI access.
version: 2
created_by: platform@example.com
tags:
  - smoke-test
inputs: {}
outputs: {}
variables: {}
nodes:
  - id: inspect
    type: bash
    label: Inspect the pinned checkout
    join: and
    config:
      command: git rev-parse HEAD && printf '%s\n' 'Kyron smoke test passed'
      allow_failure: false
      shell: /bin/bash
    position:
      x: 100
      y: 100
edges: []
settings:
  delivery_mode: report_only
  credential_access:
    mode: none
    keys: []
```

Refresh the workflow catalog, choose **Run**, and select the default branch. On
Run Detail, verify the resolved base SHA, successful wave and attempt, durable
log, and zero AI usage. `report_only` deliberately avoids pushing a run branch
or opening a change request.

## 8. Enable Prompt workflows

When the smoke test works:

1. open **Credentials** and add the model credential required by the selected
   Pi provider, such as `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`;
2. optionally configure custom endpoints under **Administration → AI providers**;
3. select project-wide Pi defaults on the project card; and
4. add and run [your first Prompt workflow](/getting-started/first-workflow).

Prompt attempts receive credentials according to the workflow's
`settings.credential_access` policy. Keep credentials out of workflow YAML.

## 9. Optional: install the VS Code extension

Use the [Visual Studio Code guide](/guides/vscode) to build the current VSIX,
connect it through device authorization, and browse the same folder-aware
workflow catalog from your repository workspace.

## Stop without deleting data

```bash
docker compose -f deploy/docker-compose.yml down
```

This preserves named volumes and the configured host data path. Do not add
`-v` unless you intentionally want to delete the PostgreSQL and Caddy volumes.

## Next steps

- [Browse all task-oriented guides](/guides/)
- [Review roles and approval policies](/guides/access-and-governance)
- [Prepare a production installation](/deployment/)
- [Learn the execution model](/getting-started/concepts)
