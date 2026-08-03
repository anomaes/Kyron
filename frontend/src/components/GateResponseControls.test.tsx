import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GateResponseControls } from "./GateResponseControls";

const defaults = {
  feedback: "Please update the docs",
  canControl: true,
  canOverride: false,
  isBusy: false,
  pendingAction: null,
  onFeedbackChange: vi.fn(),
  onSubmitFeedback: vi.fn(),
  onApprove: vi.fn(),
  onOverride: vi.fn(),
} as const;

describe("GateResponseControls", () => {
  it("immediately exposes the pending approval state", () => {
    render(<GateResponseControls {...defaults} isBusy pendingAction="approval" />);

    expect(screen.getByRole("button", { name: "Recording approval…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send feedback" })).toBeDisabled();
    expect(screen.getByLabelText("Revision feedback")).toBeDisabled();
  });

  it("sends the selected response", async () => {
    const onApprove = vi.fn();
    const onSubmitFeedback = vi.fn();
    const { container } = render(
      <GateResponseControls
        {...defaults}
        onApprove={onApprove}
        onSubmitFeedback={onSubmitFeedback}
      />,
    );
    const controls = within(container);

    await userEvent.click(controls.getByRole("button", { name: "Record approval" }));
    await userEvent.click(controls.getByRole("button", { name: "Send feedback" }));

    expect(onApprove).toHaveBeenCalledOnce();
    expect(onSubmitFeedback).toHaveBeenCalledOnce();
  });
});
