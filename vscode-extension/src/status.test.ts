import assert from "node:assert/strict";
import test from "node:test";

import { prettyStatus, runContextValue, statusIconSpec } from "./status";

test("run status presentation distinguishes actionable states", () => {
  assert.equal(prettyStatus("AWAITING_FEEDBACK"), "awaiting feedback");
  assert.equal(runContextValue("AWAITING_FEEDBACK"), "kyronRunAwaitingFeedback");
  assert.equal(runContextValue("RUNNING"), "kyronRunActive");
  assert.equal(runContextValue("FAILED"), "kyronRunResumable");
  assert.equal(runContextValue("COMPLETED"), "kyronRun");
});

test("run status icons use terminal and unknown-state treatments", () => {
  assert.deepEqual(statusIconSpec("COMPLETED"), { id: "pass", color: "passed" });
  assert.deepEqual(statusIconSpec("FAILED"), { id: "error", color: "failed" });
  assert.deepEqual(statusIconSpec("RUNNING"), { id: "sync~spin" });
  assert.deepEqual(statusIconSpec("FUTURE_STATUS"), { id: "question" });
});
