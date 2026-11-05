// The history chart (its own lazy chunk: Recharts never reaches the board or the admin entry, U18).
// dataviz: one y-scale per plot, so latency (ms) and uptime (%) are two plots stacked on one time
// axis with a shared crosshair (syncId) instead of a dual-axis chart. Hue stays reserved for state
// (direction.md): the latency lines are neutral (avg = fg 2px, max = fg-muted, thinner), and only
// the transition rules carry a state color — the color of the state the MCP moved to. Text and the
// tooltip use text tokens. No animation anywhere (isAnimationActive={false}).
import { useMemo } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";
import { copy } from "@/copy/ko";
import type { McpState, MinuteBucket, Transition } from "@/lib/api-types";
import { formatKst } from "@/lib/time";
import { downsample } from "./downsample";
import { CHART_HEIGHT } from "./history-config";

const STRIP_HEIGHT = 84; // uptime plot + the time axis band
const PLOT_HEIGHT = CHART_HEIGHT - STRIP_HEIGHT;
const Y_WIDTH = 56; // both plots: their x ranges line up
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const KST_OFFSET = 9 * HOUR;

const STATE_STROKE: Record<McpState, string> = {
  HEALTHY: "var(--color-state-healthy)",
  SUSPECT: "var(--color-state-suspect)",
  ACTION: "var(--color-state-action)",
  RECOVERING: "var(--color-state-recovering)",
  FAILED: "var(--color-state-failed)",
  MAINTENANCE: "var(--color-state-maintenance)",
};

const TICK = { fill: "var(--color-fg-muted)", fontSize: 12 } as const;
const CURSOR = { stroke: "var(--color-border-strong)", strokeWidth: 1 } as const;

interface Point {
  t: number;
  avg: number | null;
  max: number | null;
  /** percent 0–100 */
  uptime: number | null;
}

/** Clock-friendly tick steps; the chart uses the smallest that keeps about six ticks on the span shown. */
const TICK_STEPS = [1, 5, 10, 15, 30, 60, 120, 180, 360, 720, 1440].map((m) => m * MINUTE);
const MAX_TICKS = 6;

/** The step for the data actually shown (a new MCP has minutes of data even in the 7-day view). */
export function tickStep(span: number): number {
  return TICK_STEPS.find((s) => span / s <= MAX_TICKS) ?? Math.ceil(span / MAX_TICKS / DAY) * DAY;
}

function ticksFor(min: number, max: number, step: number): number[] {
  const out: number[] = [];
  // first KST boundary at or after min
  let t = Math.ceil((min + KST_OFFSET) / step) * step - KST_OFFSET;
  for (; t <= max; t += step) out.push(t);
  return out;
}

const iso = (t: number) => new Date(t).toISOString();
const clock = (t: number) => formatKst(iso(t)).slice(11, 16); // HH:mm
const day = (t: number) => formatKst(iso(t)).slice(5, 10); // MM-DD
const dayClock = (t: number) => formatKst(iso(t)).slice(5, 16); // MM-DD HH:mm

