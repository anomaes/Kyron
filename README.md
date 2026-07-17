# Kyron Workflow Engine

Kyron is a self-hosted orchestration platform for trusted internal teams. It
runs AI-assisted coding workflows against exact Git revisions, checkpoints each
execution wave in Git, integrates review through GitLab merge requests, and can
resume failed or interrupted work deterministically.

> **Security boundary:** Kyron executes Bash, Python, and Pi nodes directly in
> the backend environment. It is suitable only for trusted workflow authors and
> trusted repositories behind the configured OAuth proxy. It is not a sandbox.

## Repository layout

- `backend/` — FastAPI API, durable engine, Git/GitLab integrations, migrations,
  and tests.
- `frontend/` — React/Vite application and React Flow workflow builder.
- `auth-service/` — GitLab OAuth session service used by Caddy `forward_auth`.
- `deploy/` — single-VM Docker Compose and Caddy configuration.
- `docs/` — architecture, milestone plan, operations, and decision records.
- `workflow_orchestration_engine_spec.md` — normative implementation handoff.

## Quick start

1. Copy `.env.example` to `.env` and replace every placeholder.
2. Generate a Fernet key with
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
3. Run `docker compose -f deploy/docker-compose.yml up --build`.
4. Open the `APP_BASE_URL` configured in `.env`.

Compose intentionally refuses to start without the root `.env`. At minimum,
`POSTGRES_PASSWORD` must match the password embedded in `DATABASE_URL`, the
Fernet and session-signing keys must be valid, and the OAuth values must come
from a GitLab OAuth application. Use `docker compose -f deploy/docker-compose.yml
config` to validate that the file is being loaded before starting containers.

For local backend development, install Python 3.11 or newer and run:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
uvicorn backend.main:app --reload
```

Production must use one Uvicorn worker and must expose only Caddy. See
`docs/operations.md` for deployment, backup, recovery, and retention procedures.

## Workflow model

Workflow definitions live at `.workflowEngine/<workflow_id>.json` in each
registered repository. A workflow is a DAG containing `bash`, `script`,
`prompt`, `human_feedback`, `subworkflow`, and `review_loop` nodes. At trigger
time Kyron pins the base SHA and snapshots the root definition plus every
transitive child definition from that same SHA.

Process nodes that are ready together execute as a wave. The worktree HEAD at
wave start is persisted; a failed wave is fully reset and all its nodes receive
new attempts on resume. Composite and pause-capable nodes execute as isolated
control boundaries.

## Documentation

- [Implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [Architecture](docs/architecture.md)
- [Operations runbook](docs/operations.md)
- [Decision log](docs/decisions.md)
- [API reference](docs/api.md)
