import { describe, expect, it } from "vitest";
import { SseParser } from "./sse";

describe("SseParser", () => {
  it("parses messages split across chunks and skips heartbeats", () => {
    const p = new SseParser();
    expect(p.push("retry: 3000\n\nid: 1\nevent: st")).toEqual([]);
    expect(p.push('ep\ndata: {"seq":1}\n\n: ping\n\n')).toEqual([{ id: "1", event: "step", data: '{"seq":1}' }]);
    expect(p.push("event: end\ndata: {}\n\n")).toEqual([{ id: null, event: "end", data: "{}" }]);
  });

  it("handles CRLF and multi-line data", () => {
    const p = new SseParser();
    expect(p.push("id: 7\r\ndata: a\r\ndata: b\r\n\r\n")).toEqual([{ id: "7", event: "message", data: "a\nb" }]);
  });
});
