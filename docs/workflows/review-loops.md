---
title: Review loops
description: Model bounded implementation and revision cycles without cyclic workflow graphs.
---

# Review loops

Ordinary Kyron graphs are acyclic. A `review_loop` is the one deliberate repetition construct: it invokes a child, presents its work for human review, and either completes on approval or invokes a revision child with feedback.

## Structure

```json
{
  "id": "implementation_loop",
  "type": "review_loop",
  "label": "Implement until approved",
  "join": "and",
  "config": {
    "approval_policy": "default",
    "initial_workflow_id": "implement_change",
    "revision_workflow_id": "revise_change",
    "inputs": {
      "TASK": "${TASK}"
    },
    "revision_inputs": {
      "TASK": "${TASK}",
      "REVIEW_FEEDBACK": "${FEEDBACK}"
    },
    "commit_message": "Checkpoint: review iteration ${REVIEW_ITERATION}",
    "mr_title": "Review ${WORKFLOW_NAME}",
    "mr_description": "Iteration ${REVIEW_ITERATION} of run ${RUN_ID}",
    "max_iterations": 4,
    "output_mapping": {}
  }
}
```

`revision_workflow_id` may be omitted to reuse the initial workflow for later iterations. Separate definitions are useful when the first pass and revision instructions have meaningfully different prompts or checks.

## Runtime algorithm

1. Set `REVIEW_ITERATION` to `1`.
2. Invoke `initial_workflow_id` with `inputs`.
3. Commit and push the iteration checkpoint.
4. Resolve and snapshot the policy, create or update the run change request, and wait for eligible reviewers.
5. Once every approval requirement reaches quorum, consume the intermediate provider approvals and complete the loop.
6. On eligible comment feedback, supersede prior approvals, persist the event, increment the iteration, and invoke the revision workflow with `revision_inputs`.
7. Repeat until approval or the iteration bound is reached.

Each iteration is a separate durable child invocation. Run detail therefore shows the exact graph, attempts, and outputs for every round.

## Feedback variables

`${FEEDBACK}`, `${FEEDBACK_TYPE}`, and `${FEEDBACK_AUTHOR}` exist only after a feedback event. They are valid in `revision_inputs`, not initial `inputs`.

```json
"revision_inputs": {
  "ORIGINAL_TASK": "${TASK}",
  "REVIEW_FEEDBACK": "${FEEDBACK}",
  "REVIEWER": "${FEEDBACK_AUTHOR}"
}
```

Make the revision child's input names explicit. This produces a much clearer prompt contract than having it infer which part of context changed.

## Iteration limits

The effective bound is constrained by:

- node-level `max_iterations`, when present;
- workflow `settings.max_review_iterations`; and
- server `MAX_REVIEW_ITERATIONS`.

Choose a small, intentional bound. A review loop that repeatedly fails to converge should stop for operator analysis rather than consume unbounded model time.

## Outputs

The loop's `output_mapping` publishes outputs from the completing child invocation into the parent. Design child outputs so the initial and revision workflows expose compatible names if either may be the final iteration.

## Approval semantics

Approval completes the loop but does not mean the change request is ready to merge under branch policy. Kyron consumes intermediate approval before continuing so that final delivery still requires a fresh provider approval.

## A good division of responsibility

An effective pattern is:

- **Initial child** — inspect the request, implement it, and run local verification.
- **Revision child** — read original task plus explicit reviewer feedback, inspect current worktree state, make the smallest correction, and rerun verification.
- **Parent after loop** — run independent final checks and prepare delivery metadata.

Avoid putting provider credentials or review policy into prompts. Kyron's control node owns identity, approval consumption, and state transitions.
