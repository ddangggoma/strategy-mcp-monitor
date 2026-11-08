// Board-wide numbers for the overview tiles, computed from the live board items alone (no extra
// request: the anonymous board has the SSE stream and nothing else).
import type { BoardItem, McpState } from "@/lib/api-types";
import { STATE_SEVERITY } from "@/lib/board-store";

/** How a ratio reads against its thresholds: good, worth a look, or bad. */
export type Tone = "good" | "warn" | "bad";

/** States in severity order, worst first (the donut and its legend). */
export const STATES_BY_SEVERITY = (Object.keys(STATE_SEVERITY) as McpState[]).sort((a, b) => STATE_SEVERITY[a] - STATE_SEVERITY[b]);

/** 24 h uptime: 99 % or more is fine, under 95 % is bad. */
export const UPTIME_TONE = [0.99, 0.95] as const;
/** Recent checks: one failure in a hundred is worth a look, one in ten is bad. */
export const CHECK_TONE = [0.99, 0.9] as const;

export function toneOf(ratio: number, [good, warn]: readonly [number, number]): Tone {
  if (ratio >= good) return "good";
  if (ratio >= warn) return "warn";
  return "bad";
}

/** One column of the check strip: of the MCPs checked at that step, how many answered. */
export interface CheckStep {
  ok: number;
  total: number;
}

export interface Overview {
  total: number;
  counts: ReadonlyMap<McpState, number>;
  /** The worst state on the board (null: no MCP). */
  worst: McpState | null;
  /** Mean of the current latencies (ms), and the slowest MCP. */
  latency: { avg: number; max: number; maxName: string } | null;
  /** Mean latency per check step, oldest first, right-aligned across MCPs (null: no answer at that step). */
  latencyTrend: (number | null)[];
  /** Check results per step, oldest first, right-aligned across MCPs. */
  checks: CheckStep[];
  /** Share of answered checks over `checks`. */
  checkRate: { ok: number; total: number; ratio: number } | null;
  /** Mean of the 24 h uptimes and the lowest one. */
  uptime: { avg: number; min: number; minName: string } | null;
}

/** MCPs in maintenance are not judged (direction: no state, no recovery), so they stay out of the numbers. */
const judged = (it: BoardItem) => it.state !== "MAINTENANCE";

export function overview(items: Iterable<BoardItem>): Overview {
  const all = [...items];
  const counts = new Map<McpState, number>();
  for (const it of all) counts.set(it.state, (counts.get(it.state) ?? 0) + 1);
  const worst = STATES_BY_SEVERITY.find((s) => (counts.get(s) ?? 0) > 0) ?? null;

  const live = all.filter(judged);

  let latency: Overview["latency"] = null;
  const timed = live.filter((it): it is BoardItem & { latency_ms: number } => it.latency_ms !== null);
  if (timed.length > 0) {
    const slowest = timed.reduce((a, b) => (b.latency_ms > a.latency_ms ? b : a));
    latency = {
      avg: timed.reduce((s, it) => s + it.latency_ms, 0) / timed.length,
      max: slowest.latency_ms,
      maxName: slowest.name,
    };
  }

  // sparklines end at each MCP's latest check: line them up from the right
  const steps = live.reduce((n, it) => Math.max(n, it.sparkline.length), 0);
  const checks: CheckStep[] = Array.from({ length: steps }, () => ({ ok: 0, total: 0 }));
  const sums: number[] = Array.from({ length: steps }, () => 0);
  for (const it of live) {
    const offset = steps - it.sparkline.length;
    it.sparkline.forEach((v, i) => {
      const step = checks[offset + i]!;
      step.total++;
      if (v !== null) {
        step.ok++;
        sums[offset + i]! += v;
      }
    });
  }
  const latencyTrend = checks.map((c, i) => (c.ok > 0 ? sums[i]! / c.ok : null));
  const okChecks = checks.reduce((s, c) => s + c.ok, 0);
  const allChecks = checks.reduce((s, c) => s + c.total, 0);
  const checkRate = allChecks > 0 ? { ok: okChecks, total: allChecks, ratio: okChecks / allChecks } : null;

  let uptime: Overview["uptime"] = null;
  const measured = live.filter((it): it is BoardItem & { uptime_24h: number } => it.uptime_24h !== null);
  if (measured.length > 0) {
    const lowest = measured.reduce((a, b) => (b.uptime_24h < a.uptime_24h ? b : a));
    uptime = {
      avg: measured.reduce((s, it) => s + it.uptime_24h, 0) / measured.length,
      min: lowest.uptime_24h,
      minName: lowest.name,
    };
  }

  return { total: all.length, counts, worst, latency, latencyTrend, checks, checkRate, uptime };
}

/** The newest `last_check_at` on the board (what “마지막 점검 n초 전” counts from). */
export function latestCheck(items: Iterable<BoardItem>): string | null {
  let at: string | null = null;
  for (const it of items) {
    if (it.last_check_at !== null && (at === null || Date.parse(it.last_check_at) > Date.parse(at))) at = it.last_check_at;
  }
  return at;
}

/** How a check step reads: every MCP answered, some did not, or most did not. */
export function stepTone(step: CheckStep): Tone {
  if (step.ok === step.total) return "good";
  return step.ok * 2 >= step.total ? "warn" : "bad";
}

/** A 0–1 ratio as a percent number with one decimal, never rounding a miss up to 100. */
export function percent(ratio: number): number {
  return Math.floor(ratio * 1000) / 10;
}
