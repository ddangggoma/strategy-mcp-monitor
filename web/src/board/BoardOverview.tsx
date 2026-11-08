import { ActivityIcon, ChartPieIcon, ListChecksIcon, ShieldCheckIcon, type LucideIcon } from "lucide-react";
import { useMemo, type CSSProperties, type ReactNode } from "react";
import { RollingNumber } from "@/components/status/RollingNumber";
import { Sparkline } from "@/components/status/Sparkline";
import { STATE_ICONS } from "@/components/status/StatusBadge";
import { copy } from "@/copy/ko";
import type { BoardItem, McpState } from "@/lib/api-types";
import type { StreamStatus } from "@/lib/board-stream";
import { useClock } from "@/lib/clock";
import { relativeKo } from "@/lib/time";
import { cn } from "@/lib/utils";
import {
  CHECK_TONE,
  STATES_BY_SEVERITY,
  UPTIME_TONE,
  overview,
  percent,
  stepTone,
  toneOf,
  type Overview,
  type Tone,
} from "./overview";
import "./BoardOverview.css";

/** A tile's place in the entrance sequence (the verdict row is 0). */
const rise = (i: number) => ({ "--rise-i": i }) as CSSProperties;

/** The board state a tone stands for: tones borrow the state hues, never a new one. */
const TONE_STATE: Record<Tone, McpState> = { good: "HEALTHY", warn: "SUSPECT", bad: "FAILED" };

/** A tile's own hue (tokens.css --color-metric-*): its chip, edge, wash and line. Never a state. */
export type Accent = "states" | "latency" | "checks" | "uptime" | "cpu" | "memory" | "gpu" | "disk" | "network";

function Tile({
  title,
  icon: Icon,
  tone,
  accent,
  index,
  children,
  className,
}: {
  title: string;
  icon: LucideIcon;
  /** The tile's verdict: a problem state takes over its band, edge and wash; null leaves it to its hue. */
  tone: McpState | null;
  accent: Accent;
  index: number;
  children: ReactNode;
  className?: string;
}) {
  return (
    <li data-anim="rise" data-tone={tone ?? undefined} data-accent={accent} style={rise(index)} className={cn("ov-tile", className)}>
      <h2 className="flex items-center gap-2 text-sm font-medium text-fg-muted">
        <span aria-hidden="true" className="ov-chip">
          <Icon className="size-4" />
        </span>
        {title}
      </h2>
      {children}
    </li>
  );
}

function Metric({ children }: { children: ReactNode }) {
  return <p className="ov-metric">{children}</p>;
}

function Sub({ children }: { children: ReactNode }) {
  return <p className="truncate text-xs text-fg-muted">{children}</p>;
}

// ---- state distribution --------------------------------------------------------------

const R = 42;
/** Gap between two segments, in pathLength units (100 = the whole ring). */
const GAP = 1.6;

/** A ring of state segments, worst first from 12 o'clock, with the healthy share in the middle. */
function Donut({ o }: { o: Overview }) {
  const parts = STATES_BY_SEVERITY.filter((s) => (o.counts.get(s) ?? 0) > 0);
  const label = copy.board.overview.donutLabel(parts.map((s) => copy.board.overview.donutPart(copy.states[s], o.counts.get(s)!)).join(", "));
  const gap = parts.length > 1 ? GAP : 0;
  // each segment starts where the ones before it end
  const segments = parts.map((s, i) => {
    const before = parts.slice(0, i).reduce((sum, p) => sum + (o.counts.get(p) ?? 0), 0);
    const len = Math.max(0, ((o.counts.get(s) ?? 0) / o.total) * 100 - gap);
    return { s, start: (before / o.total) * 100, len };
  });
  return (
    <div className="ov-donut">
      <svg role="img" aria-label={label} viewBox="0 0 100 100" className="size-full">
        <circle cx="50" cy="50" r={R} className="ov-donut-track" />
        <g transform="rotate(-90 50 50)">
          {segments.map(({ s, start, len }) => (
            <circle
              key={s}
              cx="50"
              cy="50"
              r={R}
              pathLength={100}
              data-state={s}
              className="ov-donut-seg"
              style={{ strokeDasharray: `${len} ${100 - len}`, strokeDashoffset: -start }}
            />
          ))}
        </g>
      </svg>
      <div aria-hidden="true" className="ov-donut-center">
        <span className="text-2xl font-semibold text-fg tabular-nums">
          {o.counts.get("HEALTHY") ?? 0}
          <span className="text-base font-medium text-fg-muted">/{o.total}</span>
        </span>
        <span className="text-xs text-fg-muted">{copy.states.HEALTHY}</span>
      </div>
    </div>
  );
}

