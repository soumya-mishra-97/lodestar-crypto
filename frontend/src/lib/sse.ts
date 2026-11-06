/**
 * Server-Sent Events over fetch (EventSource cannot send an Authorization header).
 * Tracks the last event id and reconnects with Last-Event-ID after a dropped connection.
 */

export interface SseMessage {
  id: string | null;
  event: string;
  data: string;
}

/** Incremental parser: feed text chunks, get complete messages back. */
export class SseParser {
  private buffer = "";

  push(chunk: string): SseMessage[] {
    this.buffer += chunk.replace(/\r\n/g, "\n");
    const out: SseMessage[] = [];
    let index = this.buffer.indexOf("\n\n");
    while (index !== -1) {
      const block = this.buffer.slice(0, index);
      this.buffer = this.buffer.slice(index + 2);
      const message = parseBlock(block);
      if (message) out.push(message);
      index = this.buffer.indexOf("\n\n");
    }
    return out;
  }
}

function parseBlock(block: string): SseMessage | null {
  let id: string | null = null;
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue; // comment / heartbeat
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "id") id = value;
    else if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length || event !== "message" ? { id, event, data: data.join("\n") } : null;
}

export interface StreamOptions {
  headers?: () => HeadersInit;
  lastEventId?: number;
  signal: AbortSignal;
  onMessage: (message: SseMessage) => void;
  onEnd: () => void;
  retryMs?: number;
}

/** Follow a stream until the server sends `event: end` or the signal aborts. */
export async function followStream(url: string, opts: StreamOptions): Promise<void> {
  let last = opts.lastEventId ?? 0;
  while (!opts.signal.aborted) {
    try {
      const res = await fetch(url, {
        headers: { Accept: "text/event-stream", "Last-Event-ID": String(last), ...(opts.headers?.() ?? {}) },
        signal: opts.signal,
        credentials: "same-origin",
      });
      if (!res.ok || !res.body) throw new Error(`stream failed (${res.status})`);
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      const parser = new SseParser();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        for (const message of parser.push(value)) {
          if (message.event === "end") {
            opts.onEnd();
            return;
          }
          if (message.id) last = Number(message.id);
          opts.onMessage(message);
        }
      }
    } catch (error) {
      if (opts.signal.aborted) return;
      console.warn("event stream interrupted, reconnecting", error);
    }
    await new Promise((resolve) => setTimeout(resolve, opts.retryMs ?? 3000));
  }
}
