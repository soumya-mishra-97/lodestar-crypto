import { describe, expect, it } from "vitest";
import type { RunEvent } from "@/api/types";
import { buildTimeline, stepLayout, TRADE_ENGINES, TRADE_SKILLS } from "./pipeline";
import { ladderScale } from "./trading";

const ev = (seq: number, step: string, status: string, type: RunEvent["type"] = "step"): RunEvent => ({
  run_id: "r",
  seq,
  ts: "2026-11-03T00:00:00Z",
  step,
  type,
  status,
  payload: {},
});

describe("trade-plan timeline", () => {
  it("lays out five parallel skills, then the engines in order", () => {
    const t = buildTimeline([], "trade_plan");
    expect(t.steps.map((s) => s.step)).toEqual(["data", ...TRADE_SKILLS, ...TRADE_ENGINES, "report_writer", "verifier", "human_approval"]);
    const layout = stepLayout("trade_plan");
    expect(layout.parallel).toHaveLength(5);
    expect(layout.after.slice(0, 4)).toEqual([...TRADE_ENGINES]);
    expect(stepLayout().parallel).toEqual(["technical", "fundamental", "sentiment", "risk"]);
  });

  it("folds events for trade steps and keeps the analysis order by default", () => {
    const t = buildTimeline([ev(1, "timing_agent", "running"), ev(2, "timing_agent", "completed"), ev(3, "backtester", "running")], "trade_plan");
    const by = new Map(t.steps.map((s) => [s.step, s.state]));
    expect(by.get("timing_agent")).toBe("completed");
    expect(by.get("backtester")).toBe("running");
    expect(by.get("liquidity_checker")).toBe("pending");
    expect(buildTimeline([]).steps.map((s) => s.step)).toContain("portfolio");
  });
});

describe("ladderScale", () => {
  it("keeps every level inside the track in price order", () => {
    const x = ladderScale([90, 100, 104, 120]);
    expect(x(90)).toBeGreaterThan(0);
    expect(x(120)).toBeLessThan(100);
    expect(x(90)).toBeLessThan(x(100));
    expect(x(104)).toBeLessThan(x(120));
    expect(x(1_000)).toBe(100);
  });
});
