---
title: GitLab and GitHub
description: Configure OAuth, repository tokens, webhooks, and approval policy.
---

# GitLab and GitHub

Kyron normalizes both providers behind one code-host contract while preserving provider-specific authentication and approval behavior.

## Identity model

A browser session contains exactly one active provider identity. The durable identity key is `(provider, provider_user_id)`; accounts are never merged by email.

The signed-in identity and project token have separate jobs:

- **Signed-in identity** — determines provider affinity and who performs each
  project, run, or gate action. Gate actions additionally require membership in
  the gate's eligible-identity snapshot and the appropriate permission.
- **Project token** — performs Git operations and provider API calls on Kyron's behalf.

## Shared OAuth callback

Both provider applications use the external callback:

```text
https://kyron.example.com/auth/callback
```

OAuth state binds the provider, nonce, return target, and expiry. The callback uses the provider captured in state rather than trusting a callback query parameter.

## GitLab setup

Create a confidential OAuth application with:

- callback URI `https://kyron.example.com/auth/callback`;
- `read_user` scope; and
- the configured `GITLAB_URL` as the instance root.

Configure a project access token able to:

- read and write repository contents;
- create/update merge requests;
- assign or refresh every reviewer selected by an approval policy;
- post traceability comments; and
- synchronize and reset intermediate approvals.

Create a project webhook at:

```text
https://kyron.example.com/api/webhook/gitlab
```

Subscribe to merge-request and note events. Copy the project's webhook secret from
Kyron's Projects page into GitLab's secret-token field. If Standard Webhooks signing is
used, store its signing secret with the project and configure the same value in GitLab.

## GitHub setup

Create an OAuth App with:

- homepage URL `https://kyron.example.com`;
- authorization callback URL `https://kyron.example.com/auth/callback`.

Kyron requests `read:user user:email`. When the public profile omits email, it selects the authenticated user's verified primary email. Incomplete identities do not create sessions.

Use a repository token with contents and pull-request write access. The Kyron bot/app identity must be able to request reviewers, comment, and dismiss reviews.

Create a JSON webhook at:

```text
https://kyron.example.com/api/webhook/github
```

Subscribe to:

- pull requests;
- pull-request reviews; and
- issue comments.

Copy the project's webhook secret from Kyron's Projects page into GitHub's secret field.
Kyron resolves the repository project and validates `X-Hub-Signature-256` over the raw
request body with that project's secret. `X-GitHub-Delivery` is used for deduplication.

## Protected branches

Every target branch used for delivery should require a fresh approving review. Kyron consumes intermediate checkpoint approvals before execution continues:

- GitLab calls approval synchronization and reset.
- GitHub dismisses the active approving reviews that satisfied the intermediate
  gate.

Grant this authority explicitly. Do not rely only on “dismiss stale approvals on new commits”; Kyron must be able to enforce the transition it records.

## Accepted webhook actions

After authentication and project matching, Kyron normalizes:

| Provider action | Kyron action |
| --- | --- |
| Eligible reviewer approves | Approval toward the snapshotted policy quorum |
| Eligible reviewer posts non-system `@kyron` comment | Revision feedback |
| Change request merges or closes | Worktree/local branch cleanup |

The top-level provider actor identity must be present in the gate's immutable
eligible-identity snapshot and retain `gate.respond` permission. The default
policy selects only the run initiator; custom policies can select other members
and require several approvals. Duplicate deliveries and concurrent UI/webhook
submissions do not advance a checkpoint twice.

## Enterprise and self-managed hosts

For self-managed GitLab, set `GITLAB_URL` to the instance web root. For GitHub Enterprise Server, set both `GITHUB_WEB_URL` and `GITHUB_API_URL`; do not leave public GitHub defaults.

Ensure the VM can resolve and reach the provider over HTTPS and that the provider can reach the public webhook endpoint.

## Provider validation checklist

- [ ] OAuth sign-in returns a complete provider identity.
- [ ] A session cannot mutate a project on the other provider.
- [ ] Repository validation returns canonical metadata.
- [ ] Clone, fetch, branch push, and change-request creation succeed.
- [ ] Reviewer assignment succeeds for every identity selected by an approval policy.
- [ ] Signed webhooks are accepted and altered bodies are rejected.
- [ ] Duplicate delivery IDs are ignored.
- [ ] An intermediate approval is consumed successfully.
- [ ] Merge/close cleanup removes only the run's validated resources.
