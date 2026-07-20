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

Operators may control runs they triggered. Project administrators may control any project
run. Disabling a user globally immediately prevents login and gate responses.

## Approval policies

Approval policies select one or more project roles and optionally named members. Each
requirement has its own quorum. A policy also decides whether the run initiator may approve
and whether the same person may satisfy several requirements.

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
