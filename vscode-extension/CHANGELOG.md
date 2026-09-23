# Changelog

## Unreleased

- Mirror `.workflowEngine/` folders in the workflow tree and folder-aware picker.
- Add workflow browser navigation, catalog warnings, and clearer empty and blocked states.
- Prevent overlapping run polling and stale project refresh results.
- Notify only reviewers whose approval can contribute to an open gate, and select
  their gate when parallel reviews are open.
- Add unit tests for tree construction, Git remotes, input validation, and run status presentation.

## 0.1.0

- Add secure Kyron device sign-in with rotating credentials.
- Match workspaces to Kyron projects from Git remotes.
- List and trigger workflows with typed inputs and explicit run subjects.
- Monitor runs, inspect logs, cancel, resume, and hand gates to provider review extensions.
