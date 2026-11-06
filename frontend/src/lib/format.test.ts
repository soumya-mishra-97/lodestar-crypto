import { describe, expect, it } from "vitest";
import { duration, evidenceValue, label, pct, relativeTime, usd } from "./format";

describe("format", () => {
  it("keeps significant digits for sub-dollar prices", () => {
    expect(usd(0.08781234)).toBe("$0.08781");
    expect(usd(71250)).toBe("$71,250.00");
    expect(usd(1.23e9, { compact: true })).toBe("$1.23B");
    expect(usd(null)).toBe("—");
  });

  it("signs percentages", () => {
    expect(pct(4.21)).toBe("+4.2%");
    expect(pct(-0.04, 2)).toBe("-0.04%");
  });

  it("formats evidence by unit", () => {
    expect(evidenceValue({ value: "very_high", unit: "text" })).toBe("very high");
    expect(evidenceValue({ value: 55.123, unit: "index" })).toBe("55.1");
    expect(evidenceValue({ value: 365, unit: "days" })).toBe("365 days");
    expect(evidenceValue({ value: 0.42, unit: "ratio" })).toBe("0.42");
  });

  it("formats times and labels", () => {
    const now = new Date("2026-11-03T12:00:00Z");
    expect(relativeTime("2026-11-03T11:59:30Z", now)).toBe("just now");
    expect(relativeTime("2026-11-03T09:00:00Z", now)).toBe("3h ago");
    expect(duration(350)).toBe("350 ms");
    expect(duration(1500)).toBe("1.5 s");
    expect(label("awaiting_approval")).toBe("Awaiting approval");
  });
});
