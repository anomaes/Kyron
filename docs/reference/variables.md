---
title: Variables and outputs
description: Kyron public context, template expansion, node output variables, and secret separation.
---

# Variables and outputs

Kyron keeps persistable public context separate from ephemeral secret environment values.

## Template syntax

Public templates use exact `${NAME}` syntax. Names match `[A-Za-z_][A-Za-z0-9_]*`. Expansion converts the public value to text and fails when the name is unknown.

Supported locations include:

- Bash `config.command`;
- each Script `config.args` item;
- Prompt `config.prompt`;
- sub-workflow and review-loop mappings;
- workflow output `source`; and
- checkpoint, wave, final-commit, and change-request templates.

Templates do not expand in IDs, labels, paths, `script`, `python`, `shell`, `provider`, or `model`.

Public context is also copied into the environment of every Bash, Script, and Prompt
process. Bash may therefore read `$TARGET_DIR`, and a repository script may read
`os.environ["TARGET_DIR"]`. Script arguments and prompt text use Kyron's `${TARGET_DIR}`
template syntax instead. Prompt nodes are launched without a shell, so `$TARGET_DIR` in
the prompt remains literal text; use `${TARGET_DIR}` when the value should become part of
the prompt.

## Context precedence

More specific runtime values override definition defaults. Conceptually, context is assembled from workflow variables, invocation inputs, Kyron built-ins, mapped parent values, and later node/feedback outputs. Validation prevents ambiguous or impossible mappings where it can.

For example, a root trigger input overrides a workflow variable with the same name, and
a mapped child input overrides the child's default. Prefer workflow variables for fixed,
non-secret defaults and inputs for values the caller is allowed to choose.

Do not reuse a name for unrelated meanings across these layers.

## Run and repository built-ins

| Variable | Meaning |
| --- | --- |
| `RUN_ID` | Full run UUID |
| `RUN_ID_SHORT` | First eight hex characters of the run UUID |
| `ROOT_WORKFLOW_ID` | Root workflow ID |
| `WORKFLOW_ID` | Current invocation workflow ID |
| `WORKFLOW_NAME` | Current invocation workflow name |
| `INVOCATION_ID` | Current invocation UUID |
| `INVOCATION_PATH` | Hierarchical path such as `root/quality` |
| `PROJECT_ID` | Project UUID |
| `PROJECT_NAME` | Project display name |
| `BASE_REF` | Ref selected by the user |
| `BASE_COMMIT_SHA` | Exact pinned commit SHA |
| `BRANCH` | Run branch name |
| `WORKTREE_PATH` | Absolute run worktree path |
| `RUN_DATA_PATH` | Absolute run output-data path |

`WORKTREE_PATH` and `RUN_DATA_PATH` are trusted engine-derived paths. Workflow code should not construct sibling paths or escape these roots.

## User and provider built-ins

| Variable | Meaning |
| --- | --- |
| `USER_NAME` | Triggering user's display name |
| `USER_EMAIL` | Triggering user's email |
| `CODE_HOST_PROVIDER` | `gitlab` or `github` |
| `PROVIDER_USER_ID` | Immutable triggering provider ID as text |
| `PROVIDER_USERNAME` | Triggering provider username |
| `GITLAB_USER_ID` | Legacy alias populated only for GitLab runs |
| `GITLAB_USERNAME` | Legacy alias populated only for GitLab runs |

Prefer provider-neutral names in new workflows.

## Review built-ins

| Variable | Availability |
| --- | --- |
| `REVIEW_ITERATION` | Inside a review-loop iteration |
| `FEEDBACK` | After the first feedback event |
| `FEEDBACK_TYPE` | `comment` or `approval` after feedback |
| `FEEDBACK_AUTHOR` | Latest feedback provider username |

`WAVE_INDEX` is additionally available while expanding `wave_commit_message_template`.

Never reference feedback variables in initial review-loop inputs.

## Process node outputs

After a Bash, Script, or Prompt node succeeds, Kyron publishes:

```text
NODE_<node_id>_EXIT_CODE
NODE_<node_id>_STDOUT
NODE_<node_id>_STDERR
NODE_<node_id>_STDOUT_PATH
NODE_<node_id>_STDERR_PATH
```

For node ID `tests`, use `${NODE_tests_EXIT_CODE}`. Text values are bounded previews controlled by output limits. Use path variables inside trusted repository code when complete output is required.

A downstream node can consume these values after an edge has made it depend on the
producer. For example, if `choose_environment` prints only `staging`, a later Prompt node
may use `${NODE_choose_environment_STDOUT}`, and a later process may read
`$NODE_choose_environment_STDOUT`. Ready process nodes in the same wave start from the
same context and cannot consume one another's outputs.

Each node runs in a new subprocess. An `export TARGET_ENV=staging` in Bash applies only
to that process and its children; it does not modify later node environments. Publish a
value through the standard node outputs, or declare a child workflow output and map it to
a parent name with `output_mapping`.

Prompt stdout is Pi's raw JSONL event stream; readable engine events are separately available in run logs.

## Workflow outputs

```json
"outputs": {
  "SUMMARY": {
    "type": "string",
    "source": "${NODE_analyze_STDOUT}",
    "description": "Bounded analysis summary"
  }
}
```

Sources expand at invocation completion. A parent's `output_mapping` can expose a child output under a new public name.

## Credentials are not variables

Every Bash, Script, and Prompt process receives all credentials owned by the user who
triggered the run. The control nodes do not have subprocess environments, although
process nodes inside their child workflows receive the same triggering user's
credentials. Use native process syntax:

```bash
curl -H "Authorization: Bearer $INTERNAL_API_TOKEN" https://service.example/api
```

`${INTERNAL_API_TOKEN}` asks for a public variable and fails if only a credential exists. Secret values must never be stored in workflow `variables`, trigger inputs, output mappings, prompts, or change-request templates.

Credential names share the subprocess namespace with public and operating-system
variables. Avoid Kyron built-in names such as `RUN_ID` and `USER_EMAIL`, along with base
environment names such as `PATH` and `HOME`.
