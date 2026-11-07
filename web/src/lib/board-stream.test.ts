import { emptyStream, fakeFetch, networkError, openStream, status, streamWith } from "../../tests/stream";
import { BoardStreamClient, type StreamStatus } from "./board-stream";

const BOARD = 'event: board\ndata: {"now":"x","mcps":[]}\n\n';
const clients: BoardStreamClient[] = [];

function client(opts: Partial<ConstructorParameters<typeof BoardStreamClient>[0]> & { fetchImpl: typeof fetch }) {
  const c = new BoardStreamClient({ onEvent: vi.fn(), random: () => 0.5, ...opts });
  clients.push(c);
  return c;
}

let visibility: DocumentVisibilityState = "visible";

beforeEach(() => {
  vi.useFakeTimers();
  visibility = "visible";
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
});

afterEach(() => {
  for (const c of clients.splice(0)) c.stop();
  vi.useRealTimers();
  // back to jsdom's own getter on Document.prototype
  delete (document as { visibilityState?: unknown }).visibilityState;
});

function setVisibility(v: DocumentVisibilityState) {
  visibility = v;
  document.dispatchEvent(new Event("visibilitychange"));
}

it("reconnects after an empty 200 with backoff", async () => {
  const f = fakeFetch([emptyStream(), emptyStream(), streamWith(BOARD)]);
  const c = client({ fetchImpl: f });
  c.start();
  await vi.advanceTimersByTimeAsync(0);
  expect(f).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(999);
  expect(f).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(f).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(1999);
  expect(f).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(1);
  expect(f).toHaveBeenCalledTimes(3);
});

it("honors Retry-After on 429", async () => {
  const f = fakeFetch([status(429, { "Retry-After": "5" }), emptyStream()]);
  client({ fetchImpl: f }).start();
  await vi.advanceTimersByTimeAsync(4999);
  expect(f).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(f).toHaveBeenCalledTimes(2);
});

it("uses the backoff when it is longer than Retry-After", async () => {
  // three failures first: the fourth delay is 8000 ms, longer than Retry-After 5 s
  const f = fakeFetch([emptyStream(), emptyStream(), emptyStream(), status(429, { "Retry-After": "5" })]);
  client({ fetchImpl: f }).start();
  await vi.advanceTimersByTimeAsync(1000 + 2000 + 4000);
  expect(f).toHaveBeenCalledTimes(4);
  await vi.advanceTimersByTimeAsync(7999);
  expect(f).toHaveBeenCalledTimes(4);
  await vi.advanceTimersByTimeAsync(1);
  expect(f).toHaveBeenCalledTimes(5);
});

it("reconnects after 503, network errors and non-stream 200 with the same backoff", async () => {
  const notSse = () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
  const f = fakeFetch([status(503), networkError(), notSse]);
  client({ fetchImpl: f }).start();
  await vi.advanceTimersByTimeAsync(0);
  expect(f).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1000);
  expect(f).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(2000);
  expect(f).toHaveBeenCalledTimes(3);
  await vi.advanceTimersByTimeAsync(3999);
  expect(f).toHaveBeenCalledTimes(3);
  await vi.advanceTimersByTimeAsync(1);
  expect(f).toHaveBeenCalledTimes(4);
});

it("applies jitter and caps the delay at maxBackoffMs", async () => {
  const f = fakeFetch([emptyStream(), emptyStream()]);
  // random 0 → factor 0.8; initial 1000 capped by max 500 → 400 ms
  client({ fetchImpl: f, random: () => 0, maxBackoffMs: 500 }).start();
  await vi.advanceTimersByTimeAsync(399);
  expect(f).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(f).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(399);
  expect(f).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(1);
  expect(f).toHaveBeenCalledTimes(3);
});

it("resets the backoff after a board event", async () => {
  const f = fakeFetch([emptyStream(), streamWith(BOARD), emptyStream()]);
  client({ fetchImpl: f }).start();
  await vi.advanceTimersByTimeAsync(1000); // first delay 1000 (n 0 → 1)
  expect(f).toHaveBeenCalledTimes(2);
  // the board event resets n, so the delay before the third request is 1000 again, not 2000
  await vi.advanceTimersByTimeAsync(999);
  expect(f).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(1);
  expect(f).toHaveBeenCalledTimes(3);
  // the third request failed without a board event: the next delay doubles to 2000
  await vi.advanceTimersByTimeAsync(1999);
  expect(f).toHaveBeenCalledTimes(3);
  await vi.advanceTimersByTimeAsync(1);
  expect(f).toHaveBeenCalledTimes(4);
});

it("delivers parsed events to onEvent", async () => {
  const onEvent = vi.fn();
  const f = fakeFetch([streamWith(BOARD + 'event: mcp\ndata: {"id":1}\n\n', { keepOpen: true })]);
  client({ fetchImpl: f, onEvent }).start();
  await vi.advanceTimersByTimeAsync(0);
  expect(onEvent.mock.calls.map(([e]) => e)).toEqual([
    { event: "board", data: '{"now":"x","mcps":[]}' },
    { event: "mcp", data: '{"id":1}' },
  ]);
  const [input, init] = f.mock.calls[0]!;
  expect(String(input)).toBe(`${location.origin}/api/stream`);
  expect(init).toMatchObject({ credentials: "same-origin" });
});

