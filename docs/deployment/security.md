---
title: Security model
description: Kyron's trust boundary, secret handling, provider identity, and minimum protections.
---

# Security model

Kyron is designed for a **trusted internal environment**. It provides strong reproducibility, identity, credential-lifetime, and path protections. Prompt nodes also receive a filesystem write boundary; this is not a hostile multi-tenant or general-purpose process sandbox.

## Trust assumptions

The deployment trusts:

- authenticated internal users;
- workflow authors whose changes pass repository review;
- repositories explicitly registered by operators; and
- the single VM and container host.

Bash and Script nodes can execute arbitrary code in the backend environment. Prompt nodes can execute Pi tools and child processes, read the container filesystem, read their environment, consume compute, and access the network. Do not expose authoring or project registration to untrusted users.

## Prompt-node filesystem boundary

Kyron launches each Pi process in a Bubblewrap user, mount, and PID namespace. The
container root is recursively bind-mounted read-only, then the resolved run worktree
and a per-attempt scratch directory are mounted read-write. Pi state, caches, and
temporary files point into that scratch directory, which is removed after execution.
An empty read-only `/proc`, a private PID namespace, dropped capabilities, an isolated
ephemeral `/dev`, and a new session keep Pi child processes inside the same filesystem
view. The built-in Pi `write` and `edit` tools also reject paths outside the worktree to
provide an immediate, readable error.

`/proc` is intentionally empty rather than a nested procfs mount. This prevents access to
the parent backend process through paths such as `/proc/<pid>/root` and works with the
masked procfs used by standard container runtimes. Commands that require procfs process or
system information are therefore unavailable inside Prompt nodes.

This boundary covers direct writes, truncation, deletion, renaming, links, metadata
changes, and writes attempted through Pi's Bash tool or its descendants. Reads,
environment variables, network access, and resource consumption are deliberately not
restricted. Bash and Script workflow nodes do not use this boundary.

Bubblewrap is part of the backend image. The container runtime must permit unprivileged
user, mount, and PID namespaces; no Landlock support is required. Prompt execution
fails closed if the namespace cannot be established. Operators must run
`python -m backend.engine.pi.sandbox --check` in the deployed backend container because
a successful user-namespace probe alone does not verify the required mount operations.
The included Compose stack uses an unconfined backend seccomp profile so Bubblewrap can
perform that setup; the process still runs as UID/GID `10001` with all Linux capabilities
dropped.

Kubernetes deployments may instead use a custom seccomp allow-list when the cluster can
distribute one to every eligible node.

## Network boundary

Caddy is the only public service. It:

1. removes incoming identity headers;
2. verifies the signed OAuth session through the auth service;
3. copies only normalized trusted identity headers to the backend; and
4. proxies authenticated API and WebSocket traffic.

Never publish backend, auth-service, or PostgreSQL ports. A client that can reach the backend directly may forge trusted headers.

The health and webhook endpoints bypass browser OAuth for their intended protocols. Each webhook authenticates its raw body with provider-specific secrets.

## Provider affinity

A user may control only projects and runs on the provider of the active session. Identity is keyed by provider and immutable provider user ID, not email. Run checkpoints are bound to the triggering identity snapshot.

Project lists and run history are visible to authenticated internal users, but cross-provider mutations return HTTP 403.

## Credential handling

Stored credentials use Fernet encryption. APIs expose metadata and write-only replacement operations, never plaintext values.

At execution time, plaintext exists only in process memory and the subprocess environment. Values are registered with the in-memory redactor before output streaming. Kyron never permits secrets in public `${...}` context or workflow snapshots.

This protects against accidental persistence and logging, not malicious code. Trusted workflows remain mandatory.

## Git authentication

Project tokens are never written into clone URLs stored in the database. Provider authentication is assembled for the individual Git operation and must not appear in command logs, exception text, or durable configuration.

Git and Pi processes are invoked with argument arrays. Filesystem paths are derived beneath configured roots and validated before use.

## Exact revision and workflow integrity

Kyron fetches and resolves the requested base ref, then reads every workflow definition from that exact commit. The secret-free bundle is stored with the run. This prevents moving branches or edited children from changing in-flight instructions.

Workflow saves use optimistic concurrency and provider change requests. A stale editor cannot overwrite a newer default-branch definition silently.

## Approval integrity

Only provider identities in the opened gate's immutable policy snapshot may control a
checkpoint, and their project membership must grant `gate.respond`. Intermediate approvals
are consumed after the complete quorum is satisfied, ensuring they cannot satisfy final
protected-branch policy. Configure branches to require fresh approval and grant the Kyron
identity the authority to reset or dismiss reviews.

## Durable audit trail

Kyron persists runs, invocations, waves, node executions, attempts, edge evaluations, feedback events, provider deliveries, and engine logs. New attempts do not overwrite failed ones.

Output retention is separate from database metadata. Design a retention policy that balances incident evidence, repository sensitivity, and disk capacity.

## Minimum hardening

- Keep the service on a controlled internal hostname or access network.
- Expose only 80/443 through Caddy.
- Use least-privilege project tokens and a dedicated Kyron provider identity.
- Require code review for `.workflowEngine/` changes.
- Restrict who may register projects and create credentials.
- Protect `.env` and back up keys separately.
- Monitor disk, container health, authentication failures, and webhook rejection rates.
- Patch the VM, container images, Pi version, and Node/Python dependencies through reviewed releases.
- Run exactly one backend worker.
- Rehearse backup restore and interrupted-run recovery.

## Out of scope in the current release

- hostile multi-tenancy;
- per-node containers, network isolation, syscall filtering, or resource quotas;
- distributed worker ownership;
- provider-account linking; and
- automatic secret-manager integration.

Treat any of these requirements as an architectural extension, not a configuration switch.
