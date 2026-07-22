---
title: Access and governance
description: Configure project roles, approval policies, workflow norms, and traceability reports.
---

# Access and governance

The first user to sign in to a new Kyron database becomes the global system
administrator. That administrator registers projects and can reach every project.
All other access comes from project membership.

## Project roles

Every project starts with Project Administrator, Workflow Author, Operator, Approver,
and Viewer roles. A membership may hold several roles. Project administrators can also
create custom roles from Kyron's fixed permission catalogue. Built-in roles are immutable,
which keeps their meaning consistent across projects.

Role permissions are additive: a member with several roles receives the union of their
permissions. The built-in roles contain exactly these permissions:

| Role | Intended use | Permissions |
| --- | --- | --- |
| Project Administrator (`project-admin`) | Administer one project and all of its workflows and runs | Every project permission listed below |
| Workflow Author (`workflow-author`) | Create, validate, and publish workflow definitions and node templates | `project.view`, `policy.view`, `workflow.view`, `workflow.edit`, `workflow.publish`, `run.view`, `report.view` |
| Operator (`operator`) | Trigger workflows and control runs they started | `project.view`, `policy.view`, `workflow.view`, `run.view`, `run.trigger`, `run.control.own`, `report.view` |
| Approver (`approver`) | Inspect runs and respond when selected by an approval policy | `project.view`, `policy.view`, `workflow.view`, `run.view`, `gate.respond`, `report.view` |
| Viewer (`viewer`) | Read workflows, runs, logs, and reports without changing them | `project.view`, `policy.view`, `workflow.view`, `run.view`, `report.view` |

The permission catalogue has the following meaning:

| Permission | Allows |
| --- | --- |
| `project.view` | View the project's repository metadata and configuration |
| `project.manage` | Replace or validate the repository token, change Pi defaults, fetch the repository, and remove the project |
| `membership.manage` | List project members and available users, add or update memberships and role assignments, and activate or deactivate memberships |
| `role.manage` | List roles and create or update custom roles; built-in roles remain immutable |
| `policy.view` | View approval policies |
| `policy.manage` | Create or update approval policies and governance profiles |
| `workflow.view` | View workflow definitions, node templates, references, and local change status |
| `workflow.edit` | Validate, create, update, or delete local workflow definitions and node templates |
| `workflow.publish` | Commit and push local workflow and node-template changes to the repository |
| `run.view` | View runs, execution graphs, node details, outputs, and live or stored logs |
| `run.trigger` | Start a workflow run |
| `run.control.own` | Cancel or resume runs started by the same user |
| `run.control.any` | Cancel or resume any run in the project |
| `run.delete` | Permanently delete completed, failed, interrupted, or cancelled runs and their local resources |
| `gate.respond` | Approve or provide feedback at a gate when the user is eligible under the gate's snapshotted approval policy |
| `gate.override` | Override a stuck gate with a recorded reason |
| `report.view` | View run traceability reports |
| `audit.view` | View the project's authorization audit events |

A Project Administrator has all of these permissions, including control of any project
run, deletion of inactive runs, and audited gate overrides. Deleting a run removes its
worktree, local branch, stored output, logs, report, and execution history; the authorization
audit event recording who deleted it remains. Remote branches and pull or merge requests are
not deleted. A global system administrator is separate from the
`project-admin` role: system administrators receive every project permission without a
project membership and can register projects and manage global users. Disabling a user
globally immediately prevents login and gate responses. Permissions do not bypass provider
identity checks: repository-writing actions and run control still require a session from the
project or run's code-host provider.

## Approval policies

Approval policies select one or more project roles and optionally named members. Each
requirement has its own quorum. A policy also decides whether the run initiator may approve
and whether the same person may satisfy several requirements.

Every project starts with a `default` policy whose only eligible reviewer is the user who
triggered the workflow. One approval satisfies it, and that user may also provide revision
feedback. This makes new human-feedback and review-loop nodes usable immediately. Create another
policy and change the workflow's `approval_policy` key when independent or multi-person review is
needed.

Workflow gate nodes reference a stable policy key. When a gate opens, Kyron snapshots the
policy, eligible provider identities, and exact checkpoint commit. Later membership changes
do not rewrite that open gate. A new review iteration resolves current membership again.

Feedback closes the current gate as changes requested. Existing approvals remain visible but
are superseded; they never count toward the revised checkpoint. A project administrator may
override a stuck gate only by recording a reason, and the report highlights that decision.

## Governance profiles

Governance profiles apply to all workflows or only workflows with selected tags. They can
require named approval policies, a minimum total quorum, and independent approval. Kyron
checks profiles while validating, storing, publishing, and triggering workflows.

## Traceability reports

Every Run Detail page includes a live report. Completed runs and currently cancelled runs receive
a frozen execution report containing the trigger identity, exact workflow and code SHAs,
root and child invocation paths, every gate policy snapshot, all decisions and feedback,
and administrative events. Resuming a cancellation discards that cancellation snapshot so the
eventual result can be frozen instead. Merge or close webhooks received later appear as
append-only post-run lifecycle addenda.
