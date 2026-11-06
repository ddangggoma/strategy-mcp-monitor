// Log and audit filter state lives only in the URL search (W34), so a link reproduces the view.
// Quick ranges are recomputed whenever they are resolved, and every bound sent to the API is a KST
// minute (W8: minute-aligned bounds take the rollup path, and the result is the same either way).
import type { AuditQuery, Channel, LogCategory, LogOutcome, LogQuery } from "@/lib/api-types";
import { LOG_CATEGORIES } from "./categories";

export type QuickRange = "1h" | "today" | "yesterday" | "7d";

export interface LogSearch {
  range?: QuickRange;
  from?: string;
  to?: string;
  users?: string[];
  cat?: LogCategory[];
  event?: string[];
  outcome?: LogOutcome[];
  session?: number;
  ip?: string;
  q?: string;
  view?: "table" | "timeline";
}

export type AuditKind = NonNullable<AuditQuery["kind"]>;

export interface AuditSearch {
  range?: QuickRange;
  from?: string;
  to?: string;
  kind?: AuditKind;
  users?: string[];
  result?: LogOutcome[];
  channel?: Channel;
  q?: string;
}

const MINUTE = 60_000;
const DAY = 86_400_000;
const KST_OFFSET = 9 * 3_600_000; // Korea has no daylight saving time

const RANGES: ReadonlySet<string> = new Set<QuickRange>(["1h", "today", "yesterday", "7d"]);
const CATEGORIES: ReadonlySet<string> = new Set<string>(LOG_CATEGORIES);
const OUTCOMES: ReadonlySet<string> = new Set<LogOutcome>(["ok", "fail", "denied", "error", "failed", "timeout"]);
const VIEWS: ReadonlySet<string> = new Set(["table", "timeline"]);
const KINDS: ReadonlySet<string> = new Set<AuditKind>(["admin", "auth", "all"]);
const CHANNELS: ReadonlySet<string> = new Set<Channel>(["local", "external"]);
/** ISO 8601 date-time with an explicit offset (the API rejects times without one). */
const OFFSET_ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})$/;

/** `YYYY-MM-DDTHH:mm:ss.SSS+09:00` for an epoch-ms instant. */
function kstIso(ms: number): string {
  return new Date(ms + KST_OFFSET).toISOString().replace("Z", "+09:00");
}

/** The KST minute an offset time falls in (seconds and milliseconds dropped). */
export function floorKstMinute(iso: string): string {
  return kstIso(Math.floor(Date.parse(iso) / MINUTE) * MINUTE);
}

/** 00:00 KST of the day `ms` falls in. */
function kstMidnight(ms: number): number {
  return Math.floor((ms + KST_OFFSET) / DAY) * DAY - KST_OFFSET;
}

/** Custom bounds when both are set, else the quick range (default the last hour). */
export function resolveRange(s: Pick<LogSearch, "range" | "from" | "to">, now: Date): { from: string; to: string } {
  if (s.from !== undefined && s.to !== undefined) return { from: floorKstMinute(s.from), to: floorKstMinute(s.to) };
  const end = Math.ceil(now.getTime() / MINUTE) * MINUTE; // "now" rounded up: the current minute is included
  const today = kstMidnight(now.getTime());
  switch (s.range ?? "1h") {
    case "today":
      return { from: kstIso(today), to: kstIso(end) };
    case "yesterday":
      return { from: kstIso(today - DAY), to: kstIso(today) };
    case "7d":
      return { from: kstIso(today - 6 * DAY), to: kstIso(end) };
    case "1h":
      return { from: kstIso(end - 60 * MINUTE), to: kstIso(end) };
  }
}

// ---- reading the URL: anything malformed is dropped, never "fixed" -----------------------

/** Text from the URL. TanStack Router JSON-parses each value, so a typed `?q=8812` is a number. */
function text(v: unknown): string | undefined {
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return typeof v === "string" && v !== "" ? v : undefined;
}

function oneOf<T extends string>(set: ReadonlySet<string>, v: unknown): T | undefined {
  return typeof v === "string" && set.has(v) ? (v as T) : undefined;
}

function strings(v: unknown): string[] | undefined {
  if (!Array.isArray(v)) return undefined;
  const out = v.filter((x): x is string => typeof x === "string" && x !== "");
  return out.length > 0 ? out : undefined;
}

function allowed<T extends string>(set: ReadonlySet<string>, v: unknown): T[] | undefined {
  const out = strings(v)?.filter((x) => set.has(x));
  return out && out.length > 0 ? (out as T[]) : undefined;
}

function offsetIso(v: unknown): string | undefined {
  return typeof v === "string" && OFFSET_ISO.test(v) && !Number.isNaN(Date.parse(v)) ? v : undefined;
}

function sessionId(v: unknown): number | undefined {
  const n = typeof v === "string" && /^\d+$/.test(v) ? Number(v) : v;
  return typeof n === "number" && Number.isSafeInteger(n) && n >= 0 ? n : undefined;
}

/** Only the keys that hold a value: the API query (and its React Query key) has no `undefined`. */
function defined<T extends object>(o: T): T {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined)) as T;
}

// The parsers return every key, `undefined` for a dropped value, on purpose: TanStack Router merges
// the validated search over the raw one, so a key left out would keep its malformed URL value.
// Undefined keys are not written to the URL.

/** The logs route's `validateSearch`. */
export function parseLogSearch(raw: Record<string, unknown>): LogSearch {
  return {
    range: oneOf<QuickRange>(RANGES, raw.range),
    from: offsetIso(raw.from),
    to: offsetIso(raw.to),
    users: strings(raw.users),
    cat: allowed<LogCategory>(CATEGORIES, raw.cat),
    event: strings(raw.event),
    outcome: allowed<LogOutcome>(OUTCOMES, raw.outcome),
    session: sessionId(raw.session),
    ip: text(raw.ip),
    q: text(raw.q),
    view: oneOf<"table" | "timeline">(VIEWS, raw.view),
  };
}

/** The audit route's `validateSearch`. */
export function parseAuditSearch(raw: Record<string, unknown>): AuditSearch {
  return {
    range: oneOf<QuickRange>(RANGES, raw.range),
    from: offsetIso(raw.from),
    to: offsetIso(raw.to),
    kind: oneOf<AuditKind>(KINDS, raw.kind),
    users: strings(raw.users),
    result: allowed<LogOutcome>(OUTCOMES, raw.result),
    channel: oneOf<Channel>(CHANNELS, raw.channel),
    q: text(raw.q),
  };
}

const nonEmpty = <T>(a: readonly T[] | undefined): T[] | undefined => (a && a.length > 0 ? [...a] : undefined);

/** The API query for `s` at `now`: minute-aligned bounds, empty filters left out. */
export function toLogQuery(s: LogSearch, now: Date): LogQuery {
  const ip = s.ip?.trim();
  const q = s.q?.trim();
  return defined<LogQuery>({
    ...resolveRange(s, now),
    users: nonEmpty(s.users),
    cat: nonEmpty(s.cat),
    event: nonEmpty(s.event),
    outcome: nonEmpty(s.outcome),
    session: s.session,
    ip: ip ? ip : undefined,
    q: q ? q : undefined,
  });
}
