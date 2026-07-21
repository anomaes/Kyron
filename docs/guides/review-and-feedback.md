---
title: Reviews and feedback
description: Add human checkpoints and control them through Kyron or the code host.
---

# Reviews and feedback

Human control in Kyron is not an informal pause. It is a durable checkpoint tied to an
exact commit, a snapshotted project approval policy, and the active change request.

## Human feedback node

Use `human_feedback` when the workflow should stop once, present the current branch for review, and then continue on approval or comment feedback.

```json
{
  "id": "review",
  "type": "human_feedback",
  "label": "Review implementation",
  "join": "and",
  "config": {
    "approval_policy": "default",
    "commit_message": "Checkpoint: implementation ready for review",
    "mr_title": "Review ${WORKFLOW_NAME}",
    "mr_description": "Inspect run ${RUN_ID} at ${BASE_COMMIT_SHA}.",
    "allow_comment_feedback": true,
    "allow_approval": true
  },
  "position": { "x": 620, "y": 120 }
}
```

When reached, Kyron commits pending work, resolves the selected approval policy, snapshots
eligible users and requirements, requests their provider identities as reviewers, and sets
the run to `awaiting_feedback`.

The built-in `default` policy requires one approval from the user who triggered the workflow.
The `approval_policy` field may be omitted because `default` is also the schema default. Select a
custom project policy when the triggerer must not approve their own run or more reviewers are
required.

## Who may continue the run

Provider user IDs in the gate eligibility snapshot are authoritative. Matching by email or
username is not enough. Role changes do not alter an already-open gate.

Frontend actions also require the active session provider to match the run provider. Webhooks authenticate their raw request, normalize the provider event, verify project identity, and compare the actor to the open gate's eligibility snapshot.

## Approval

Approval says “continue without revision.” It can arrive from Kyron's run detail or a provider approval event. Kyron records partial approvals and remains paused until every policy requirement reaches quorum.

Before execution continues, Kyron consumes the intermediate provider approval:

- GitLab synchronizes then resets approvals.
- GitHub dismisses the relevant approving review.

This makes the protected branch require a **fresh** approval for final merge. Configure the repository to require approving reviews and grant the Kyron identity the permission needed to consume them.

## Comment feedback

Comment feedback says “continue with these revision instructions.” In the UI, submit feedback from the checkpoint controls. On the provider, a non-system change-request comment addressed to `@kyron` is normalized as feedback.

After feedback, these public variables become available:

| Variable | Value |
| --- | --- |
| `FEEDBACK` | Latest feedback text |
| `FEEDBACK_TYPE` | `comment` or `approval` |
| `FEEDBACK_AUTHOR` | Provider username that supplied it |

Do not use `${FEEDBACK}` before the first event. In a review loop, place it in `revision_inputs`, not initial `inputs`.

## Idempotency and races

Webhook delivery IDs are provider-prefixed and deduplicated. The feedback service also protects state transitions so a provider webhook and frontend submission arriving together cannot advance the same checkpoint twice.

Invalid or stale transitions return HTTP 409. Reload run state before retrying.

## Choose the right construct

| Need | Use |
| --- | --- |
| One gate before continuing | `human_feedback` |
| Repeat implementation after feedback | `review_loop` |
| A final code-host review after the run | Normal protected-branch policy; the run may already be `completed` |

For bounded revision cycles, continue to [review loops](/workflows/review-loops).
