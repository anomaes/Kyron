---
title: Security model
description: Kyron's trust boundary, secret handling, provider identity, and minimum protections.
---

# Security model

Kyron is designed for a **trusted internal environment**. It provides strong reproducibility, identity, credential-lifetime, and path protections, including a write boundary for Pi Prompt processes. It does not isolate hostile workflow code.

## Trust assumptions

The deployment trusts:

- authenticated internal users;
- workflow authors whose changes pass repository review;
- repositories explicitly registered by operators; and
- the single VM and container host.

Bash and Script nodes can execute arbitrary code in the backend environment. Prompt nodes can execute arbitrary code with access to readable backend files, their environment and injected credentials, compute, and the network. Do not expose authoring or project registration to untrusted users.

## Prompt write boundary

Kyron launches every Pi Prompt process under a Linux Landlock ruleset. Pi and all of
its child processes can write or truncate file contents and create, delete, or rename
directory entries only beneath the run's current Git worktree and an ephemeral scratch
directory used for Pi state, caches, and temporary files. The scratch directory is
removed after the process ends. Kyron's Pi extension also rejects out-of-worktree
`write` and `edit` tool calls with a direct error.

The boundary covers file content writes, truncation, creation, deletion, renaming,
hard-linking, and symlink escapes. Landlock does not mediate every metadata-only
operation, such as changing file permissions or timestamps. The boundary also does not
restrict reads, environment variables, network access, or resource consumption, and it
does not apply to Bash or Script nodes. All credentials belonging to the triggering
user are still injected into the Prompt process. Treat the boundary as protection
against unintended content and namespace edits, not as permission to run untrusted
prompts or repositories.

Prompt execution fails closed before Pi starts unless the backend host and container
runtime expose Landlock ABI 3 or newer. Kyron never silently falls back to an
unconfined Prompt process.

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
- per-node containers or general syscall/network isolation;
- distributed worker ownership;
- provider-account linking; and
- automatic secret-manager integration.

Treat any of these requirements as an architectural extension, not a configuration switch.
