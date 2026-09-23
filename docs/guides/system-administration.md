---
title: System administration
description: Manage Kyron users and global AI-provider configuration.
---

# System administration

The first user who signs in to a new Kyron database becomes the global system
administrator. System administrators can register projects, access every
project permission, manage global users, and configure the Pi model catalog.
Project Administrator is a separate, project-scoped role.

## Bootstrap safely

1. Start Kyron and verify that only the intended OAuth providers are enabled.
2. Sign in with the account that should own initial administration.
3. Open **Administration → Users** and confirm that account is active and marked
   **Administrator**.
4. Grant a second trusted account system-administrator access before relying on
   the installation for production work.

Avoid removing administrator access from the last usable administrator. User
and administrator changes are immediate; keep an authenticated recovery session
until the replacement account has signed in successfully. Kyron prevents an
administrator from disabling or demoting their own current account, but another
administrator can change it.

## Manage users

Open **Administration → Users**. This page lists the provider identity, last
login, activation status, and global administrator status of every known user.

- **Active / Disabled** controls whether the user may sign in or respond to a
  gate. Disabling an account takes effect immediately.
- **Administrator / Standard user** grants or removes global administration.
- Project access for a standard user is configured separately in the project's
  administration page through memberships and roles.

Provider identities are keyed by provider and immutable provider user ID, not
by email. Kyron does not merge GitLab and GitHub identities merely because their
email addresses match.

## Configure built-in model providers

For a Pi built-in provider, users normally create the required secret under
**Credentials** and select the provider/model in project, workflow, or Prompt
node settings. Credential values remain user-owned and write-only.

The selection order is:

1. Prompt-node override;
2. workflow Pi setting;
3. project Pi default.

Each field inherits independently, so a workflow can override the model while
retaining the project's provider and skill.

## Configure custom AI providers

Open **Administration → AI providers** to add OpenAI-compatible,
Anthropic-compatible, or Google-compatible endpoints. The guided editor covers
the common fields; the advanced editor accepts Pi's complete models
configuration.

Kyron validates a proposed configuration with the installed Pi version before
activation. Each activation creates an audited database revision. New runs
snapshot the active revision when queued; changing the active revision never
rewrites an existing run. Earlier revisions can be validated and restored from
the same page.

Secret-like values in provider configuration must refer to Kyron credential
names, for example `$CUSTOM_LLM_API_KEY`, rather than containing plaintext.
Create matching credentials for the users who trigger workflows and ensure the
workflow's credential policy makes them available.

The optional `PI_MODELS_CONFIG_PATH` file is a bootstrap or fallback, not an
additional merged source. A database-managed revision takes precedence. See
[Custom Pi providers](/deployment/configuration#custom-pi-providers) for the
complete JSON contract and file-managed alternative.

## Project administration

Open a project's administration page to manage its memberships, custom roles,
approval policies, governance profiles, and authorization audit. These controls
are documented in [Access and governance](/guides/access-and-governance).
