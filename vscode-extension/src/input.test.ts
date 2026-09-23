import assert from "node:assert/strict";
import test from "node:test";

import { positiveIntegerValidation, validateWorkflowInput } from "./input";
import type { WorkflowInput } from "./types";

function input(overrides: Partial<WorkflowInput> = {}): WorkflowInput {
  return { type: "string", required: false, ...overrides };
}

test("validateWorkflowInput enforces required, integer, and number inputs", () => {
  assert.equal(validateWorkflowInput("", input({ required: true })), "This input is required");
  assert.equal(validateWorkflowInput("", input({ required: true, default: "fallback" })), undefined);
  assert.equal(validateWorkflowInput("1.5", input({ type: "integer" })), "Enter an integer");
  assert.equal(validateWorkflowInput("-12", input({ type: "integer" })), undefined);
  assert.equal(validateWorkflowInput("nope", input({ type: "number" })), "Enter a number");
  assert.equal(validateWorkflowInput("1.25", input({ type: "number" })), undefined);
});

test("positiveIntegerValidation accepts positive request numbers only", () => {
  assert.equal(positiveIntegerValidation("42"), undefined);
  assert.equal(positiveIntegerValidation("0"), "Enter a positive integer");
  assert.equal(positiveIntegerValidation("-1"), "Enter a positive integer");
});
