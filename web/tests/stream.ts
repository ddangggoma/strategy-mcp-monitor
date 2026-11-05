// Fake `fetch` for BoardStreamClient tests (no MSW: tests drive timers and byte timing directly).
// Each scripted response is a factory that receives the request's AbortSignal, so an open stream
// errors when the client aborts it, just like a real fetch body.
import { vi } from "vitest";

export type FakeResponse = (signal: AbortSignal) => Response;

const SSE_HEADERS = { "Content-Type": "text/event-stream; charset=utf-8" };

function abortable(signal: AbortSignal, start: (c: ReadableStreamDefaultController<Uint8Array>) => void) {
  return new ReadableStream<Uint8Array>({
    start(c) {
      signal.addEventListener("abort", () => c.error(signal.reason), { once: true });
      start(c);
    },
  });
}

/** 200 text/event-stream that ends at once (the server lost the race for the last slot). */
export function emptyStream(): FakeResponse {
  return () => new Response("", { status: 200, headers: SSE_HEADERS });
}

/** 200 text/event-stream that sends `text`, then ends (or stays open with `keepOpen`). */
export function streamWith(text: string, opts: { keepOpen?: boolean } = {}): FakeResponse {
  return (signal) =>
    new Response(
      abortable(signal, (c) => {
        c.enqueue(new TextEncoder().encode(text));
        if (!opts.keepOpen) c.close();
      }),
      { status: 200, headers: SSE_HEADERS },
    );
}

/** 200 text/event-stream that stays open without a byte until aborted; `push` writes into it. */
export function openStream(): FakeResponse & { push(text: string): void } {
  let ctrl: ReadableStreamDefaultController<Uint8Array> | null = null;
  const make = ((signal: AbortSignal) =>
    new Response(
      abortable(signal, (c) => {
        ctrl = c;
      }),
      { status: 200, headers: SSE_HEADERS },
    )) as FakeResponse & { push(text: string): void };
  make.push = (text) => ctrl?.enqueue(new TextEncoder().encode(text));
  return make;
}

/** A plain non-stream response (429, 503, 401…). */
export function status(code: number, headers: Record<string, string> = {}): FakeResponse {
  return () => new Response(JSON.stringify({ error: "x" }), { status: code, headers });
}

/** Rejects like fetch does when the server is unreachable. */
export function networkError(): FakeResponse {
  return () => {
    throw new TypeError("fetch failed");
  };
}

/**
 * `vi.fn` fetch that answers the scripted responses in order; after the script runs out every
 * call gets a silent open stream. `signalOf(n)` is the AbortSignal of the n-th call (0-based).
 */
export function fakeFetch(responses: FakeResponse[]) {
  const queue = [...responses];
  const f = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const signal = init?.signal ?? new AbortController().signal;
    const next = queue.shift() ?? openStream();
    return next(signal);
  });
  return Object.assign(f, {
    signalOf(n: number): AbortSignal {
      const init = f.mock.calls[n]?.[1];
      if (!init?.signal) throw new Error(`fetch call ${n} has no signal`);
      return init.signal;
    },
  });
}