export function LatencyChart({
  mcpId,
  buckets,
  transitions,
}: {
  mcpId: number;
  buckets: MinuteBucket[];
  transitions: Transition[];
}) {
  const points = useMemo<Point[]>(
    () =>
      downsample(buckets).map((p) => ({
        t: Date.parse(p.at),
        avg: p.avg,
        max: p.max,
        uptime: p.uptime === null ? null : p.uptime * 100,
      })),
    [buckets],
  );
  const first = points[0]?.t ?? 0;
  const last = points.at(-1)?.t ?? 0;
  // one point still needs a span to draw on
  const lo = first === last ? first - MINUTE : first;
  const hi = first === last ? last + MINUTE : last;
  const domain: [number, number] = [lo, hi];
  const step = tickStep(hi - lo);
  const ticks = useMemo(() => ticksFor(lo, hi, step), [lo, hi, step]);
  const marks = useMemo(
    () => transitions.map((tr) => ({ t: Date.parse(tr.at), to: tr.to })).filter((m) => m.t >= lo && m.t <= hi),
    [transitions, lo, hi],
  );
  // whole days read as dates; a span over a day needs the date next to the time
  const tickLabel = step >= DAY ? day : hi - lo > 20 * HOUR ? dayClock : clock;
  const sync = `mcp-history-${mcpId}`;

  // Recharts flattens children with an older react-is that does not see React 19 fragments:
  // reference lines are passed as a plain array, never inside a fragment
  const rules = (key: string) =>
    marks.map((m, i) => (
      <ReferenceLine
        key={`${key}-${m.t}-${i}`}
        x={m.t}
        stroke={STATE_STROKE[m.to]}
        strokeWidth={1}
        ifOverflow="discard"
      />
    ));

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <Legend />
      <div data-volatile="" style={{ height: CHART_HEIGHT }}>
        <ResponsiveContainer width="100%" height={PLOT_HEIGHT} initialDimension={{ width: 800, height: PLOT_HEIGHT }}>
          <ComposedChart data={points} syncId={sync} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} title={copy.mcp.chartTitle}>
            <CartesianGrid vertical={false} stroke="var(--color-border)" />
            <XAxis dataKey="t" type="number" domain={domain} ticks={ticks} hide />
            <YAxis
              width={Y_WIDTH}
              tick={TICK}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
              tickFormatter={(v: number) => copy.common.units.ms(v)}
            />
            <Tooltip content={(p) => <ChartTooltip {...p} />} cursor={CURSOR} isAnimationActive={false} />
            {rules("lat")}
            <Line
              dataKey="max"
              name={copy.mcp.chartMax}
              stroke="var(--color-fg-muted)"
              strokeWidth={1.5}
              dot={false}
              activeDot={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="avg"
              name={copy.mcp.chartAvg}
              stroke="var(--color-fg)"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              dot={false}
              activeDot={{ r: 4, fill: "var(--color-fg)", stroke: "var(--color-surface)", strokeWidth: 2 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
        <ResponsiveContainer width="100%" height={STRIP_HEIGHT} initialDimension={{ width: 800, height: STRIP_HEIGHT }}>
          <ComposedChart data={points} syncId={sync} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--color-border)" />
            <XAxis
              dataKey="t"
              type="number"
              domain={domain}
              ticks={ticks}
              tick={TICK}
              tickLine={false}
              axisLine={{ stroke: "var(--color-border)" }}
              tickFormatter={(t: number) => tickLabel(t)}
            />
            <YAxis
              width={Y_WIDTH}
              domain={[0, 100]}
              ticks={[0, 100]}
              tick={TICK}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) => copy.common.units.percent(v)}
            />
            {/* the crosshair follows the top plot; its tooltip already lists the uptime */}
            <Tooltip content={() => null} cursor={CURSOR} isAnimationActive={false} />
            {rules("up")}
            <Area
              dataKey="uptime"
              name={copy.mcp.chartUptime}
              type="stepAfter"
              stroke="var(--color-fg-muted)"
              strokeWidth={1.5}
              fill="var(--color-fg)"
              fillOpacity={0.1}
              activeDot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/** Line keys for lines, a filled key for the area, a short rule for transitions (dataviz: legend mirrors the mark). */
function Legend() {
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-fg-muted">
      <li className="inline-flex items-center gap-1.5">
        <span aria-hidden="true" className="h-0.5 w-4 rounded-full bg-fg" />
        {copy.mcp.chartAvg}
      </li>
      <li className="inline-flex items-center gap-1.5">
        <span aria-hidden="true" className="h-px w-4 bg-fg-muted" />
        {copy.mcp.chartMax}
      </li>
      <li className="inline-flex items-center gap-1.5">
        <span aria-hidden="true" className="size-3 rounded-[2px] border border-fg-muted bg-fg/10" />
        {copy.mcp.chartUptime}
      </li>
      <li className="inline-flex items-center gap-1.5">
        <span aria-hidden="true" className="h-3 w-px bg-fg-muted" />
        {copy.mcp.chartTransition}
      </li>
    </ul>
  );
}

const fmtMs = (v: number | null) => (v === null ? copy.common.none : copy.common.units.ms(Math.round(v)));

/** Values lead, labels follow; every series at this time (dataviz interaction rules). */
function ChartTooltip({ active, payload }: Pick<TooltipContentProps, "active" | "payload">) {
  const p = payload?.[0]?.payload as Point | undefined;
  if (!active || !p) return null;
  const rows: [string, string, string][] = [
    [fmtMs(p.avg), copy.mcp.chartAvg, "h-0.5 bg-fg"],
    [fmtMs(p.max), copy.mcp.chartMax, "h-px bg-fg-muted"],
    [p.uptime === null ? copy.common.none : copy.common.units.percent(p.uptime.toFixed(1)), copy.mcp.chartUptime, "h-1.5 bg-fg/20"],
  ];
  return (
    <div className="flex min-w-36 flex-col gap-1.5 rounded-md border bg-surface-raised px-3 py-2 text-xs shadow-md">
      <p className="font-mono text-fg-muted">{formatKst(iso(p.t)).slice(0, 16)}</p>
      <ul className="flex flex-col gap-1">
        {rows.map(([value, label, key]) => (
          <li key={label} className="flex items-center gap-2">
            <span aria-hidden="true" className={`w-3 shrink-0 ${key}`} />
            <span className="font-semibold text-fg tabular-nums">{value}</span>
            <span className="text-fg-muted">{label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
