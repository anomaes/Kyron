---
title: Security model
description: Kyron's trust boundary, secret handling, provider identity, and minimum protections.
---

# Security model

Kyron is designed for a **trusted internal environment**. It provides strong reproducibility, identity, credential-lifetime, and path protections, but it intentionally does not sandbox workflow code.

## Trust assumptions

The deployment trusts:

- authenticated internal users;
- workflow authors whose changes pass repository review;
- repositories explicitly registered by operators; and
- the single VM and container host.

Bash, Script, and Prompt nodes can execute arbitrary code in the backend environment. A malicious workflow can read its environment, modify its worktree, consume compute, or attempt network access. Do not expose authoring or project registration to untrusted users.

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
- per-node containers or syscall/network sandboxing;
- distributed worker ownership;
- provider-account linking; and
- automatic secret-manager integration.

Treat any of these requirements as an architectural extension, not a configuration switch.
