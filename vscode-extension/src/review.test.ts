import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { currentReviewForUser, reviewRequiredForUser } from "./review";
import type { Gate, GateDecision, RunGraph, User } from "./types";

const user: User = {
  id: "user-id",
  email: "alice@example.com",
  display_name: "Alice",
  provider: "github",
  provider_user_id: "7",
  provider_username: "alice",
};

function gate(
  id: string,
  users: Array<{ provider: "gitlab" | "github"; provider_user_id: string }>,
  quorum = 1,
): Gate {
  return {
    id,
    status: "OPEN",
    checkpoint_commit_sha: "a".repeat(40),
    change_request_id: `${id}-change`,
    policy_snapshot: {
      name: "Review",
      distinct_approvers_across_requirements: true,
    },
    eligible_snapshot: {
      requirements: [{ key: "review", name: "Review", quorum, users }],
    },
  };
}

function approval(gateId: string, providerUserId: string, superseded = false): GateDecision {
  return {
    gate_instance_id: gateId,
    event_type: "approval",
    superseded,
    actor_snapshot: { provider: "github", provider_user_id: providerUserId },
    requirement_keys: ["review"],
  };
}

describe("reviewRequiredForUser", () => {
  it("requires review only from a snapshotted eligible identity", () => {
    const open = gate("gate", [{ provider: "github", provider_user_id: "7" }]);
    assert.equal(reviewRequiredForUser(open, [], user), true);
    assert.equal(
      reviewRequiredForUser(
        gate("other", [{ provider: "github", provider_user_id: "8" }]),
        [],
        user,
      ),
      false,
    );
  });

  it("does not request another review after the user already approved", () => {
    const open = gate("gate", [
      { provider: "github", provider_user_id: "7" },
      { provider: "github", provider_user_id: "8" },
    ], 2);
    assert.equal(reviewRequiredForUser(open, [approval("gate", "7")], user), false);
  });

  it("ignores superseded and unrelated-gate approvals", () => {
    const open = gate("gate", [{ provider: "github", provider_user_id: "7" }]);
    assert.equal(reviewRequiredForUser(open, [approval("gate", "7", true)], user), true);
    assert.equal(reviewRequiredForUser(open, [approval("other", "7")], user), true);
  });

  it("recognizes when another approval already filled the only useful slot", () => {
    const open = gate("gate", [
      { provider: "github", provider_user_id: "7" },
      { provider: "github", provider_user_id: "8" },
    ]);
    assert.equal(reviewRequiredForUser(open, [approval("gate", "8")], user), false);
  });

  it("handles policies that let one approval satisfy several requirements", () => {
    const open = gate("gate", [{ provider: "github", provider_user_id: "7" }]);
    open.policy_snapshot.distinct_approvers_across_requirements = false;
    open.eligible_snapshot.requirements = [
      {
        key: "security",
        name: "Security",
        quorum: 1,
        users: [{ provider: "github", provider_user_id: "8" }],
      },
      {
        key: "release",
        name: "Release",
        quorum: 1,
        users: [{ provider: "github", provider_user_id: "7" }],
      },
    ];
    const securityApproval = approval("gate", "8");
    securityApproval.requirement_keys = ["security"];
    assert.equal(reviewRequiredForUser(open, [securityApproval], user), true);
  });
});

describe("currentReviewForUser", () => {
  it("selects the user's actionable gate when parallel gates are open", () => {
    const other = gate("other", [{ provider: "github", provider_user_id: "8" }]);
    const mine = gate("mine", [{ provider: "github", provider_user_id: "7" }]);
    const graph: RunGraph = {
      gates: [mine, other],
      gate_decisions: [],
      change_requests: [
        { id: "mine-change", kind: "pull_request", provider: "github", provider_number: 1, url: "https://example.test/1", status: "OPEN" },
        { id: "other-change", kind: "pull_request", provider: "github", provider_number: 2, url: "https://example.test/2", status: "OPEN" },
      ],
    };
    const review = currentReviewForUser(graph, user);
    assert.equal(review.reviewRequested, true);
    assert.equal(review.gate?.id, "mine");
    assert.equal(review.changeRequest?.id, "mine-change");
  });
});
