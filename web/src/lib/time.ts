// Time and size formatting. Every timestamp is shown in KST whatever the host time zone (U28):
// the server and its logs are KST, so the UI matches what an operator greps for.
import { formatDistanceStrict } from "date-fns/formatDistanceStrict";
import { ko } from "date-fns/locale/ko";
import { copy } from "@/copy/ko";

const kst = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function kstParts(iso: string): Record<"year" | "month" | "day" | "hour" | "minute" | "second", string> {
  const out = { year: "", month: "", day: "", hour: "", minute: "", second: "" };
  for (const p of kst.formatToParts(new Date(iso))) {
    if (p.type in out) out[p.type as keyof typeof out] = p.value;
  }
  return out;
}

/** `YYYY-MM-DD HH:mm:ss` in KST. */
export function formatKst(iso: string): string {
  const p = kstParts(iso);
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
}

/** `MM-DD HH:mm` in KST. */
export function formatKstShort(iso: string): string {
  const p = kstParts(iso);
  return `${p.month}-${p.day} ${p.hour}:${p.minute}`;
}

/** "3분 전" / "1분 후" relative to `now` (default: the current time). */
export function relativeKo(iso: string, now: Date = new Date()): string {
  return formatDistanceStrict(new Date(iso), now, { addSuffix: true, locale: ko });
}

/** "1.2초" under a minute, "2분 3초", "1시간 2분"; "—" when unknown. */
export function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  const { seconds, minutes, hours } = copy.common.units;
  const tenths = Math.round(ms / 100);
  if (tenths < 600) return seconds((tenths / 10).toFixed(1));
  const total = Math.round(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return m > 0 ? `${hours(h)} ${minutes(m)}` : hours(h);
  return s > 0 ? `${minutes(m)} ${seconds(s)}` : minutes(m);
}

const BYTE_UNITS = ["KB", "MB", "GB", "TB"] as const;

/** Binary units with one decimal: "12.3 MB"; whole bytes below 1 KB. */
export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  let v = n / 1024;
  let unit = 0;
  while (v >= 1024 && unit < BYTE_UNITS.length - 1) {
    v /= 1024;
    unit++;
  }
  return `${v.toFixed(1)} ${BYTE_UNITS[unit]}`;
}
