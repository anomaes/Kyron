# API guide

The API is rooted at `/api`. The field-level OpenAPI document is available at
`/api/docs` on a running instance. UUIDs are strings, timestamps are UTC ISO
8601 values, and paginated endpoints use `page` and `page_size` with a maximum
page size of 200.

## Authentication boundary

Caddy removes every incoming `X-Token-*` identity header, verifies the signed
OAuth session through the auth service, and copies trusted identity headers to
the backend. Do not publish the backend port or call it through an untrusted
proxy. `/api/health`, `/api/webhook/gitlab`, and `/api/webhook/github` bypass
browser OAuth; each webhook authenticates its raw body with provider-specific
headers and secrets.

## Route inventory

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Worker and database health |
| GET | `/api/metrics` | Authenticated Prometheus-format storage metrics |
| GET | `/api/auth/me` | Current user and active provider identity |
| GET/POST | `/api/projects` | List or register repositories |
| GET/DELETE | `/api/projects/{project_id}` | Inspect or remove a project |
| PUT | `/api/projects/{project_id}/token` | Replace the write-only project token |
| POST | `/api/projects/{project_id}/fetch` | Fetch/prune the local clone |
| POST | `/api/projects/{project_id}/validate` | Validate provider and repository access |
| PUT | `/api/projects/{project_id}/pi` | Replace project-wide Pi provider, model, and skill defaults |
| GET/POST | `/api/credentials` | List metadata or create a write-only credential |
| PUT/DELETE | `/api/credentials/{credential_id}` | Replace or remove a credential |
| GET | `/api/projects/{project_id}/workflows` | List tagged definitions at the default-branch SHA for catalog search/grouping and workflow selection |
| GET/PUT/DELETE | `/api/projects/{project_id}/workflows/{workflow_id}` | Read or store a project-local definition change |
| POST | `/api/projects/{project_id}/workflows/validate` | Validate one definition and related drafts |
| GET/POST | `/api/projects/{project_id}/workflows/templates` | List or locally store project node templates |
| DELETE | `/api/projects/{project_id}/workflows/templates/{template_id}` | Locally stage a template deletion |
| GET | `/api/projects/{project_id}/workflows/changes` | Read outgoing and in-review definition counts |
| POST | `/api/projects/{project_id}/workflows/changes/review` | Batch outgoing definitions into one code-host review |
| GET | `/api/projects/{project_id}/workflows/{workflow_id}/references` | Direct and reverse references |
| POST | `/api/projects/{project_id}/workflows/{workflow_id}/runs` | Snapshot and queue a run |
| GET | `/api/runs` | Filtered, paginated run list |
| GET | `/api/runs/{run_id}` | Durable run state |
| GET | `/api/runs/{run_id}/graph` | Snapshot, invocations, waves, nodes, attempts, edges, feedback |
| GET | `/api/runs/{run_id}/logs` | Replay engine logs after a sequence ID |
| GET | `/api/runs/{run_id}/nodes/{node_execution_id}` | Node and attempt history |
| GET | `/api/runs/{run_id}/nodes/{node_execution_id}/output` | Safe stdout/stderr/Pi event retrieval |
| POST | `/api/runs/{run_id}/cancel` | Cancel processes and the registered run task |
| POST | `/api/runs/{run_id}/resume` | Restore the failed wave as a new attempt |
| POST | `/api/runs/{run_id}/approve` | Continue the current human checkpoint |
| POST | `/api/runs/{run_id}/feedback` | Submit revision feedback and continue |
| POST | `/api/webhook/gitlab` | Authenticated, idempotent GitLab events |
| POST | `/api/webhook/github` | Authenticated, idempotent GitHub events |
| WS | `/api/ws/runs/{run_id}/logs?after_id=N` | Replayed then live run events |

`GET /api/runs` accepts `project_id`, `root_workflow_id`, `status`,
`triggered_by`, `created_after`, and `created_before`. Output retrieval accepts
`attempt`, `stream=stdout|stderr|pi_events`, and `tail_lines`.

Workflow definitions include a `tags` array. Tags are lowercase catalog metadata
stored in the workflow JSON; they do not alter scheduling. The workflow list response
contains complete definitions so the builder can populate searchable child-workflow
selectors and generate input/output mapping controls from each child's declared
schema.

The run-graph response includes every invocation and node execution, not only the
root invocation. The frontend uses `parent_invocation_id`,
`parent_node_execution_id`, `loop_iteration`, and `invocation_path` to expand child
workflow instances and order review-loop rounds.

## Common workflows

Validate a draft before proposing its change request:

```json
POST /api/projects/<project-id>/workflows/validate
{
  "workflow": { "id": "full_review", "version": 1, "nodes": [], "edges": [] },
  "proposed_related_workflows": {}
}
```

Triggering resolves the requested ref to an exact SHA before the run row is
committed. Set `use_local_definitions` only for a local test; Kyron then creates an
exact local definition commit and disables push/change-request creation for that run:

```json
POST /api/projects/<project-id>/workflows/full_review/runs
{
  "base_ref": "main",
  "use_local_definitions": false,
  "inputs": { "TASK": "Add validation to the import endpoint" }
}
```

Reconnect log clients with the last received engine-log sequence. The server
replays durable events with larger IDs and then switches to live delivery.
Process output events are live-only; complete attempt files remain available
through the output endpoint until retention cleanup.

## State conflicts and safety

Invalid input returns HTTP 422, missing resources return 404, authorization
failures return 401/403, and stale or invalid state transitions return 409.
Workflow saves require `expected_base_commit_sha`; a changed default branch is a
409 and the editor must reload. Workflow deletion is also a 409 while reverse
references exist. The output endpoint derives paths only from durable node
metadata and verifies they remain under the run-data root.
