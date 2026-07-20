---
title: Projects and credentials
description: Register repositories and make secrets available to workflow processes.
---

# Projects and credentials

Projects connect Kyron to repositories. Credentials provide secret environment values to process nodes. They have different scopes and should not be confused.

## Register a project

Open **Projects** and choose **Add project**. Supply:

| Field | Meaning |
| --- | --- |
| Provider | `gitlab` or `github`; must match your active session for mutations |
| Provider project | GitLab project ID/path or GitHub `owner/repository` |
| Clone URL | HTTPS repository URL without username, token, or embedded credentials |
| Access token | Write-only token used for Git and provider API operations |
| Pi defaults | Optional provider, model, and repository-relative skill used by prompt nodes |

Kyron asks the provider for canonical repository metadata. It does not trust a user-provided display name or project identity when the provider can supply one.

The token needs enough access to fetch and push repository contents, create and update a change request, request reviewers, post comments, and consume intermediate approval. Exact provider guidance is in [GitLab and GitHub setup](/deployment/providers).

::: danger Authenticated URLs are forbidden
Never paste `https://user:token@host/repository.git`. Kyron constructs authenticated Git access in memory for each operation and must never persist or log the result.
:::

## Refresh or validate a project

Use **Validate** after changing provider permissions. Validation checks repository identity and the operations Kyron needs. **Fetch** updates and prunes the local clone; it does not alter an existing run's pinned commit or workflow snapshot.

Replacing a project token is a write-only operation. The old plaintext is not returned by the API or UI.

## Configure Pi defaults

Use **Pi defaults** on a project card to select the provider, model, and skill shared
by its prompt nodes. Workflow defaults override project values, and prompt-node values
override workflow values. Resolution happens per field, so a workflow can select a
model while continuing to use the project's skill.

Skill paths are relative to the repository root, such as
`.agents/skills/implementation/SKILL.md`. Kyron resolves the path inside the pinned run
worktree, loads it explicitly with Pi, and invokes the name declared by the skill's
frontmatter. The skill therefore follows the same reviewed Git history as the code and
workflow definitions it operates on.

## Remove a project

Choose **Remove** on a project card and confirm the action. Kyron removes its local
repository clone and any project-local workflow or node-template changes. The remote
GitLab or GitHub repository is never deleted.

A project with workflow run history cannot be removed because doing so would break its
durable audit trail. Keep the project registered when historical runs exist.

## Create a workflow credential

Open **Credentials**, choose **Add credential**, and provide a name and secret value. The name becomes an environment variable for workflow subprocesses, so use an identifier such as `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `NPM_TOKEN`.

Kyron stores Fernet ciphertext plus safe metadata. Read endpoints never return the secret value.

Use the shell's environment syntax in a Bash node:

```json
{
  "id": "publish",
  "type": "bash",
  "label": "Publish package",
  "config": {
    "command": "npm config set //registry.npmjs.org/:_authToken \"$NPM_TOKEN\" && npm publish",
    "allow_failure": false,
    "shell": "/bin/bash"
  }
}
```

Do **not** write `${NPM_TOKEN}`. Kyron interprets that as a public template variable and fails because credentials are deliberately excluded from public context.

## Secret lifetime

For each process operation, Kyron:

1. decrypts the credential immediately before use;
2. adds the value to the in-memory output redactor;
3. passes it through the subprocess environment;
4. streams redacted output; and
5. discards plaintext references after the operation.

This reduces exposure but does not make untrusted workflow code safe. A malicious process can still exfiltrate environment values. Only trusted authors and repositories belong in Kyron.

## Rotation

Replace credentials and project tokens through their write-only update actions. To rotate the master Fernet key, follow the controlled procedure in the [operations runbook](/operations); replacing it without re-encrypting existing values makes those credentials unreadable.
