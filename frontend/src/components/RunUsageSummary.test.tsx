import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { PiUsage, RunUsage } from "../types";
import { RunUsageSummary } from "./RunUsageSummary";

function piUsage(totalTokens: number, requestCount: number, cost: number): PiUsage {
  return {
    input: totalTokens - 30,
    output: 20,
    cacheRead: 10,
    cacheWrite: 0,
    totalTokens,
    cost: {
      input: 0,
      output: cost,
      cacheRead: 0,
      cacheWrite: 0,
      total: cost,
    },
    requestCount,
  };
}

function runUsage(): RunUsage {
  const first = piUsage(120_000, 2, 1.25);
  const retry = piUsage(64_000, 1, 0.59);
  return {
    usage: piUsage(184_000, 3, 1.84),
    prompt_node_count: 1,
    attempt_count: 2,
    nodes: [{
      node_execution_id: "node-1",
      node_id: "implement",
      node_path: "root/implement",
      status: "SUCCESS",
      usage: piUsage(184_000, 3, 1.84),
      attempts: [
        { attempt_id: "attempt-1", attempt_number: 1, status: "FAILED", usage: retry, source: "persisted" },
        { attempt_id: "attempt-2", attempt_number: 2, status: "SUCCESS", usage: first, source: "persisted" },
      ],
    }],
  };
}

describe("run usage summary", () => {
  it("shows the aggregate and expands an all-attempt breakdown", async () => {
    const user = userEvent.setup();
    const { container } = render(<div className="run-summary"><RunUsageSummary data={runUsage()} /></div>);

    const summary = container.querySelector("summary");
    expect(summary).toHaveTextContent("184K tokens");
    expect(screen.getByText("3 model calls · $1.84")).toBeVisible();

    const details = container.querySelector("details");
    expect(details).not.toHaveAttribute("open");
    if (!summary) throw new Error("Usage summary was not rendered");
    await user.click(summary);
    expect(details).toHaveAttribute("open");
    expect(screen.getByText("All prompt-node attempts, including retries")).toBeVisible();
    expect(screen.getByText("Attempt 1", { exact: false })).toBeVisible();
    expect(screen.getAllByText("FAILED").length).toBeGreaterThan(0);
  });

  it("distinguishes a run with no recorded Pi calls", () => {
    const empty = runUsage();
    empty.usage = piUsage(0, 0, 0);
    render(<RunUsageSummary data={empty} />);

    expect(screen.getByText("0 tokens")).toBeVisible();
    expect(screen.getByText("No Pi model calls recorded")).toBeVisible();
  });
});