it("aborts a silent stream after the watchdog", async () => {
  const f = fakeFetch([openStream()]);
  client({ fetchImpl: f }).start();
  await vi.advanceTimersByTimeAsync(44_999);
  expect(f.signalOf(0).aborted).toBe(false);
  await vi.advanceTimersByTimeAsync(1);
  expect(f.signalOf(0).aborted).toBe(true);
  expect(f).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1000);
  expect(f).toHaveBeenCalledTimes(2);
});

it("keeps a stream that sends heartbeats alive", async () => {
  const s = openStream();
  const f = fakeFetch([s]);
  client({ fetchImpl: f }).start();
  for (let i = 0; i < 6; i++) {
    await vi.advanceTimersByTimeAsync(15_000);
    s.push(": ping\n\n");
  }
  await vi.advanceTimersByTimeAsync(0);
  expect(f.signalOf(0).aborted).toBe(false);
  expect(f).toHaveBeenCalledTimes(1);
});

it("closes after 60 s hidden and reconnects on visible", async () => {
  const statuses: StreamStatus[] = [];
  const f = fakeFetch([streamWith(": ping\n\n", { keepOpen: true })]);
  // watchdog off for this test: only the hidden timer may close the silent stream
  client({ fetchImpl: f, onStatus: (s) => statuses.push(s), watchdogMs: 1e9 }).start();
  await vi.advanceTimersByTimeAsync(0);
  setVisibility("hidden");
  await vi.advanceTimersByTimeAsync(30_000);
  setVisibility("visible"); // a short hide does not close
  setVisibility("hidden");
  await vi.advanceTimersByTimeAsync(59_999);
  expect(f.signalOf(0).aborted).toBe(false);
  await vi.advanceTimersByTimeAsync(1);
  expect(f.signalOf(0).aborted).toBe(true);
  // paused, not stopped: no reconnect while hidden, however long
  await vi.advanceTimersByTimeAsync(120_000);
  expect(f).toHaveBeenCalledTimes(1);
  expect(statuses.at(-1)).toBe("reconnecting");
  setVisibility("visible");
  expect(f).toHaveBeenCalledTimes(2);
});

it("restart() aborts the current stream and connects at once", async () => {
  const f = fakeFetch([openStream(), openStream()]);
  const c = client({ fetchImpl: f });
  c.start();
  await vi.advanceTimersByTimeAsync(0);
  c.restart();
  expect(f.signalOf(0).aborted).toBe(true);
  expect(f).toHaveBeenCalledTimes(2);
  // the aborted first stream must not schedule an extra reconnect
  await vi.advanceTimersByTimeAsync(5000);
  expect(f).toHaveBeenCalledTimes(2);
});

it("restart() during a backoff wait connects at once without a second timer", async () => {
  const f = fakeFetch([emptyStream(), emptyStream()]);
  const c = client({ fetchImpl: f });
  c.start();
  await vi.advanceTimersByTimeAsync(500);
  c.restart();
  expect(f).toHaveBeenCalledTimes(2);
  // the second request failed: its delay starts from n = 0 (1000), the old timer is gone
  await vi.advanceTimersByTimeAsync(999);
  expect(f).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(1);
  expect(f).toHaveBeenCalledTimes(3);
});

it("reports statuses connecting → open → reconnecting", async () => {
  const statuses: StreamStatus[] = [];
  const second = openStream();
  const f = fakeFetch([streamWith(BOARD), second]);
  const c = client({ fetchImpl: f, onStatus: (s) => statuses.push(s) });
  expect(c.status).toBe("stopped");
  c.start();
  await vi.advanceTimersByTimeAsync(0);
  expect(statuses).toEqual(["connecting", "open", "reconnecting"]);
  await vi.advanceTimersByTimeAsync(1000);
  expect(statuses).toEqual(["connecting", "open", "reconnecting"]); // headers alone are not "open"
  second.push(": heartbeat\n\n");
  await vi.advanceTimersByTimeAsync(0);
  expect(statuses).toEqual(["connecting", "open", "reconnecting", "open"]);
  expect(c.status).toBe("open");
  c.stop();
  expect(statuses.at(-1)).toBe("stopped");
  expect(f.signalOf(1).aborted).toBe(true);
});

it("does not report an empty 200 (a lost slot race) as open", async () => {
  const statuses: StreamStatus[] = [];
  const f = fakeFetch([emptyStream(), emptyStream(), emptyStream()]);
  client({ fetchImpl: f, onStatus: (s) => statuses.push(s) }).start();
  await vi.advanceTimersByTimeAsync(0);
  await vi.advanceTimersByTimeAsync(1000);
  await vi.advanceTimersByTimeAsync(2000);
  expect(f).toHaveBeenCalledTimes(3);
  expect(statuses).not.toContain("open"); // no reconnecting → open flip, so no reconcile per attempt
  expect(statuses).toEqual(["connecting", "reconnecting"]);
});

it("stop() cancels a pending reconnect and ignores visibility changes", async () => {
  const f = fakeFetch([emptyStream()]);
  const c = client({ fetchImpl: f });
  c.start();
  await vi.advanceTimersByTimeAsync(0);
  c.stop();
  await vi.advanceTimersByTimeAsync(60_000);
  setVisibility("hidden");
  setVisibility("visible");
  expect(f).toHaveBeenCalledTimes(1);
  expect(c.status).toBe("stopped");
});
