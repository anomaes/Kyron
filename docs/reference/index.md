---
title: Reference
description: Direct links to Kyron's exact contracts, states, configuration, and architecture.
---

# Reference

Use these pages when you need an exact field, variable, state, route, or invariant.

## Workflow language

| Reference | Covers |
| --- | --- |
| [Workflow JSON specification](/workflow-json-authoring-spec) | Complete version 2 schema, naming, nodes, conditions, settings, and validation |
| [Variables and outputs](/reference/variables) | Public built-ins, node outputs, feedback context, templates, and secrets |
| [Node types](/workflows/node-types) | Task-oriented node configuration summary |
| [Edges and joins](/workflows/edges-and-joins) | Conditions, readiness, AND/OR, and skip behavior |

## Runtime and integration

| Reference | Covers |
| --- | --- |
| [Run states](/reference/states) | Run, wave, execution, attempt, and feedback lifecycle |
| [API guide](/api) | HTTP and WebSocket route inventory, auth, filters, and conflicts |
| [Architecture](/architecture) | Components, persistence, snapshots, scheduling, and secret boundaries |
| [Provider contract](/code-host-provider-spec) | GitLab/GitHub identity, adapters, webhooks, and approval consumption |

## Operations and project history

| Reference | Covers |
| --- | --- |
| [Configuration](/deployment/configuration) | Environment variables and server limits |
| [Operations runbook](/operations) | Backup, restore, incident actions, retention, and release checks |
| [Decision log](/decisions) | Accepted architectural choices and normative deltas |
| [Implementation plan](/IMPLEMENTATION_PLAN) | Milestones, delivery status, and completion gates |
| [Acceptance verification](/acceptance) | Automated evidence and environment-dependent checks |

## Sources of truth

When two documents disagree, use this order:

1. `backend/schemas/workflow.py` and `backend/engine/validation.py` for the accepted workflow shape and semantic validation.
2. `docs/code-host-provider-spec.md` for provider-neutral behavior that supersedes GitLab-only wording.
3. `workflow_orchestration_engine_spec.md` for normative product behavior.
4. Task-oriented documentation for explanation and examples.

Please open a documentation issue or use the page's **Edit this page** link when you find drift.
