import type { MinuteBucket } from "@/lib/api-types";

export interface ChartPoint {
  /** First minute of the group (KST ISO). */
  at: string;
  /** Mean of the minutes' averages that exist (ms); null when none has one. */
  avg: number | null;
  /** Largest per-minute maximum (ms). */
  max: number | null;
  /** Σok / Σtotal (0–1); null when the group had no checks. */
  uptime: number | null;
}

/**
 * At most `maxPoints` chart points from per-minute buckets: consecutive minutes are grouped
 * ceil(n / maxPoints) at a time (a week is 10,080 minutes → groups of 14), so the line keeps its
 * shape without drawing more points than the chart has pixels.
 */
export function downsample(buckets: MinuteBucket[], maxPoints = 720): ChartPoint[] {
  const size = Math.max(1, Math.ceil(buckets.length / maxPoints));
  const out: ChartPoint[] = [];
  for (let start = 0; start < buckets.length; start += size) {
    let ok = 0;
    let total = 0;
    let avgSum = 0;
    let avgCount = 0;
    let max: number | null = null;
    const end = Math.min(start + size, buckets.length);
    for (let i = start; i < end; i++) {
      const b = buckets[i]!;
      ok += b.ok;
      total += b.total;
      if (b.avg_latency_ms !== null) {
        avgSum += b.avg_latency_ms;
        avgCount++;
      }
      if (b.max_latency_ms !== null && (max === null || b.max_latency_ms > max)) max = b.max_latency_ms;
    }
    out.push({
      at: buckets[start]!.minute,
      avg: avgCount > 0 ? avgSum / avgCount : null,
      max,
      uptime: total > 0 ? ok / total : null,
    });
  }
  return out;
}
