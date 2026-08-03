type GateAction = "feedback" | "approval" | "override";

type GateResponseControlsProps = {
  feedback: string;
  canControl: boolean;
  canOverride: boolean;
  isBusy: boolean;
  pendingAction: GateAction | null;
  onFeedbackChange: (value: string) => void;
  onSubmitFeedback: () => void;
  onApprove: () => void;
  onOverride: () => void;
};

function actionLabel(action: GateAction, pending: boolean): string {
  if (!pending) {
    return action === "feedback"
      ? "Send feedback"
      : action === "approval"
        ? "Record approval"
        : "Override";
  }
  return action === "feedback"
    ? "Sending feedback…"
    : action === "approval"
      ? "Recording approval…"
      : "Applying override…";
}

export function GateResponseControls({
  feedback,
  canControl,
  canOverride,
  isBusy,
  pendingAction,
  onFeedbackChange,
  onSubmitFeedback,
  onApprove,
  onOverride,
}: GateResponseControlsProps) {
  if (!canControl && !canOverride) return null;

  return (
    <div className="feedback-controls" aria-busy={isBusy}>
      {canControl && (
        <textarea
          value={feedback}
          disabled={isBusy}
          onChange={(event) => onFeedbackChange(event.target.value)}
          placeholder="Describe what should be revised…"
          aria-label="Revision feedback"
        />
      )}
      <div className="feedback-action-row">
        {canControl && (
          <>
            <button
              type="button"
              className={`secondary ${pendingAction === "feedback" ? "is-pending" : ""}`}
              disabled={isBusy || !feedback.trim()}
              onClick={onSubmitFeedback}
            >
              {pendingAction === "feedback" && <span className="button-spinner" aria-hidden="true" />}
              {actionLabel("feedback", pendingAction === "feedback")}
            </button>
            <button
              type="button"
              className={pendingAction === "approval" ? "is-pending" : ""}
              disabled={isBusy}
              onClick={onApprove}
            >
              {pendingAction === "approval" && <span className="button-spinner" aria-hidden="true" />}
              {actionLabel("approval", pendingAction === "approval")}
            </button>
          </>
        )}
        {canOverride && (
          <button
            type="button"
            className={`danger ${pendingAction === "override" ? "is-pending" : ""}`}
            disabled={isBusy}
            onClick={onOverride}
          >
            {pendingAction === "override" && <span className="button-spinner" aria-hidden="true" />}
            {actionLabel("override", pendingAction === "override")}
          </button>
        )}
      </div>
    </div>
  );
}
