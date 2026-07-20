---
title: Developer guide
description: Set up, verify, and safely change the Kyron codebase.
---

# Developer guide

Kyron has a Python/FastAPI backend, React/TypeScript operator UI, TypeScript OAuth service, PostgreSQL schema managed by Alembic, and a Docker Compose deployment.

Read the repository `AGENTS.md` and the [normative specification](https://github.com/anomaes/Kyron/blob/main/workflow_orchestration_engine_spec.md) before changing execution behavior.

## Backend setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e '.[dev]'
```

Run backend checks:

```bash
ruff check backend
mypy backend
pytest
```

## Frontend and auth service

```bash
npm --prefix frontend ci
npm --prefix frontend run check
npm --prefix frontend run build

npm --prefix auth-service ci
npm --prefix auth-service run check
npm --prefix auth-service run build
```

## Documentation site

```bash
npm --prefix docs ci
npm --prefix docs run dev
```

The local server provides search, routing, and live reload. Build before submitting documentation changes:

```bash
npm --prefix docs run build
```

Page source lives under `docs/`. Navigation and theme configuration live under `docs/.vitepress/`. Keep task-oriented guides approachable and link to exact reference contracts rather than duplicating every schema field.

The documentation workflow publishes through GitHub Pages and can bootstrap a
new Pages site automatically. For the first deployment, add a repository Actions
secret named `PAGES_ENABLEMENT_TOKEN` containing a fine-grained token limited to
this repository with Pages write permission. After Pages has been enabled, remove
the bootstrap secret; subsequent deployments use the standard workflow
`GITHUB_TOKEN`. Keep its permissions at `contents: read`, `pages: write`, and
`id-token: write`. GitHub does not allow the built-in token to perform initial
Pages enablement.

## Full local verification

```bash
./scripts/verify.sh
```

The script runs backend lint, typing, and tests; installed Node package checks; and Compose configuration validation. A release also audits Node dependencies and builds all container images.

## Non-negotiable invariants

- Never persist or log decrypted credentials or authenticated Git URLs.
- Resolve and snapshot every workflow from the run's exact base commit.
- Keep ordinary graphs acyclic; repetition belongs in `review_loop`.
- Reset and retry a failed wave as a whole with fresh attempt rows.
- Only identities snapshotted as eligible by the gate policy may control feedback checkpoints.
- Consume intermediate provider approval before execution continues.
- Run exactly one backend worker in production.

State-machine changes require tests.

## Safe implementation patterns

- Pass argument arrays to Git and Pi processes.
- Validate derived filesystem paths against configured roots.
- Preserve unrelated worktree changes during contributor work.
- Keep provider-specific payloads inside integration adapters.
- Make database state transitions explicit and transactional.
- Preserve immutable history; append attempts and events rather than rewriting evidence.
- Update task-oriented docs and exact references together when a public contract changes.

## Where to make changes

| Area | Main paths |
| --- | --- |
| API routes | `backend/api/` |
| Domain services | `backend/services/` |
| Scheduling and execution | `backend/engine/` |
| Workflow schema | `backend/schemas/workflow.py` |
| Durable model/repositories | `backend/db/` |
| GitLab/GitHub adapters | `backend/integrations/` |
| Operator UI | `frontend/src/` |
| OAuth boundary | `auth-service/src/` |
| Deployment | `deploy/` |
| Product and architecture docs | `docs/` and the root normative specification |

## Architecture records

Use the [decision log](/decisions) for accepted architectural deviations and the [implementation plan](/IMPLEMENTATION_PLAN) for milestone status. Record environment-specific acceptance evidence in [acceptance verification](/acceptance) without embedding secrets or provider tokens.

## Pull request checklist

- [ ] Behavior matches the normative specification or an explicit decision record.
- [ ] State-machine behavior has focused unit/integration tests.
- [ ] Provider-neutral and provider-specific boundaries remain clear.
- [ ] Logs and errors were checked for secret leakage.
- [ ] Filesystem and Git inputs are validated and passed safely.
- [ ] API/UI/docs changed together where needed.
- [ ] Local verification succeeds.
