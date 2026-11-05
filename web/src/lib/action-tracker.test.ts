import type { ActionEvent, McpHistory, ScriptKind, ScriptStatus } from "./api-types";
import { ActionTracker, isFinalStep, trackerTimeoutMs, type ActionToasts, type TrackedRun } from "./action-tracker";
import { record } from "../../tests/msw/fixtures";

const run: TrackedRun = { runId: "r1", mcpId: 1, mcpName: "calc", requested: "restart" };
const ev = (kind: ScriptKind, status: ScriptStatus = "ok", p: Partial<ActionEvent> = {}): ActionEvent => ({
  run_id: "r1", mcp_id: 1, kind, requested: "restart", trigger: "manual", status, exit_code: 0, duration_ms: 900, ...p,
});
const empty = (): McpHistory => ({ buckets: [], transitions: [], actions: [] });

function fake() {
  return { pending: vi.fn(), step: vi.fn(), done: vi.fn(), unknown: vi.fn() } satisfies ActionToasts;
}

afterEach(() => {
  vi.useRealTimers();
});

it("treats only the stop step of a requested restart as intermediate", () => {
  expect(isFinalStep("restart", "stop")).toBe(false);
  expect(isFinalStep("restart", "start")).toBe(true);
  expect(isFinalStep("restart", "restart")).toBe(true);
  expect(isFinalStep("stop", "stop")).toBe(true);
  expect(isFinalStep("start", "start")).toBe(true);
});

it("sizes the timeout for a stop+start fallback (F24)", () => {
  expect(trackerTimeoutMs(120)).toBe(270_000);
  expect(trackerTimeoutMs(5)).toBe(40_000);
});

it("shows the pending toast when tracking starts", () => {
  const t = fake();
  new ActionTracker({ toasts: t, fetchHistory: vi.fn() }).track(run);
  expect(t.pending).toHaveBeenCalledWith(run);
});

it("restart fallback waits for the start step", () => {
  const t = fake();
  const tr = new ActionTracker({ toasts: t, fetchHistory: vi.fn() });
  tr.track(run);
  tr.handle(ev("stop"));
  expect(t.done).not.toHaveBeenCalled();
  expect(t.step).toHaveBeenCalledTimes(1);
  expect(t.step).toHaveBeenCalledWith(run, expect.objectContaining({ kind: "stop" }));
  tr.handle(ev("start"));
  expect(t.done).toHaveBeenCalledWith(run, expect.objectContaining({ status: "ok" }));
  // finished runs are no longer tracked: a duplicate event changes nothing
  tr.handle(ev("start", "failed"));
  expect(t.done).toHaveBeenCalledTimes(1);
});

it("ignores events for run ids this tab did not start", () => {
  const t = fake();
  const tr = new ActionTracker({ toasts: t, fetchHistory: vi.fn() });
  tr.track(run);
  tr.handle(ev("start", "ok", { run_id: "other", requested: "start" }));
  expect(t.step).not.toHaveBeenCalled();
  expect(t.done).not.toHaveBeenCalled();
  expect(t.unknown).not.toHaveBeenCalled();
});

it("resolves a run whose result arrived before the 202 response", () => {
  const t = fake();
  const tr = new ActionTracker({ toasts: t, fetchHistory: vi.fn() });
  tr.handle(ev("start", "failed", { run_id: "r2", requested: "start", exit_code: 2 }));
  expect(t.done).not.toHaveBeenCalled();
  const r2: TrackedRun = { ...run, runId: "r2", requested: "start" };
  tr.track(r2);
  expect(t.pending).toHaveBeenCalledWith(r2);
  expect(t.done).toHaveBeenCalledWith(r2, expect.objectContaining({ status: "failed", exit_code: 2 }));
});

it("forgets early events after 30 seconds", () => {
  vi.useFakeTimers();
  const t = fake();
  const tr = new ActionTracker({ toasts: t, fetchHistory: vi.fn() });
  tr.handle(ev("start", "ok", { run_id: "r3", requested: "start" }));
  vi.advanceTimersByTime(30_001);
  tr.track({ ...run, runId: "r3", requested: "start" });
  expect(t.done).not.toHaveBeenCalled();
  tr.dispose();
});

it("reconciles a pending action from history after reconnect", async () => {
  const t = fake();
  const fetchHistory = vi.fn().mockResolvedValue({
    buckets: [], transitions: [], actions: [record({ run_id: "r1", kind: "restart", status: "failed", exit_code: 3 })],
  });
  const tr = new ActionTracker({ toasts: t, fetchHistory });
  tr.track(run);
  await tr.reconcile();
  expect(fetchHistory).toHaveBeenCalledWith(1);
  expect(t.done).toHaveBeenCalledWith(run, expect.objectContaining({ status: "failed", exit_code: 3 }));
});

it("does not finish a restart from its stop step in history", async () => {
  const t = fake();
  const fetchHistory = vi.fn().mockResolvedValue({
    ...empty(),
    actions: [record({ run_id: "r1", requested: "restart", kind: "stop", status: "ok" }), record({ run_id: "zz", kind: "restart" })],
  });
  const tr = new ActionTracker({ toasts: t, fetchHistory });
  tr.track(run);
  await tr.reconcile();
  expect(t.done).not.toHaveBeenCalled();
  expect(t.unknown).not.toHaveBeenCalled(); // before the deadline nothing is decided
  tr.dispose();
});

