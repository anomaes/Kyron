import { describe, expect, it } from "vitest";
import type { PiActivityEvent } from "../types";
import { buildPiTranscript } from "./PiActivityPanel";

describe("Pi activity transcript", () => {
  it("keeps usage visible for a tool-only assistant turn", () => {
    const usage = {
      input: 100,
      output: 20,
      cacheRead: 50,
      cacheWrite: 0,
      totalTokens: 170,
    };
    const events: PiActivityEvent[] = [{
      event_index: 4,
      pi_event_type: "message_end",
      kind: "assistant_end",
      text: "",
      thinking: "",
      stop_reason: "toolUse",
      usage,
    }];

    const transcript = buildPiTranscript(events);

    expect(transcript).toHaveLength(1);
    const item = transcript[0];
    expect(item?.kind).toBe("assistant");
    if (!item || item.kind !== "assistant") throw new Error("Expected assistant usage");
    expect(item.usage).toEqual(usage);
    expect(item.open).toBe(false);
  });
});
