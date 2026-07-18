---
title: Edges, conditions, and joins
description: Define dependencies, conditional branches, and node readiness.
---

# Edges, conditions, and joins

An edge declares that a target depends on a source. With no condition, the edge is satisfied when its source succeeds. With a condition, Kyron evaluates the condition once the source is terminal and records the result.

```json
{
  "id": "tests_to_publish",
  "source": "tests",
  "target": "publish",
  "condition": null
}
```

Edge IDs are unique identifiers. `source` and `target` must name nodes in the same workflow, and self-edges are invalid.

## Exit code condition

Compare the source process exit code:

```json
"condition": {
  "type": "exit_code",
  "operator": "equals",
  "value": 0
}
```

Operators are `equals`, `not_equals`, `greater_than`, `greater_than_or_equal`, `less_than`, and `less_than_or_equal`.

Exit-code conditions require a process source node that produces an exit code.

## Output contains condition

Search bounded source output for a string:

```json
"condition": {
  "type": "output_contains",
  "value": "READY_FOR_REVIEW",
  "stream": "stdout"
}
```

`stream` is `stdout`, `stderr`, or `combined`. Prefer explicit machine-readable markers over fragile matches against human prose.

## File exists condition

Test for a path in the current run worktree:

```json
"condition": {
  "type": "file_exists",
  "value": "reports/coverage.xml"
}
```

The path must be repository-relative and may not escape with `..`. The check happens after the source is terminal and sees the checkpointed worktree state available at that point.

## Variable condition

Compare a public context value:

```json
"condition": {
  "type": "variable",
  "name": "STRICT",
  "operator": "equals",
  "value": true
}
```

The variable must exist and the comparison follows the value's public type. Credentials are never eligible.

## AND joins

`"join": "and"` is the default. A target becomes ready only when every incoming edge is resolved and satisfied.

Use AND when all prerequisites matter—for example, both tests and lint must succeed before review.

```text
tests ──┐
        ├──> review  (and)
lint  ──┘
```

If one branch cannot satisfy its edge, the target is skipped rather than waiting forever.

## OR joins

`"join": "or"` makes a target ready when at least one incoming edge is satisfied. The scheduler still resolves graph state deterministically and records every edge decision needed to explain why the node ran.

Use OR for mutually exclusive routes that converge on a common action.

```text
fast_path ──┐
            ├──> package  (or)
full_path ──┘
```

Do not use OR as a substitute for tolerating failure. If a source may fail without failing its wave, make that policy explicit with `allow_failure` and deliberate downstream conditions.

## Skip propagation

When no valid incoming route can make a node ready, it becomes skipped. `settings.propagate_skips` controls how aggressively that state flows through dependent graph regions. Keep the default until you have a tested branching case; small changes to skip semantics can affect large downstream sections.

## Design guidance

- Keep branches shallow and name conditions for the decision they represent.
- Prefer one decision edge over repeating the same output test at many targets.
- Avoid conditions that depend on incidental log wording.
- Use a child workflow to encapsulate a complex conditional subsystem.
- Test both the satisfied and unsatisfied path before relying on the graph in production.
- Remember that ordinary back edges are invalid; use a [review loop](/workflows/review-loops) for repetition.
