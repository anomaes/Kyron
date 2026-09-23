---
title: Visual Studio Code
description: Trigger, monitor, and review Kyron workflows from VS Code.
---

# Use Kyron from Visual Studio Code

The Kyron extension is a direct user interface to the existing HTTP API. It does
not require an AI agent or MCP client: the person chooses a workflow, supplies
its inputs and subject, and explicitly confirms the run.

## Install the development build

The extension currently ships as a source-built VSIX; the GitHub release does
not yet contain an extension asset and it is not published in the Visual Studio
Marketplace. You need VS Code 1.92 or newer and a Node.js/npm installation.

From a Kyron repository checkout, build the package:

```bash
npm --prefix vscode-extension ci
npm --prefix vscode-extension run check
npm --prefix vscode-extension test
npm --prefix vscode-extension run package
```

In VS Code, run **Extensions: Install from VSIX…** and choose the generated file.
The file is written below `vscode-extension/` and is named like
`kyron-workflows-0.1.0.vsix`. Reinstall a newly built VSIX when upgrading an
unpublished development build.

## Configure extension settings

Open **Settings**, search for `Kyron`, and configure:

| Setting | Default | Valid values | Purpose |
| --- | --- | --- | --- |
| `kyron.serverUrl` | empty | HTTPS origin, without an API path | Deployment used by Connect and browser links |
| `kyron.pollIntervalSeconds` | `10` | `3`–`120` seconds | Refresh interval for active runs |

**Kyron: Connect to Kyron** prompts for the server URL when the setting is
empty. Use the same trusted HTTPS origin users open in a browser; do not disable
certificate verification for a private deployment.

## Connect to a deployment

1. Run **Kyron: Connect to Kyron**.
2. Enter the HTTPS origin of the deployment if it is not already configured.
3. Compare the short code in VS Code with the code on the Kyron page.
4. Sign in through the normal GitLab or GitHub OAuth flow and select
   **Connect VS Code**.

The one-time device code expires after ten minutes by default. VS Code stores the
opaque access and refresh credentials in `SecretStorage`; the Kyron database
stores only their SHA-256 hashes. Access credentials are short-lived and every
refresh rotates both credentials. **Kyron: Disconnect from Kyron** revokes the
server-side session and removes the local credentials.

## Select a project and run a workflow

The extension compares the current repository's Git remotes with the accessible
Kyron project URLs. It selects an exact host-and-project-path match, without
storing or displaying authenticated remote URLs. Use **Kyron: Select Project** if
there is no match or if the workspace should operate another project.

The **Workflows** view lists definitions from Kyron's default-branch catalog and
mirrors their folder structure below `.workflowEngine/`. Folder counts include
all nested workflows. Select a workflow to:

1. choose the current branch, default branch, another remote branch, or an open
   merge/pull request;
2. enter schema-aware string, integer, number, and boolean inputs; and
3. confirm the request.

The workflow context menu can open the definition in the Kyron web UI. If Kyron
skips an invalid definition while loading the catalog, the view shows a warning;
open **Show Workflow Catalog Warnings** for the affected paths and validation
messages. The view also explains when triggering is unavailable because of
permissions or unmerged definition changes.

The extension always sends `use_local_definitions: false`. The backend still
resolves the chosen subject, loads the workflow graph from the correct trusted
definition revision, and snapshots the exact commits before it queues execution.
If the project has outgoing or in-review definition changes, the extension
temporarily blocks triggering so an overlaid draft cannot be mistaken for the
merged definition that a normal run would execute. Publish, merge, and refresh
those changes first; local-definition test runs remain available in the web UI.

## Follow runs and review gates

The **Runs** view polls the selected project's latest runs. From a run you can
inspect durable log events, open the full Kyron run, cancel active execution, or
resume a recoverable run. VS Code sends a review notification only when the
connected provider identity is eligible for an open gate, has not already
approved it, and can still contribute to its quorum. Completion, failure, and
interruption notifications remain visible for all listed runs.

For a GitLab gate, install the
[GitLab Workflow extension](https://marketplace.visualstudio.com/items?itemName=GitLab.gitlab-workflow)
and sign in to the
same provider account used for Kyron. **Kyron: Review Current Gate** focuses the
GitLab review view and identifies the exact merge request. Review the diff there,
then approve it or add an `@kyron` revision comment. GitHub uses the equivalent
[GitHub Pull Requests extension](https://marketplace.visualstudio.com/items?itemName=GitHub.vscode-pull-request-github).

The provider remains authoritative. Kyron consumes the signed webhook, checks
the reviewer against the gate's eligible-identity snapshot and quorum, then
continues or revises the workflow. The VS Code extension intentionally does not
offer a separate API approval button.

::: tip Staying in VS Code
With the provider review extension installed, workflow selection, run monitoring,
diff review, comments, and approval can all happen inside VS Code. The browser is
needed only for the initial Kyron device authorization (and as a fallback for
opening detailed run or change-request pages).
:::
