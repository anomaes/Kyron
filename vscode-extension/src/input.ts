import type { WorkflowInput } from "./types";

export function validateWorkflowInput(value: string, input: WorkflowInput): string | undefined {
  if (!value.trim()) {
    return input.required && input.default == null ? "This input is required" : undefined;
  }
  if (input.type === "integer" && !/^-?\d+$/.test(value.trim())) {
    return "Enter an integer";
  }
  if (input.type === "number" && !Number.isFinite(Number(value))) {
    return "Enter a number";
  }
  return undefined;
}

export function positiveIntegerValidation(value: string): string | undefined {
  return /^[1-9]\d*$/.test(value.trim()) ? undefined : "Enter a positive integer";
}
