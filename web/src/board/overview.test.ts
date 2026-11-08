import type { BoardItem } from "@/lib/api-types";
import { item } from "../../tests/msw/fixtures";
import { CHECK_TONE, UPTIME_TONE, latestCheck, overview, percent, stepTone, toneOf } from "./overview";

const with_ = (base: BoardItem, extra: Partial<BoardItem>): BoardItem => ({ ...base, ...extra });

it("counts states and finds the worst one", () => {
  const o = overview([item(1, "HEALTHY"), item(2, "SUSPECT"), item(3, "FAILED"), item(4, "HEALTHY")]);
  expect(o.total).toBe(4);
  expect(o.counts.get("HEALTHY")).toBe(2);
  expect(o.counts.get("FAILED")).toBe(1);
  expect(o.worst).toBe("FAILED");
  expect(overview([]).worst).toBeNull();
});

it("averages latency and uptime over the MCPs that have them, naming the slowest and the lowest", () => {
  const o = overview([
    with_(item(1, "HEALTHY", "a"), { latency_ms: 10, uptime_24h: 1 }),
    with_(item(2, "HEALTHY", "b"), { latency_ms: 30, uptime_24h: 0.9 }),
    with_(item(3, "FAILED", "c"), { latency_ms: null, uptime_24h: null }),
  ]);
  expect(o.latency).toEqual({ avg: 20, max: 30, maxName: "b" });
  expect(o.uptime).toEqual({ avg: 0.95, min: 0.9, minName: "b" });
});

it("leaves MCPs in maintenance out of the numbers but not out of the counts", () => {
  const o = overview([
    with_(item(1, "HEALTHY"), { latency_ms: 10, sparkline: [10, 10] }),
    with_(item(2, "MAINTENANCE"), { latency_ms: 500, sparkline: [null, null], uptime_24h: 0.1 }),
  ]);
  expect(o.counts.get("MAINTENANCE")).toBe(1);
  expect(o.latency?.avg).toBe(10);
  expect(o.uptime?.min).toBe(1);
  expect(o.checkRate).toEqual({ ok: 2, total: 2, ratio: 1 });
});

it("lines sparklines up from the right into check steps and a mean trend", () => {
  const o = overview([
    with_(item(1, "HEALTHY"), { sparkline: [10, 20, 30] }),
    with_(item(2, "FAILED"), { sparkline: [null, 40] }), // its two checks are the latest two steps
  ]);
  expect(o.checks).toEqual([
    { ok: 1, total: 1 },
    { ok: 1, total: 2 },
    { ok: 2, total: 2 },
  ]);
  expect(o.latencyTrend).toEqual([10, 20, 35]);
  expect(o.checkRate).toEqual({ ok: 4, total: 5, ratio: 0.8 });
});

it("reads ratios and check steps as tones", () => {
  expect(toneOf(1, UPTIME_TONE)).toBe("good");
  expect(toneOf(0.97, UPTIME_TONE)).toBe("warn");
  expect(toneOf(0.94, UPTIME_TONE)).toBe("bad");
  expect(toneOf(0.95, CHECK_TONE)).toBe("warn");
  expect(stepTone({ ok: 3, total: 3 })).toBe("good");
  expect(stepTone({ ok: 2, total: 3 })).toBe("warn");
  expect(stepTone({ ok: 1, total: 3 })).toBe("bad");
});

it("never rounds a miss up to 100 percent", () => {
  expect(percent(0.9996)).toBe(99.9);
  expect(percent(1)).toBe(100);
  expect(percent(0.889)).toBe(88.9);
});

it("finds the newest check on the board", () => {
  const a = with_(item(1, "HEALTHY"), { last_check_at: "2026-11-04T14:00:00.000+09:00" });
  const b = with_(item(2, "HEALTHY"), { last_check_at: "2026-11-04T14:00:05.000+09:00" });
  const c = with_(item(3, "HEALTHY"), { last_check_at: null });
  expect(latestCheck([a, b, c])).toBe(b.last_check_at);
  expect(latestCheck([c])).toBeNull();
});
