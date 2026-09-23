import type { ChangeRequest, Gate, GateDecision, RunGraph, User } from "./types";

export type CurrentReview = {
  gate?: Gate;
  changeRequest?: ChangeRequest;
  reviewRequested: boolean;
};

function identity(provider: string | undefined, providerUserId: string | undefined): string {
  return `${provider ?? ""}:${providerUserId ?? ""}`;
}

function approvalDecisions(gate: Gate, decisions: readonly GateDecision[]): GateDecision[] {
  return decisions.filter(
    (decision) =>
      decision.gate_instance_id === gate.id &&
      decision.event_type === "approval" &&
      !decision.superseded,
  );
}

function maximumMatch(slots: readonly string[], eligible: ReadonlyMap<string, ReadonlySet<string>>): number {
  const actorToSlot = new Map<string, string>();

  const assign = (slot: string, seen: Set<string>): boolean => {
    for (const actor of eligible.get(slot) ?? []) {
      if (seen.has(actor)) continue;
      seen.add(actor);
      const previous = actorToSlot.get(actor);
      if (!previous || assign(previous, seen)) {
        actorToSlot.set(actor, slot);
        return true;
      }
    }
    return false;
  };

  let matched = 0;
  for (const slot of slots) {
    if (assign(slot, new Set())) matched += 1;
  }
  return matched;
}

function distinctApprovalProgress(gate: Gate, approved: ReadonlySet<string>): number {
  const slots: string[] = [];
  const eligible = new Map<string, ReadonlySet<string>>();
  for (const requirement of gate.eligible_snapshot.requirements) {
    const actors = new Set(
      requirement.users.map((actor) => identity(actor.provider, actor.provider_user_id)),
    );
    for (let index = 0; index < requirement.quorum; index += 1) {
      const slot = `${requirement.key}:${index}`;
      slots.push(slot);
      eligible.set(slot, new Set([...actors].filter((actor) => approved.has(actor))));
    }
  }
  return maximumMatch(slots, eligible);
}

function sharedApprovalProgress(gate: Gate, decisions: readonly GateDecision[]): number {
  return gate.eligible_snapshot.requirements.reduce((total, requirement) => {
    const actors = new Set(
      decisions
        .filter((decision) => decision.requirement_keys.includes(requirement.key))
        .map((decision) =>
          identity(decision.actor_snapshot.provider, decision.actor_snapshot.provider_user_id),
        ),
    );
    return total + Math.min(requirement.quorum, actors.size);
  }, 0);
}

export function reviewRequiredForUser(
  gate: Gate,
  decisions: readonly GateDecision[],
  user: User | undefined,
): boolean {
  if (!user || gate.status !== "OPEN") return false;
  const userIdentity = identity(user.provider, user.provider_user_id);
  const requirementKeys = gate.eligible_snapshot.requirements
    .filter((requirement) =>
      requirement.users.some(
        (actor) => identity(actor.provider, actor.provider_user_id) === userIdentity,
      ),
    )
    .map((requirement) => requirement.key);
  if (requirementKeys.length === 0) return false;

  const approvals = approvalDecisions(gate, decisions);
  if (
    approvals.some(
      (decision) =>
        identity(decision.actor_snapshot.provider, decision.actor_snapshot.provider_user_id) ===
        userIdentity,
    )
  ) {
    return false;
  }

  const hypothetical: GateDecision = {
    gate_instance_id: gate.id,
    event_type: "approval",
    superseded: false,
    actor_snapshot: {
      provider: user.provider,
      provider_user_id: user.provider_user_id,
    },
    requirement_keys: requirementKeys,
  };
  if (gate.policy_snapshot.distinct_approvers_across_requirements !== false) {
    const approved = new Set(
      approvals.map((decision) =>
        identity(decision.actor_snapshot.provider, decision.actor_snapshot.provider_user_id),
      ),
    );
    const before = distinctApprovalProgress(gate, approved);
    approved.add(userIdentity);
    return distinctApprovalProgress(gate, approved) > before;
  }
  return sharedApprovalProgress(gate, [...approvals, hypothetical]) > sharedApprovalProgress(gate, approvals);
}

export function currentReviewForUser(graph: RunGraph, user: User | undefined): CurrentReview {
  const openGates = [...graph.gates].reverse().filter((gate) => gate.status === "OPEN");
  const requestedGate = openGates.find((gate) =>
    reviewRequiredForUser(gate, graph.gate_decisions, user),
  );
  const gate = requestedGate ?? openGates[0];
  const changeRequest = gate?.change_request_id
    ? graph.change_requests.find((candidate) => candidate.id === gate.change_request_id)
    : [...graph.change_requests].reverse().find((candidate) => candidate.status === "OPEN");
  return { gate, changeRequest, reviewRequested: Boolean(requestedGate) };
}