it("fetches each MCP's history once for several runs and survives a failed fetch", async () => {
  const t = fake();
  const fetchHistory = vi.fn(async (id: number): Promise<McpHistory> => {
    if (id === 2) throw new Error("offline");
    return { ...empty(), actions: [record({ run_id: "a", requested: "start", kind: "start" }), record({ run_id: "b", requested: "stop", kind: "stop" })] };
  });
  const tr = new ActionTracker({ toasts: t, fetchHistory });
  const a: TrackedRun = { runId: "a", mcpId: 1, mcpName: "calc", requested: "start" };
  const b: TrackedRun = { runId: "b", mcpId: 1, mcpName: "calc", requested: "stop" };
  const c: TrackedRun = { runId: "c", mcpId: 2, mcpName: "files", requested: "start" };
  tr.track(a);
  tr.track(b);
  tr.track(c);
  await tr.reconcile();
  expect(fetchHistory).toHaveBeenCalledTimes(2);
  expect(t.done).toHaveBeenCalledWith(a, expect.objectContaining({ status: "ok" }));
  expect(t.done).toHaveBeenCalledWith(b, expect.objectContaining({ status: "ok" }));
  expect(t.done).toHaveBeenCalledTimes(2);
  expect(t.unknown).not.toHaveBeenCalled();
  tr.dispose();
});

it("does not reconcile when nothing is tracked", async () => {
  const fetchHistory = vi.fn();
  await new ActionTracker({ toasts: fake(), fetchHistory }).reconcile();
  expect(fetchHistory).not.toHaveBeenCalled();
});

it("reports unknown after the timeout when history has nothing", async () => {
  vi.useFakeTimers();
  const t = fake();
  const fetchHistory = vi.fn().mockResolvedValue(empty());
  const tr = new ActionTracker({ toasts: t, fetchHistory });
  tr.track(run);
  await vi.advanceTimersByTimeAsync(149_999);
  expect(fetchHistory).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1);
  expect(fetchHistory).toHaveBeenCalledWith(1);
  expect(t.unknown).toHaveBeenCalledWith(run);
  expect(t.done).not.toHaveBeenCalled();
  tr.dispose();
});

it("finishes from history at the deadline instead of reporting unknown", async () => {
  vi.useFakeTimers();
  const t = fake();
  const fetchHistory = vi.fn().mockResolvedValue({ ...empty(), actions: [record({ run_id: "r1", kind: "start", status: "ok" })] });
  const tr = new ActionTracker({ toasts: t, fetchHistory, timeoutMs: 1000 });
  tr.track(run);
  await vi.advanceTimersByTimeAsync(1000);
  expect(t.done).toHaveBeenCalledWith(run, expect.objectContaining({ status: "ok" }));
  expect(t.unknown).not.toHaveBeenCalled();
});

it("uses the run's own timeout and keeps listening after unknown (F24)", async () => {
  vi.useFakeTimers();
  const t = fake();
  const tr = new ActionTracker({ toasts: t, fetchHistory: vi.fn().mockResolvedValue(empty()) });
  const slow: TrackedRun = { ...run, timeoutMs: trackerTimeoutMs(120) };
  tr.track(slow);
  await vi.advanceTimersByTimeAsync(150_000);
  expect(t.unknown).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(120_000);
  expect(t.unknown).toHaveBeenCalledWith(slow);
  tr.handle(ev("start", "ok"));
  expect(t.done).toHaveBeenCalledWith(slow, expect.objectContaining({ status: "ok" }));
  tr.dispose();
});

it("stops listening an hour after unknown", async () => {
  vi.useFakeTimers();
  const t = fake();
  const tr = new ActionTracker({ toasts: t, fetchHistory: vi.fn().mockResolvedValue(empty()), timeoutMs: 1000 });
  tr.track(run);
  await vi.advanceTimersByTimeAsync(1000);
  expect(t.unknown).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(60 * 60_000);
  tr.handle(ev("start"));
  expect(t.done).not.toHaveBeenCalled();
});

it("dispose clears runs and timers", async () => {
  vi.useFakeTimers();
  const t = fake();
  const fetchHistory = vi.fn().mockResolvedValue(empty());
  const tr = new ActionTracker({ toasts: t, fetchHistory });
  tr.track(run);
  tr.dispose();
  await vi.advanceTimersByTimeAsync(200_000);
  expect(fetchHistory).not.toHaveBeenCalled();
  tr.handle(ev("start"));
  expect(t.done).not.toHaveBeenCalled();
  // still usable afterwards (StrictMode re-runs effects)
  tr.track(run);
  tr.handle(ev("start"));
  expect(t.done).toHaveBeenCalledTimes(1);
});

it("does not report a run twice when an event lands during a reconcile fetch", async () => {
  const t = fake();
  let resolve!: (h: McpHistory) => void;
  const fetchHistory = vi.fn(() => new Promise<McpHistory>((r) => (resolve = r)));
  const tr = new ActionTracker({ toasts: t, fetchHistory });
  tr.track(run);
  const p = tr.reconcile();
  tr.handle(ev("start", "ok"));
  resolve({ ...empty(), actions: [record({ run_id: "r1", kind: "start", status: "failed" })] });
  await p;
  expect(t.done).toHaveBeenCalledTimes(1);
  expect(t.done).toHaveBeenCalledWith(run, expect.objectContaining({ status: "ok" }));
});