function Distribution({ o }: { o: Overview }) {
  // healthy always shows (a zero there is news); other states only when present
  const rows = STATES_BY_SEVERITY.filter((s) => s === "HEALTHY" || (o.counts.get(s) ?? 0) > 0);
  return (
    <div className="flex items-center gap-5">
      <Donut o={o} />
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <p className="text-sm text-fg">{copy.board.overview.healthyOf(o.counts.get("HEALTHY") ?? 0, o.total)}</p>
        <ul className="flex flex-col gap-1">
          {rows.map((s) => {
            const Icon = STATE_ICONS[s];
            const n = o.counts.get(s) ?? 0;
            return (
              <li key={s} data-state={s} className="ov-legend-row">
                <Icon aria-hidden="true" className="ov-legend-icon size-3.5 shrink-0" />
                <span className="flex-1 truncate">{copy.states[s]}</span>
                <span className="font-semibold text-fg tabular-nums">{n}</span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

// ---- check strip ------------------------------------------------------------------------

/** One cell per check step, oldest left: every MCP answered, some did not, most did not. */
function CheckStrip({ o }: { o: Overview }) {
  const failed = o.checks.reduce((n, c) => n + (c.total - c.ok), 0);
  const last = o.checks.length - 1;
  return (
    <div className="flex flex-col gap-1">
      <div role="img" aria-label={copy.board.overview.checkStripLabel(o.checks.length, failed)} className="ov-strip">
        {o.checks.map((c, i) => (
          <span
            key={i}
            title={copy.board.overview.checkStep(last - i, c.ok, c.total)}
            data-state={TONE_STATE[stepTone(c)]}
            className="ov-strip-cell"
            style={{ "--cell-i": i } as CSSProperties}
          />
        ))}
      </div>
      <div aria-hidden="true" className="flex justify-between text-[0.6875rem] text-fg-muted">
        <span>{copy.board.overview.older}</span>
        <span>{copy.board.overview.newer}</span>
      </div>
    </div>
  );
}

// ---- live status -----------------------------------------------------------------------

function LastCheckAgo({ at }: { at: string }) {
  const { wall } = useClock();
  return (
    <time dateTime={at} data-volatile="">
      {copy.board.overview.lastCheck(relativeKo(at, new Date(Math.max(wall, Date.parse(at)))))}
    </time>
  );
}

/** “● 실시간 · 마지막 점검 2초 전”: the stream is open and how fresh the newest check is. */
export function LiveStatus({ status, lastCheckAt, className }: { status: StreamStatus; lastCheckAt: string | null; className?: string }) {
  const open = status === "open";
  return (
    <p className={cn("ov-live", className)} data-live={open ? "on" : "off"}>
      <span aria-hidden="true" className="ov-live-dot" data-anim={open ? "pulse" : undefined} />
      <span className="font-medium text-fg">{open ? copy.board.overview.live : copy.board.overview.waiting}</span>
      {lastCheckAt ? (
        <>
          <span aria-hidden="true" className="text-fg-muted">
            ·
          </span>
          <LastCheckAgo at={lastCheckAt} />
        </>
      ) : null}
    </p>
  );
}

// ---- the overview ----------------------------------------------------------------------

/**
 * Four tiles between the verdict and the MCP cards: how the MCPs split over the states, the mean
 * response time with its recent trend, how many recent checks were answered, and the mean 24 h
 * uptime. Numbers come from the live board only; MCPs in maintenance are left out of the last
 * three (they are not checked). State colours carry the verdicts, each with an icon and a number
 * beside it; each tile also has its own metric hue (chip, edge, line), which never means a state.
 */
export function BoardOverview({ items }: { items: ReadonlyMap<number, BoardItem> }) {
  const o = useMemo(() => overview(items.values()), [items]);
  if (o.total === 0) return null;

  const checkTone = o.checkRate ? TONE_STATE[toneOf(o.checkRate.ratio, CHECK_TONE)] : null;
  const uptimeTone = o.uptime ? TONE_STATE[toneOf(o.uptime.avg, UPTIME_TONE)] : null;
  const checkPct = o.checkRate ? percent(o.checkRate.ratio) : null;
  const uptimePct = o.uptime ? percent(o.uptime.avg) : null;

  return (
    <section aria-label={copy.board.overview.title}>
      <ul className="ov-grid">
        <Tile title={copy.board.overview.distribution} icon={ChartPieIcon} tone={o.worst} accent="states" index={1} className="ov-tile-wide">
          <Distribution o={o} />
        </Tile>

        <Tile title={copy.board.overview.avgLatency} icon={ActivityIcon} tone={null} accent="latency" index={2}>
          <Metric>
            <RollingNumber value={o.latency ? o.latency.avg : null} unit="ms" />
          </Metric>
          <div className="ov-trend">
            <Sparkline points={o.latencyTrend} label={copy.board.overview.avgLatency} height={40} />
          </div>
          <Sub>{o.latency ? copy.board.overview.slowest(o.latency.maxName, Math.round(o.latency.max)) : copy.board.overview.noValue}</Sub>
        </Tile>

        <Tile title={copy.board.overview.checkRate} icon={ListChecksIcon} tone={checkTone} accent="checks" index={3}>
          <Metric>
            <RollingNumber value={checkPct} unit="%" decimals={checkPct === 100 ? 0 : 1} />
          </Metric>
          {o.checks.length > 0 ? <CheckStrip o={o} /> : null}
          <Sub>{o.checkRate ? copy.board.overview.checkSummary(o.checkRate.ok, o.checkRate.total) : copy.board.overview.noValue}</Sub>
        </Tile>

        <Tile title={copy.board.overview.avgUptime} icon={ShieldCheckIcon} tone={uptimeTone} accent="uptime" index={4}>
          <Metric>
            <RollingNumber value={uptimePct} unit="%" decimals={uptimePct === 100 ? 0 : 1} />
          </Metric>
          {o.uptime && uptimePct !== null ? (
            <div
              role="meter"
              aria-label={copy.board.overview.uptimeLabel(uptimePct)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={uptimePct}
              className="ov-meter"
              data-state={uptimeTone ?? undefined}
            >
              <span className="ov-meter-fill" style={{ "--meter": o.uptime.avg } as CSSProperties} />
            </div>
          ) : null}
          <Sub>{o.uptime ? copy.board.overview.lowest(o.uptime.minName, percent(o.uptime.min).toFixed(1)) : copy.board.overview.noValue}</Sub>
        </Tile>
      </ul>
      {(o.counts.get("MAINTENANCE") ?? 0) > 0 ? <p className="mt-2 text-xs text-fg-muted">{copy.board.overview.excludesMaintenance}</p> : null}
    </section>
  );
}
