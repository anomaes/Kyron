# Kyron Workflows for Visual Studio Code

Run and monitor workflows on a Kyron deployment without leaving Visual Studio
Code. The extension provides:

- device-based sign-in through your existing Kyron browser session;
- automatic matching between the current Git remote and an accessible Kyron project;
- folder-aware workflow discovery and type-aware input prompts;
- branch and merge/pull-request run subjects;
- run status, logs, cancellation, resumption, and review notifications; and
- gate handoff to GitLab Workflow or GitHub Pull Requests for authoritative review.

## Connect

1. Set **Kyron: Server URL**, or run **Kyron: Connect to Kyron** and enter it.
2. Check the short code shown by VS Code, open Kyron, and approve the connection.
3. Open the Kyron activity-bar view. Select a project if the current Git remote
   was not matched automatically.

Triggering is temporarily disabled while the project has outgoing or in-review
workflow-definition changes. This keeps the displayed definition aligned with
the trusted merged definition used by a normal run.

The workflow view mirrors folders below `.workflowEngine/`. Expand or collapse
folders to browse the catalog, use the workflow context menu to open a
definition in Kyron, and open the warning indicator when invalid definitions
were skipped while loading the catalog.

Access and refresh credentials are held in VS Code `SecretStorage`. Kyron stores
only SHA-256 hashes of the opaque credentials. Access tokens are short-lived and
refresh credentials rotate whenever they are used.

## Review a gate

When a run reaches `AWAITING_FEEDBACK`, use **Review Current Gate**. If the
matching provider extension is installed, Kyron focuses its review view and
identifies the exact merge or pull request. Approve or add an `@kyron` revision
comment there. The code host webhook remains the authoritative input to the
snapshotted approval policy; this extension does not create a parallel approval
path.

## Develop

```bash
npm ci
npm run check
npm test
npm run build
npm run package
```

Press `F5` from the extension folder to launch an Extension Development Host,
or install the generated `.vsix` with **Extensions: Install from VSIX…**.
