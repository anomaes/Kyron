# Code-host provider architecture

This document is the normative delta that extends Kyron from GitLab-only delivery
to GitLab and GitHub delivery. Where the original workflow engine specification
names GitLab-specific fields or operations, the provider-neutral behavior below
supersedes it. The existing state-machine, exact-commit, credential, review, and
single-worker invariants remain unchanged.

## Scope and identity model

Kyron supports `gitlab` and `github` code-host providers. The sign-in page offers
every configured provider. A browser session contains exactly one active provider
identity and a user may only mutate, trigger, approve, or provide feedback for a
project on that provider. Cross-provider actions fail with HTTP 403.

Provider identities are never inferred or merged by email. The durable identity
key is `(provider, provider_user_id)`. A Kyron user has exactly one provider
identity in this release; the separate identity table intentionally permits a
future, explicit account-linking flow without changing run history.

The project access token is independent from the signed-in identity. It performs
Git/API operations, while the signed-in provider identity determines the requested
reviewer and the only actor permitted to control checkpoints.

## Durable model

- `provider_identities` stores provider, immutable provider user ID, current
  username, and its Kyron user.
- `projects` stores `provider`, `provider_project_id`, and
  `provider_project_path`. Project IDs are strings at the boundary because the
  provider namespaces differ; GitLab IDs and GitHub repository IDs remain intact.
- `workflow_runs` stores provider-neutral change-request fields plus the reviewer
  provider, provider user ID, and username snapshot.
- `feedback_events` stores provider-neutral actor and comment/review identifiers.
- `webhook_deliveries` stores the provider and provider project ID. Delivery keys
  are provider-prefixed before deduplication.

Migration `0002` converts every existing user, project, run, feedback event, and
webhook delivery to `gitlab` without changing its semantic identity or history.

## Provider adapter contract

Backend services depend on `CodeHostClient`, not a concrete provider client. The
contract normalizes these operations:

1. validate repository metadata;
2. find an open merge request or pull request by source and target branch;
3. create a merge request or pull request;
4. request or refresh the complete gate reviewer set;
5. inspect change-request lifecycle state;
6. post a traceability comment;
7. consume an intermediate approval so final merge requires a fresh approval.

GitLab implements approval consumption with approval synchronization followed by
`reset_approvals`. GitHub dismisses the submitted approving review. For a frontend
approval, GitHub looks up and dismisses active reviews that satisfied the gate;
if none exist, there is no provider approval to consume. Repository
policy must require approving reviews for the fresh-final-approval guarantee.

Provider responses are converted immediately into `RepositoryMetadata`,
`ChangeRequest`, and `ProviderComment`; provider-shaped dictionaries do not cross
the integration boundary.

Creation is recoverable across ambiguous network failures. The coordinator checks
for an existing open change request on the run's unique source branch before creation
and checks again when a create request fails. It stores the returned identifier before
the separate reviewer update, so reviewer-assignment failure cannot orphan an
untracked change request.

## Webhooks

The unauthenticated webhook endpoints are:

- `POST /api/webhook/gitlab`
- `POST /api/webhook/github`

GitLab retains token/optional Standard Webhooks signature validation. GitHub
requires `X-Hub-Signature-256` HMAC-SHA256 validation over the raw request body.
`X-GitHub-Delivery` is the delivery identifier and `X-GitHub-Event` is the event
name.

Normalized events are accepted only when project provider and repository ID match:

- approving review -> approval feedback;
- non-system `@kyron` change-request comment -> comment feedback;
- merge/close -> resource cleanup.

The top-level provider actor must match the reviewer identity snapshot on the run.
Duplicate delivery and concurrent frontend/webhook protections remain mandatory.

## Authentication and trusted boundary

The auth service exposes a provider chooser at `/auth/login` and provider-specific
authorization at `/auth/login?provider=<provider>`. OAuth state binds the provider,
nonce, return target, and expiry. The callback uses the bound provider and never a
provider supplied by the callback request.

Caddy removes and then copies only these provider-neutral trusted headers:

- `X-Token-User-Email`
- `X-Token-User-Name`
- `X-Token-User-Avatar`
- `X-Token-Provider`
- `X-Token-Provider-User-Id`
- `X-Token-Provider-Username`

GitHub email discovery uses the authenticated user's verified primary email when
the public profile omits an email. A provider without complete identity data may
not create a session.

## Configuration

GitLab configuration remains `GITLAB_URL`, `GITLAB_WEBHOOK_SECRET`,
`GITLAB_OAUTH_CLIENT_ID`, and `GITLAB_OAUTH_CLIENT_SECRET`. GitHub configuration is
`GITHUB_API_URL`, `GITHUB_WEB_URL`, `GITHUB_WEBHOOK_SECRET`,
`GITHUB_OAUTH_CLIENT_ID`, and `GITHUB_OAUTH_CLIENT_SECRET`. A provider appears on
the sign-in page only when both of its OAuth values are configured.

The shared `OAUTH_REDIRECT_URI` must point to `/auth/callback`. Legacy
`OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET` remain GitLab fallbacks for one release.

## API and UI behavior

Project registration requires `provider`, `provider_project`, HTTPS clone URL, and
an access token. `provider_project` is a GitLab numeric project ID/path or a GitHub
`owner/repository` path. The backend persists canonical metadata returned by the
provider.

Project lists and run history remain visible to every authenticated internal user.
Mutation controls are enabled only when the active session provider matches the
project/run provider. Direct API attempts receive HTTP 403.

User-facing language uses “change request” where both providers are possible and
“merge request” or “pull request” only for provider-specific links or instructions.

## Delivery plan

1. Introduce the provider-neutral schema and migration, normalized adapter
   protocol, and provider factory while preserving GitLab behavior.
2. Implement the GitHub REST adapter, approval dismissal, webhook authentication,
   webhook event normalization, and tests.
3. Make project, workflow, coordinator, feedback, reconciliation, and lifecycle
   services provider-aware and enforce provider affinity at API boundaries.
4. Add the OAuth provider chooser, GitHub OAuth flow, neutral trusted headers, and
   provider-identity upsert semantics.
5. Update frontend forms/types/labels, Caddy routes, environment examples, API and
   operations documentation.
6. Run migration, backend, frontend, auth, Compose, lint, and type-check gates; add
   environment acceptance checks for both providers.

## Acceptance criteria

- Existing GitLab data migrates and existing GitLab behavior remains green.
- The same email on GitLab and GitHub creates distinct Kyron users.
- A session cannot control a project or run belonging to the other provider.
- GitHub repository validation, clone/fetch/push, PR creation, reviewer request,
  comments, review approval, review dismissal, close/merge cleanup, webhook replay,
  and reconciliation are covered by automated adapter/domain tests.
- Neither provider token nor authenticated Git URL is persisted or logged.
- An intermediate provider approval cannot satisfy the final protected-branch
  approval requirement.
