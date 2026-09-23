export type StatusIconSpec = {
  id: string;
  color?: "passed" | "failed" | "warning";
};

export function prettyStatus(status: string): string {
  return status.toLowerCase().replaceAll("_", " ");
}

export function runContextValue(status: string): string {
  if (status === "AWAITING_FEEDBACK") return "kyronRunAwaitingFeedback";
  if (["QUEUED", "RUNNING", "RESUMING"].includes(status)) return "kyronRunActive";
  if (["FAILED", "INTERRUPTED", "CANCELLED"].includes(status)) return "kyronRunResumable";
  return "kyronRun";
}

export function statusIconSpec(status: string): StatusIconSpec {
  switch (status) {
    case "COMPLETED":
      return { id: "pass", color: "passed" };
    case "FAILED":
      return { id: "error", color: "failed" };
    case "CANCELLED":
    case "INTERRUPTED":
      return { id: "circle-slash" };
    case "AWAITING_FEEDBACK":
      return { id: "comment-discussion", color: "warning" };
    case "QUEUED":
      return { id: "watch" };
    case "RUNNING":
    case "RESUMING":
      return { id: "sync~spin" };
    default:
      return { id: "question" };
  }
}
