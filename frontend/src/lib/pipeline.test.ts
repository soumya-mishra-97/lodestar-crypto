import { describe, expect, it } from "vitest";
import type { RunEvent } from "@/api/types";
import { buildTimeline, mergeEvents } from "./pipeline";

let seq = 0;
const ev = (step: string, type: RunEvent["type"], status: string | null, payload: Record<string, unknown> = {}): RunEvent => ({
  run_id: "r",
  seq: ++seq,
  ts: "2026-11-03T12:00:00Z",
  step,
  type,
  status,
  payload,
});

describe("buildTimeline", () => {
  it("folds events into steps, attempts, tool calls and run status", () => {
    seq = 0;
    const events = [
      ev("run", "run", "running"),
      ev("data", "step", "running", { inputs: { asset: "POL" } }),
      ev("data", "step", "completed", { outputs: { history_days: 365 }, evidence_ids: ["DAT-01"], duration_ms: 12 }),
      ev("technical", "step", "running"),
      ev("technical", "tool_call", "ok", { tool: "compute_indicator", react_step: 1, max_steps: 6 }),
      ev("report_writer", "step", "running", { attempt: 1 }),
      ev("report_writer", "step", "completed", { attempt: 1 }),
      ev("verifier", "step", "running", { attempt: 1 }),
      ev("verifier", "step", "completed", { attempt: 1, outputs: { passed: false, findings: ["x"] } }),
      ev("verifier", "note", null, { message: "repair loop 1 of 2" }),
      ev("report_writer", "step", "running", { attempt: 2 }),
      ev("report_writer", "step", "completed", { attempt: 2 }),
      ev("human_approval", "step", "waiting", { message: "waiting" }),
      ev("run", "run", "awaiting_approval"),
    ];
    const t = buildTimeline([...events].reverse()); // order-independent
    const step = (name: string) => {
      const found = t.steps.find((s) => s.step === name);
      if (!found) throw new Error(`missing step ${name}`);
      return found;
    };
    expect(t.runStatus).toBe("awaiting_approval");
    expect(t.lastSeq).toBe(events.length);
    expect(step("data").state).toBe("completed");
    expect(step("data").attempts[0]?.evidenceIds).toEqual(["DAT-01"]);
    expect(step("technical").state).toBe("running");
    expect(step("technical").toolCalls).toHaveLength(1);
    expect(step("report_writer").attempts.map((a) => a.attempt)).toEqual([1, 2]);
    expect(step("verifier").notes).toHaveLength(1);
    expect(step("human_approval").state).toBe("waiting");
    expect(step("fundamental").state).toBe("pending");
    expect(t.steps.some((s) => s.step === "fail_closed")).toBe(false);
  });

  it("merges live events by sequence without duplicates", () => {
    seq = 0;
    const a = ev("run", "run", "queued");
    const b = ev("run", "run", "running");
    expect(mergeEvents([a], [b, a]).map((e) => e.seq)).toEqual([1, 2]);
  });
});
