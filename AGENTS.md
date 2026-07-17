# Kyron contributor guide

Kyron is a trusted-internal workflow orchestration engine. The normative product
behavior is in `workflow_orchestration_engine_spec.md`; architectural decisions
and delivery status are recorded under `docs/`.

## Build and test

- Install backend dependencies: `python3 -m pip install -e '.[dev]'`
- Run backend tests: `pytest`
- Lint backend: `ruff check backend`
- Type-check backend: `mypy backend`
- Install frontend dependencies: `npm --prefix frontend ci`
- Check frontend: `npm --prefix frontend run check`
- Install auth dependencies: `npm --prefix auth-service ci`
- Check auth service: `npm --prefix auth-service run check`
- Run all local checks: `./scripts/verify.sh`
- Start the development stack: `docker compose -f deploy/docker-compose.yml up --build`

## Non-negotiable invariants

- Never persist or log decrypted credentials or authenticated Git URLs.
- Resolve and snapshot workflows from the run's exact base commit.
- Ordinary workflow graphs remain acyclic; repetition belongs to `review_loop`.
- A failed wave is reset as a whole and retried with new attempt rows.
- Only the triggering user on the run's code-host provider may control feedback checkpoints.
- Intermediate provider approval must be consumed before execution continues.
- Production runs exactly one backend worker.

Use argument arrays for Git and Pi processes, validate all filesystem paths
against configured roots, preserve unrelated worktree changes, and add tests for
every state-machine change.
