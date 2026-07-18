---
title: Quick start
description: Configure and run Kyron with Docker Compose.
---

# Quick start

This guide brings up Kyron with the included Docker Compose stack. For an internet-facing or long-lived installation, continue with the [production deployment guide](/deployment/) before inviting users.

## Prerequisites

- Docker Engine and Docker Compose v2.24 or newer
- Git
- A GitLab or GitHub OAuth application
- A repository access token for a trusted test repository
- Credentials for the model provider used by Pi prompt nodes, if you plan to use them

The stack contains Caddy, the OAuth service, one FastAPI backend worker, PostgreSQL, and the React operator UI.

## 1. Create the environment file

From the Kyron repository root:

```bash
cp .env.example .env
```

Generate independent values for the credential encryption key and session key:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set at least these groups in `.env`:

| Group | Required values |
| --- | --- |
| Public URL | `APP_HOST`, `APP_BASE_URL`, `OAUTH_REDIRECT_URI` |
| Database | `POSTGRES_PASSWORD` and the matching password in `DATABASE_URL` |
| Secrets | `CREDENTIALS_ENCRYPTION_KEY`, `SESSION_SIGNING_KEY` |
| GitLab | OAuth ID/secret, URL, webhook secret—or leave the provider disabled |
| GitHub | OAuth ID/secret, web/API URLs, webhook secret—or leave the provider disabled |
| Storage | `WORKFLOW_DATA_HOST_PATH` and the three backend storage roots |

At least one provider must have both OAuth values configured. A partially configured provider is not offered on the sign-in page.

::: danger Never commit `.env`
It contains the keys that protect browser sessions and encrypted credentials. Kyron intentionally refuses to start in production without its required values.
:::

## 2. Validate the configuration

```bash
docker compose -f deploy/docker-compose.yml --env-file .env config --quiet
```

Fix configuration errors before starting the stack. In particular, `POSTGRES_PASSWORD` must match the password embedded in `DATABASE_URL`.

## 3. Start Kyron

```bash
docker compose -f deploy/docker-compose.yml up --build -d
docker compose -f deploy/docker-compose.yml ps
```

Only Caddy should publish host ports. The backend, auth service, and PostgreSQL must remain internal.

Open `APP_BASE_URL`, choose a configured provider, and complete sign-in.

## 4. Register a repository

In **Projects**, choose **Add project** and provide:

- the code-host provider;
- the GitLab project ID/path or GitHub `owner/repository` path;
- an HTTPS clone URL without embedded credentials; and
- a project token with repository contents and change-request write access.

Kyron validates the provider metadata, stores canonical project identity, encrypts the token, and prepares the local clone.

## 5. Add and run a workflow

Workflow files live in the registered repository at:

<span class="doc-path">.workflowEngine/&lt;workflow_id&gt;.json</span>

Commit the [first workflow](/getting-started/first-workflow) to the repository's default branch. Refresh the workflow catalog, choose **Run**, select a base ref, and supply the required inputs.

The run detail should show:

1. the resolved base SHA;
2. a root invocation;
3. one or more execution waves;
4. live and durable output; and
5. the run branch and change request when the workflow reaches delivery or review.

## 6. Stop without deleting data

```bash
docker compose -f deploy/docker-compose.yml down
```

This stops the containers and preserves named volumes and the configured host data path. Do not add `-v` unless you intentionally want to delete the PostgreSQL and Caddy volumes.

## Next steps

- [Learn the execution model](/getting-started/concepts)
- [Configure GitLab or GitHub webhooks](/deployment/providers)
- [Create model credentials](/guides/projects-and-credentials)
- [Review the production checklist](/deployment/#production-checklist)
