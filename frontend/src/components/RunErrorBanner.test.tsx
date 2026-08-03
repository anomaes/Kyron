import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RunErrorBanner } from "./RunErrorBanner";

describe("run error banner", () => {
  it("shows a persisted workflow crash prominently", () => {
    render(<RunErrorBanner
      errorType="ENGINE_CRASH"
      errorMessage="Workflow worker stopped unexpectedly (IntegrityError); inspect backend logs"
    />);

    expect(screen.getByRole("alert")).toHaveTextContent("ENGINE CRASH");
    expect(screen.getByRole("alert")).toHaveTextContent("IntegrityError");
  });

  it("does not render without a persisted error", () => {
    const { container } = render(<RunErrorBanner errorType={null} errorMessage={null} />);

    expect(container).toBeEmptyDOMElement();
  });
});
