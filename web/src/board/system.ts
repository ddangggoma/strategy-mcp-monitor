// Formatting and thresholds for the "서버 PC 리소스" panel.
import { copy } from "@/copy/ko";
import type { McpState } from "@/lib/api-types";

const UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

/** 1024-based, one decimal from KB up ("15.9GB", "820B"). */
export function formatBytes(n: number): string {
  let v = n;
  let u = 0;
  while (v >= 1024 && u < UNITS.length - 1) {
    v /= 1024;
    u++;
  }
  return u === 0 ? `${Math.round(v)}${UNITS[0]}` : `${v.toFixed(1)}${UNITS[u]}`;
}

export const formatRate = (bps: number) => `${formatBytes(bps)}/s`;

/** "3일 4시간", "5시간 12분", "8분" since `bootIso`. */
export function formatUptime(bootIso: string, nowMs: number): string {
  const { days, hours, minutes } = copy.common.units;
  const min = Math.max(0, Math.floor((nowMs - Date.parse(bootIso)) / 60_000));
  const d = Math.floor(min / 1440);
  const h = Math.floor((min % 1440) / 60);
  const m = min % 60;
  if (d > 0) return h > 0 ? `${days(d)} ${hours(h)}` : days(d);
  if (h > 0) return m > 0 ? `${hours(h)} ${minutes(m)}` : hours(h);
  return minutes(m);
}

/** Where a load starts to be worth a look and where it is bad, in percent. */
export const CPU_LOAD = [70, 90] as const;
export const MEMORY_LOAD = [80, 90] as const;
export const DISK_LOAD = [80, 90] as const;
/** The GPU's busiest engine reads like a CPU; its dedicated memory like the PC's memory. */
export const GPU_LOAD = CPU_LOAD;
export const GPU_MEMORY_LOAD = MEMORY_LOAD;

/** A load in percent as the state hue it borrows: fine, worth a look, or bad. */
export function loadState(percent: number, [warn, bad]: readonly [number, number]): McpState {
  if (percent >= bad) return "FAILED";
  if (percent >= warn) return "SUSPECT";
  return "HEALTHY";
}
