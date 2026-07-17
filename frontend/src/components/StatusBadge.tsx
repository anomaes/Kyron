const statusClass: Record<string, string> = {
  QUEUED: "neutral",
  RUNNING: "active",
  RESUMING: "purple",
  AWAITING_FEEDBACK: "waiting",
  COMPLETED: "success",
  SUCCESS: "success",
  FAILED: "danger",
  CANCELLED: "neutral",
  INTERRUPTED: "purple",
  SKIPPED: "waiting",
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${statusClass[status] ?? "neutral"}`}>{status.replaceAll("_", " ")}</span>;
}
