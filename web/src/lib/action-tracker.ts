// Toasts for the manual actions this tab started (U29). The POST answers 202 with a run id; the
// result arrives later as an SSE `action` event. A run that never hears its final event (the
// stream dropped meanwhile) is looked up in the MCP's last-hour history on reconnect and at its
// deadline; only when history has nothing at the deadline does the toast say "unknown", and a late
// event can still finish it (F24).
import type { ActionEvent, McpHistory, ScriptKind } from "./api-types";

export interface TrackedRun {
  runId: string;
  mcpId: number;
  mcpName: string;
  requested: ScriptKind;
  /** Deadline for this run (F24: use trackerTimeoutMs(script_timeout_sec)); default: the tracker's. */
  timeoutMs?: number;
}

export type ActionResult = Pick<ActionEvent, "status" | "exit_code" | "duration_ms">;

export interface ActionToasts {
  pending(r: TrackedRun): void;
  step(r: TrackedRun, e: ActionEvent): void;
  done(r: TrackedRun, e: ActionResult): void;
  unknown(r: TrackedRun): void;
}

/** A restart without a restart script runs stop then start under one run id (U9): stop is not the end. */
export function isFinalStep(requested: ScriptKind, kind: ScriptKind): boolean {
  return !(requested === "restart" && kind === "stop");
}

/** F24: a fallback restart can take two full script timeouts, plus slack for the slot wait. */
export function trackerTimeoutMs(scriptTimeoutSec: number): number {
  return (2 * scriptTimeoutSec + 30) * 1000;
}

const DEFAULT_TIMEOUT_MS = 150_000;
/** Events for run ids not tracked yet: the result can beat the 202 response of a fast script. */
const EARLY_EVENT_MS = 30_000;
const EARLY_EVENT_MAX = 50;
/** After "unknown", a late event still finishes the toast for as long as history could hold it. */
const LINGER_MS = 60 * 60_000;

interface Entry {
  run: TrackedRun;
  phase: "pending" | "unknown";
  timer: ReturnType<typeof setTimeout>;
}

export class ActionTracker {
  private readonly toasts: ActionToasts;
  private readonly fetchHistory: (mcpId: number) => Promise<McpHistory>;
  private readonly timeoutMs: number;
  private readonly runs = new Map<string, Entry>();
  private early: { at: number; e: ActionEvent }[] = [];
  private stopped = false;

  constructor(o: { toasts: ActionToasts; fetchHistory: (mcpId: number) => Promise<McpHistory>; timeoutMs?: number }) {
    this.toasts = o.toasts;
    this.fetchHistory = o.fetchHistory;
    this.timeoutMs = o.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  /** True from dispose() until activate(): the shell that owned the tracker is gone. */
  get disposed(): boolean {
    return this.stopped;
  }

  track(r: TrackedRun): void {
    // a 202 that lands after the shell unmounted (logout): Sonner would replay its toast to the next login
    if (this.stopped || this.runs.has(r.runId)) return;
    this.toasts.pending(r);
    const timer = setTimeout(() => void this.expire(r.runId), r.timeoutMs ?? this.timeoutMs);
    this.runs.set(r.runId, { run: r, phase: "pending", timer });
    this.pruneEarly();
    const replay = this.early.filter((x) => x.e.run_id === r.runId);
    this.early = this.early.filter((x) => x.e.run_id !== r.runId);
    for (const x of replay) this.handle(x.e);
  }

  /** SSE `action` listener (an arrow property, so it can be passed to BoardStore.onAction as is). */
  readonly handle = (e: ActionEvent): void => {
    if (this.stopped) return;
    const entry = this.runs.get(e.run_id);
    if (!entry) {
      this.pruneEarly();
      this.early.push({ at: Date.now(), e });
      if (this.early.length > EARLY_EVENT_MAX) this.early.shift();
      return;
    }
    if (!isFinalStep(entry.run.requested, e.kind)) {
      this.toasts.step(entry.run, e);
      return;
    }
    this.finish(entry, e);
  };

  /** Looks every tracked run up in its MCP's last-hour history (one request per MCP). */
  async reconcile(): Promise<void> {
    await this.settle([...this.runs.values()]);
  }

  /** Accepts runs again after dispose(): StrictMode re-runs the shell's effect on the same tracker. */
  activate(): void {
    this.stopped = false;
  }

  /** Stops every timer, forgets every run and ignores later ones until activate(). */
  dispose(): void {
    this.stopped = true;
    for (const entry of this.runs.values()) clearTimeout(entry.timer);
    this.runs.clear();
    this.early = [];
  }

  private finish(entry: Entry, result: ActionResult): void {
    clearTimeout(entry.timer);
    this.runs.delete(entry.run.runId);
    this.toasts.done(entry.run, { status: result.status, exit_code: result.exit_code, duration_ms: result.duration_ms });
  }

  private async settle(entries: Entry[]): Promise<void> {
    const byMcp = new Map<number, Entry[]>();
    for (const entry of entries) byMcp.set(entry.run.mcpId, [...(byMcp.get(entry.run.mcpId) ?? []), entry]);
    await Promise.all(
      [...byMcp].map(async ([mcpId, group]) => {
        let history: McpHistory;
        try {
          history = await this.fetchHistory(mcpId);
        } catch {
          return; // try again on the next reconnect or at the deadline
        }
        for (const entry of group) {
          if (this.runs.get(entry.run.runId) !== entry) continue; // finished meanwhile
          const rec = history.actions.find((a) => a.run_id === entry.run.runId && isFinalStep(a.requested, a.kind));
          if (rec) this.finish(entry, rec);
        }
      }),
    );
  }

  private async expire(runId: string): Promise<void> {
    const entry = this.runs.get(runId);
    if (!entry || entry.phase !== "pending") return;
    await this.settle([entry]);
    if (this.runs.get(runId) !== entry) return;
    entry.phase = "unknown";
    this.toasts.unknown(entry.run);
    entry.timer = setTimeout(() => {
      if (this.runs.get(runId) === entry) this.runs.delete(runId);
    }, LINGER_MS);
  }

  private pruneEarly(): void {
    const cutoff = Date.now() - EARLY_EVENT_MS;
    if (this.early.some((x) => x.at < cutoff)) this.early = this.early.filter((x) => x.at >= cutoff);
  }
}
