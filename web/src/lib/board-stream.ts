// One SSE connection per tab (U4, U5): fetch + createSseParser instead of EventSource, so 429
// `Retry-After`, 503, the empty 200 of a lost slot race and the 15 s heartbeat comments are all
// visible. Reconnects with jittered exponential backoff, aborts a silent stream (watchdog), and
// closes while the tab stays hidden.
import { apiUrl, parseRetryAfter } from "./api";
import { createSseParser, type SseEvent } from "./sse";

export type StreamStatus = "connecting" | "open" | "reconnecting" | "stopped";

export interface BoardStreamOptions {
  url?: string /* "/api/stream" */;
  onEvent(e: SseEvent): void;
  onStatus?(s: StreamStatus): void;
  fetchImpl?: typeof fetch;
  initialBackoffMs?: number /* 1000 */;
  maxBackoffMs?: number /* 30000 */;
  watchdogMs?: number /* 45000 */;
  hiddenCloseMs?: number /* 60000 */;
  random?: () => number;
}

type Timer = ReturnType<typeof setTimeout>;

export class BoardStreamClient {
  private readonly url: string;
  private readonly onEvent: (e: SseEvent) => void;
  private readonly onStatus: ((s: StreamStatus) => void) | undefined;
  private readonly fetchImpl: typeof fetch;
  private readonly initialBackoffMs: number;
  private readonly maxBackoffMs: number;
  private readonly watchdogMs: number;
  private readonly hiddenCloseMs: number;
  private readonly random: () => number;

  private _status: StreamStatus = "stopped";
  private running = false;
  /** Closed because the tab stayed hidden: waits for `visible`, not for a timer. */
  private paused = false;
  /** n in the backoff formula: failed attempts since the last `board` event. */
  private attempt = 0;
  /** Bumped per connection; a finished or aborted loop whose generation is stale does nothing. */
  private generation = 0;
  private controller: AbortController | null = null;
  private retryTimer: Timer | null = null;
  private watchdogTimer: Timer | null = null;
  private hiddenTimer: Timer | null = null;

  constructor(o: BoardStreamOptions) {
    this.url = o.url ?? "/api/stream";
    this.onEvent = o.onEvent;
    this.onStatus = o.onStatus;
    this.fetchImpl = o.fetchImpl ?? ((input, init) => fetch(input, init)); // late-bound: test doubles patch fetch
    this.initialBackoffMs = o.initialBackoffMs ?? 1000;
    this.maxBackoffMs = o.maxBackoffMs ?? 30_000;
    this.watchdogMs = o.watchdogMs ?? 45_000;
    this.hiddenCloseMs = o.hiddenCloseMs ?? 60_000;
    this.random = o.random ?? Math.random;
  }

  get status(): StreamStatus {
    return this._status;
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.paused = false;
    this.attempt = 0;
    document.addEventListener("visibilitychange", this.onVisibility);
    this.armHiddenTimer();
    this.connect("connecting");
  }

  /** Reconnect now with a fresh backoff (after login/logout: the stream keeps its connect-time auth level). */
  restart(): void {
    if (!this.running) {
      this.start();
      return;
    }
    this.paused = false;
    this.attempt = 0;
    this.armHiddenTimer();
    this.connect("connecting");
  }

  stop(): void {
    if (!this.running) return;
    this.running = false;
    this.paused = false;
    document.removeEventListener("visibilitychange", this.onVisibility);
    this.clearTimer("hiddenTimer");
    this.disconnect();
    this.setStatus("stopped");
  }

  // ---- connection ----------------------------------------------------------------------

  private connect(status: StreamStatus): void {
    this.disconnect();
    this.setStatus(status);
    const gen = ++this.generation;
    const ctrl = new AbortController();
    this.controller = ctrl;
    void this.run(gen, ctrl);
  }

  /** Aborts the current request and cancels pending timers; the old loop sees a stale generation. */
  private disconnect(): void {
    this.generation++;
    this.clearTimer("retryTimer");
    this.clearTimer("watchdogTimer");
    this.controller?.abort();
    this.controller = null;
  }

  private async run(gen: number, ctrl: AbortController): Promise<void> {
    let retryAfterMs = 0;
    try {
      this.armWatchdog(ctrl); // also covers a server that accepts the request and never answers
      const res = await this.fetchImpl(apiUrl(this.url), {
        signal: ctrl.signal,
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "text/event-stream" },
      });
      if (gen !== this.generation) return;
      const type = res.headers.get("Content-Type") ?? "";
      if (res.status === 200 && type.startsWith("text/event-stream") && res.body) {
        await this.read(gen, ctrl, res.body); // "open" on the first byte, see read()
      } else {
        if (res.status === 429) retryAfterMs = (parseRetryAfter(res.headers.get("Retry-After")) ?? 0) * 1000;
        res.body?.cancel().catch(() => {});
      }
    } catch {
      // network error, or the watchdog / hidden timer aborted the request: reconnect below
    }
    if (gen !== this.generation || !this.running) return;
    this.clearTimer("watchdogTimer");
    this.controller = null;
    this.setStatus("reconnecting");
    if (this.paused) return; // hidden: `visible` reconnects
    this.scheduleRetry(retryAfterMs);
  }

  private async read(gen: number, ctrl: AbortController, body: ReadableStream<Uint8Array>): Promise<void> {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    const feed = createSseParser((e) => {
      if (e.event === "board") this.attempt = 0;
      this.onEvent(e);
    });
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (gen !== this.generation) return;
        if (done) break;
        // the stream is open once something arrives: an empty 200 (the server lost the race for the
        // last slot) has headers only and must not count as a reconnect
        if (value.byteLength > 0) this.setStatus("open");
        this.armWatchdog(ctrl); // any byte counts, heartbeat comments included
        feed(decoder.decode(value, { stream: true }));
      }
    } finally {
      reader.releaseLock();
    }
  }

  private scheduleRetry(minMs: number): void {
    const base = Math.min(this.maxBackoffMs, this.initialBackoffMs * 2 ** this.attempt);
    const delay = Math.max(minMs, base * (0.8 + 0.4 * this.random()));
    this.attempt++;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      this.connect("reconnecting");
    }, delay);
  }

  private armWatchdog(ctrl: AbortController): void {
    this.clearTimer("watchdogTimer");
    this.watchdogTimer = setTimeout(() => ctrl.abort(), this.watchdogMs);
  }

  // ---- visibility ----------------------------------------------------------------------

  private readonly onVisibility = (): void => {
    if (!this.running) return;
    if (document.visibilityState === "hidden") {
      this.armHiddenTimer();
      return;
    }
    this.clearTimer("hiddenTimer");
    if (this.paused) {
      this.paused = false;
      this.attempt = 0;
      this.connect("reconnecting");
    }
  };

  private armHiddenTimer(): void {
    this.clearTimer("hiddenTimer");
    if (document.visibilityState !== "hidden") return;
    this.hiddenTimer = setTimeout(() => {
      this.hiddenTimer = null;
      this.paused = true;
      this.disconnect();
      this.setStatus("reconnecting");
    }, this.hiddenCloseMs);
  }

  // ---- helpers -------------------------------------------------------------------------

  private clearTimer(name: "retryTimer" | "watchdogTimer" | "hiddenTimer"): void {
    const t = this[name];
    if (t !== null) clearTimeout(t);
    this[name] = null;
  }

  private setStatus(s: StreamStatus): void {
    if (s === this._status) return;
    this._status = s;
    this.onStatus?.(s);
  }
}
