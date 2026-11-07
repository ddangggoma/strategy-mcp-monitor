import type { MinuteBucket } from "@/lib/api-types";
import { downsample, tickStep } from "./downsample";

const T0 = Date.parse("2026-11-04T00:00:00.000+09:00");

/** Minute `i` after T0 as the server writes it (KST ISO). */
function bucket(i: number, p: { ok: number; total: number; avg: number | null; max: number | null }): MinuteBucket {
  const at = new Date(T0 + i * 60_000 + 9 * 3_600_000).toISOString().replace("Z", "+09:00");
  return { minute: at, ok: p.ok, total: p.total, avg_latency_ms: p.avg, max_latency_ms: p.max };
}

it("returns buckets unchanged under the limit and groups above it", () => {
  const b = Array.from({ length: 1440 }, (_, i) => bucket(i, { ok: i % 2, total: 1, avg: i % 3 === 0 ? null : 10, max: i }));
  const pts = downsample(b, 720);
  expect(pts).toHaveLength(720); expect(pts[0]).toEqual({ at: b[0]!.minute, avg: 10, max: 1, uptime: 0.5 });
  expect(downsample(b.slice(0, 5), 720)).toHaveLength(5);
});

it("uptime is null for a group without checks", () => {
  const b = [bucket(0, { ok: 0, total: 0, avg: null, max: null }), bucket(1, { ok: 0, total: 0, avg: null, max: null })];
  expect(downsample(b, 1)).toEqual([{ at: b[0]!.minute, avg: null, max: null, uptime: null }]);
  expect(downsample(b, 720)[1]).toEqual({ at: b[1]!.minute, avg: null, max: null, uptime: null });
});

it("averages only the minutes that have an average and keeps the group maximum", () => {
  const b = [
    bucket(0, { ok: 3, total: 4, avg: 10, max: 30 }),
    bucket(1, { ok: 4, total: 4, avg: null, max: null }),
    bucket(2, { ok: 1, total: 4, avg: 20, max: 90 }),
  ];
  expect(downsample(b, 1)).toEqual([{ at: b[0]!.minute, avg: 15, max: 90, uptime: 8 / 12 }]);
});

it("groups ceil(n / maxPoints) minutes, so the last group may be shorter", () => {
  const b = Array.from({ length: 7 }, (_, i) => bucket(i, { ok: 1, total: 1, avg: i, max: i }));
  const pts = downsample(b, 3); // groups of 3: [0,1,2] [3,4,5] [6]
  expect(pts.map((p) => p.at)).toEqual([b[0]!.minute, b[3]!.minute, b[6]!.minute]);
  expect(pts.map((p) => p.avg)).toEqual([1, 4, 6]);
  expect(pts.map((p) => p.max)).toEqual([2, 5, 6]);
});

it("keeps a full week (10,080 minutes) at no more than 720 points", () => {
  const b = Array.from({ length: 10_080 }, (_, i) => bucket(i, { ok: 1, total: 1, avg: 5, max: 5 }));
  const pts = downsample(b);
  expect(pts.length).toBeLessThanOrEqual(720);
  expect(pts).toHaveLength(720); // groups of 14
  expect(downsample([])).toEqual([]);
});

it("chart ticks follow the span shown, not the period picked", () => {
  const min = 60_000;
  expect(tickStep(5 * min)).toBe(min); // a new MCP: minutes of data even in the 7-day view
  expect(tickStep(60 * min)).toBe(10 * min);
  expect(tickStep(24 * 60 * min)).toBe(360 * min);
  expect(tickStep(7 * 24 * 60 * min)).toBe(2 * 24 * 60 * min);
});
