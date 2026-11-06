// Log counts over time as a hand-drawn SVG (W32, not Recharts): stacked by category group, selectable
// by dragging or from the keyboard, never animated. docs/design/screens/logs.md §2–§4, §8.
import { useMemo, useReducer, useState, type KeyboardEvent, type PointerEvent } from "react";
import { copy } from "@/copy/ko";
import type { LogCategory, LogHistogram as Histogram } from "@/lib/api-types";
import { formatKstShort } from "@/lib/time";
import { useElementWidth } from "@/lib/use-element-width";
import { CATEGORY_GROUP, GROUP_COLOR_VAR, GROUP_STACK, type LogGroup } from "./categories";
import { kstIso } from "./search";

type Stack = LogGroup | "none";
const NONE_COLOR = "var(--color-fg-muted)";
const NARROW = 480; // below this container width the axis keeps only its two ends
const LABEL_SLOT = 110; // px one axis label needs
const r2 = (n: number) => Math.round(n * 100) / 100; // fewer SVG digits (rendering-svg-precision)

// ---- time labels (shared with the timeline) ---------------------------------------------

/** Whether `from`–`to` lies within one KST day (then labels drop the date). */
export function sameKstDay(from: string, to: string): boolean {
  return formatKstShort(from).slice(0, 5) === formatKstShort(new Date(Date.parse(to) - 1).toISOString()).slice(0, 5);
}

/** `HH:mm` within one day, `MM-DD HH:mm` across days. */
export function timeLabel(iso: string, oneDay: boolean): string {
  const s = formatKstShort(iso);
  return oneDay ? s.slice(6) : s;
}

/** Start and end (exclusive) of buckets lo..hi, the end cut at the histogram's own end. */
export function bucketSpan(data: Histogram, lo: number, hi: number): { from: string; to: string } {
  const end = Date.parse(data.starts[hi]!) + data.bucket_sec * 1000;
  return { from: data.starts[lo]!, to: end >= Date.parse(data.to) ? data.to : kstIso(end) };
}

// ---- data shaping --------------------------------------------------------------------------

interface Shaped {
  /** Groups present, bottom-up. */
  stacks: Stack[];
  counts: Map<Stack, number[]>;
  totals: number[];
  max: number;
}

function shape(data: Histogram): Shaped {
  const n = data.starts.length;
  const counts = new Map<Stack, number[]>();
  for (const s of data.series) {
    const g: Stack = s.key !== null && s.key in CATEGORY_GROUP ? CATEGORY_GROUP[s.key as LogCategory] : "none";
    const row = counts.get(g) ?? new Array<number>(n).fill(0);
    for (let i = 0; i < n; i++) row[i]! += s.counts[i] ?? 0;
    counts.set(g, row);
  }
  const stacks = [...GROUP_STACK, "none" as const].filter((g) => counts.get(g)?.some((c) => c > 0));
  const totals = Array.from({ length: n }, (_, i) => stacks.reduce((sum, g) => sum + counts.get(g)![i]!, 0));
  let max = 0;
  for (const t of totals) if (t > max) max = t;
  return { stacks, counts, totals, max };
}

const colorOf = (g: Stack) => (g === "none" ? NONE_COLOR : GROUP_COLOR_VAR[g]);
const nameOf = (g: Stack) => (g === "none" ? null : copy.logs.groups[g]);

// ---- keyboard selection ----------------------------------------------------------------------

interface Cursor {
  focus: number;
  /** Fixed end of a Shift selection; null = only the focused bucket. */
  anchor: number | null;
}

type Move = { to: number; extend: boolean } | { clear: true } | { reset: number };

function cursorReducer(c: Cursor, m: Move): Cursor {
  if ("reset" in m) return { focus: m.reset, anchor: null };
  // Escape: drop the selection and go back to where it started (F19)
  if ("clear" in m) return c.anchor === null ? c : { focus: c.anchor, anchor: null };
  return { focus: m.to, anchor: m.extend ? (c.anchor ?? c.focus) : null };
}

const span = (a: number, b: number): [number, number] => (a <= b ? [a, b] : [b, a]);

export interface LogHistogramProps {
  data: Histogram;
  /** A selected span: bucket-aligned KST bounds, the end never past `data.to`. */
  onSelect(from: string, to: string): void;
  /** Shorter bars, no legend (cards, the audit screen). */
  compact?: boolean;
  /** Fixed width for tests and SSR; otherwise the container's width. */
  width?: number;
}

export function LogHistogram({ data, onSelect, compact = false, width }: LogHistogramProps) {
  const [wrapRef, W] = useElementWidth<HTMLDivElement>(width);
  const [cursor, move] = useReducer(cursorReducer, { focus: 0, anchor: null });
  const [drag, setDrag] = useState<{ a: number; b: number } | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [keyboard, setKeyboard] = useState(false); // the focus ring and tooltip follow keys, not clicks
  const [focused, setFocused] = useState(false);
  // new bars (an applied selection, another range): the keyboard starts again at the first one,
  // on the same element, so focus stays here between successive zooms
  const bars = `${data.from}|${data.to}|${data.bucket_sec}`;
  const [seenBars, setSeenBars] = useState(bars);
  if (bars !== seenBars) {
    setSeenBars(bars);
    move({ reset: 0 });
    setDrag(null);
    setHover(null);
  }

  const n = data.starts.length;
  // pointer moves re-render this; the series are folded once per answer
  const { stacks, counts, totals, max } = useMemo(() => shape(data), [data]);
  const oneDay = sameKstDay(data.from, data.to);
  const fmt = (iso: string) => timeLabel(iso, oneDay);
  const last = Math.max(0, n - 1);
  const focus = Math.min(cursor.focus, last);

  const TOP = compact ? 4 : 16; // room for the max label
  const PLOT = compact ? 40 : 112;
  const AXIS = 18;
  const H = TOP + PLOT + AXIS;
  const base = TOP + PLOT;
  const slot = n > 0 ? W / n : 0;
  const barW = Math.max(2, slot - 1); // W41: 2 px even with 200 bars in a 400 px container

  const indexAt = (clientX: number, el: Element) => {
    const rect = el.getBoundingClientRect();
    const i = Math.floor((clientX - rect.left) / (rect.width / n));
    return Math.min(last, Math.max(0, i));
  };

  const apply = (a: number, b: number) => {
    const [lo, hi] = span(a, b);
    const s = bucketSpan(data, lo, hi);
    onSelect(s.from, s.to);
  };

  const onPointerDown = (e: PointerEvent<SVGSVGElement>) => {
    if (e.button !== 0 || n === 0) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const i = indexAt(e.clientX, e.currentTarget);
    setKeyboard(false);
    setDrag({ a: i, b: i });
  };
  const onPointerMove = (e: PointerEvent<SVGSVGElement>) => {
    if (n === 0) return;
    const i = indexAt(e.clientX, e.currentTarget);
    if (drag) {
      if (drag.b !== i) setDrag({ a: drag.a, b: i });
    } else if (hover !== i) setHover(i);
  };
  const onPointerUp = (e: PointerEvent<SVGSVGElement>) => {
    if (!drag) return;
    const i = indexAt(e.clientX, e.currentTarget);
    setDrag(null);
    move({ reset: Math.min(drag.a, i) });
    apply(drag.a, i);
  };

  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    if (n === 0) return;
    const to = { ArrowLeft: focus - 1, ArrowRight: focus + 1, Home: 0, End: last }[e.key];
    if (to !== undefined) {
      e.preventDefault();
      move({ to: Math.min(last, Math.max(0, to)), extend: e.shiftKey });
    } else if (e.key === "Enter") {
      e.preventDefault();
      apply(cursor.anchor ?? focus, focus);
    } else if (e.key === "Escape" && cursor.anchor !== null) {
      e.preventDefault();
      move({ clear: true });
    } else {
      return;
    }
    setKeyboard(true);
  };

  // what is selected right now: the drag, else the keyboard span, else nothing drawn
  const sel = drag ? span(drag.a, drag.b) : cursor.anchor !== null ? span(cursor.anchor, focus) : null;
  const kbSpan = cursor.anchor !== null ? span(cursor.anchor, focus) : ([focus, focus] as [number, number]);
  const sum = (lo: number, hi: number) => totals.slice(lo, hi + 1).reduce((a, b) => a + b, 0);
  const live = keyboard && focused && n > 0 ? copy.logs.selection(fmt(data.starts[kbSpan[0]]!), fmt(bucketSpan(data, ...kbSpan).to), sum(...kbSpan)) : "";

  // the tooltip: the drag span, else the hovered bucket, else the keyboard span
  const tipSpan: [number, number] | null = drag ? span(drag.a, drag.b) : hover !== null ? [hover, hover] : keyboard && focused && n > 0 ? kbSpan : null;

  // axis labels: both ends always; in between, one per LABEL_SLOT px when the container is wide enough
  const labels: { x: number; text: string; anchor: "start" | "middle" | "end" }[] = [];
  if (n > 0) {
    labels.push({ x: 0, text: fmt(data.starts[0]!), anchor: "start" });
    if (!compact && W >= NARROW) {
      const step = Math.max(1, Math.ceil(n / Math.floor(W / LABEL_SLOT)));
      for (let i = step; i < n; i += step) {
        const x = i * slot;
        if (x < LABEL_SLOT * 0.75 || x > W - LABEL_SLOT * 0.75) continue;
        labels.push({ x, text: fmt(data.starts[i]!), anchor: "middle" });
      }
    }
    labels.push({ x: W, text: fmt(data.to), anchor: "end" });
  }

  const showLegend = !compact && stacks.length >= 2;

  return (
    <div className="flex min-w-0 flex-col gap-2" data-volatile="">
      <div ref={wrapRef} className="relative min-w-0">
        <svg
          data-testid="log-histogram"
          role="group"
          tabIndex={0}
          aria-label={copy.logs.histogramLabel(fmt(data.from), fmt(data.to), data.total)}
          width={W}
          height={H}
          className="block cursor-crosshair touch-none select-none"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={() => setDrag(null)}
          onPointerLeave={() => setHover(null)}
          onKeyDown={onKeyDown}
          onFocus={() => setFocused(true)}
          onBlur={() => {
            setFocused(false);
            setKeyboard(false);
          }}
        >
          <g aria-hidden="true">
            {/* max line: the only gridline (dataviz: recessive, one hairline) */}
            {!compact && max > 0 ? (
              <>
                <line x1={0} x2={W} y1={TOP + 0.5} y2={TOP + 0.5} stroke="var(--color-border)" />
                <text data-ytick="" x={0} y={TOP - 4} fontSize={11} fill="var(--color-fg-muted)" className="tabular-nums">
                  {max.toLocaleString("ko-KR")}
                </text>
              </>
            ) : null}
            <line x1={0} x2={W} y1={base + 0.5} y2={base + 0.5} stroke="var(--color-border-strong)" />
            {hover !== null && !drag ? (
              <rect x={r2(hover * slot)} y={TOP} width={r2(slot)} height={PLOT} fill="var(--color-hover)" />
            ) : null}
            {sel ? (
              <rect
                data-selection=""
                x={r2(sel[0] * slot)}
                y={TOP}
                width={r2((sel[1] - sel[0] + 1) * slot)}
                height={PLOT}
                fill="var(--color-selected)"
                stroke="var(--color-border-strong)"
              />
            ) : null}
            {max > 0
              ? totals.map((_, i) => {
                  let y = base;
                  return stacks.map((g, k) => {
                    const c = counts.get(g)![i]!;
                    if (c === 0) return null;
                    const h = Math.max(1, (c / max) * PLOT);
                    y -= h;
                    // a 1 px surface gap between touching segments (dataviz spacer, thinned for short bars)
                    const gap = k > 0 && h > 2 ? 1 : 0;
                    return (
                      <rect
                        key={`${i}-${g}`}
                        data-bucket={i}
                        data-group={g}
                        x={r2(i * slot)}
                        y={r2(y)}
                        width={r2(barW)}
                        height={r2(h - gap)}
                        fill={colorOf(g)}
                      />
                    );
                  });
                })
              : null}
            {keyboard && focused && n > 0 ? (
              <rect
                data-focus=""
                x={r2(focus * slot + 1)}
                y={TOP + 1}
                width={r2(Math.max(2, slot - 2))}
                height={PLOT - 2}
                fill="none"
                stroke="var(--color-focus)"
                strokeWidth={2}
              />
            ) : null}
            {labels.map((l) => (
              <text
                key={`${l.anchor}-${l.x}`}
                data-axis=""
                x={r2(l.x)}
                y={H - 4}
                textAnchor={l.anchor}
                fontSize={11}
                fill="var(--color-fg-muted)"
                className="tabular-nums"
              >
                {l.text}
              </text>
            ))}
          </g>
        </svg>
        {tipSpan ? <Tip data={data} span={tipSpan} slot={slot} W={W} fmt={fmt} stacks={stacks} counts={counts} /> : null}
      </div>
      {showLegend || !compact ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-muted">
          {showLegend ? (
            <ul aria-label={copy.logs.legend} className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {stacks.map((g) => (
                <li key={g} className="inline-flex items-center gap-1.5">
                  <span aria-hidden="true" className="size-2.5 rounded-xs" style={{ background: colorOf(g) }} />
                  {nameOf(g)}
                </li>
              ))}
            </ul>
          ) : null}
          <span className="tabular-nums">{copy.logs.total(data.total)}</span>
          {/* the drag is not discoverable otherwise; keyboard users get the same in the name */}
          {!compact ? <span aria-hidden="true">{copy.logs.dragHint}</span> : null}
        </div>
      ) : null}
      <div aria-live="polite" className="sr-only">
        {live}
      </div>
    </div>
  );
}

/** Hover / drag / keyboard tooltip: the span's times and counts. For the eye only (the live region speaks). */
function Tip({
  data, span: [lo, hi], slot, W, fmt, stacks, counts,
}: {
  data: Histogram;
  span: [number, number];
  slot: number;
  W: number;
  fmt(iso: string): string;
  stacks: Stack[];
  counts: Map<Stack, number[]>;
}) {
  const { from, to } = bucketSpan(data, lo, hi);
  const by = stacks.map((g) => [g, counts.get(g)!.slice(lo, hi + 1).reduce((a, b) => a + b, 0)] as const);
  const total = by.reduce((a, [, c]) => a + c, 0);
  const center = ((lo + hi + 1) / 2) * slot;
  const left = center < W / 2;
  return (
    <div
      data-testid="log-histogram-tip"
      aria-hidden="true"
      className="pointer-events-none absolute top-0 z-(--z-popover) min-w-36 rounded-md border bg-surface-raised px-3 py-2 text-xs text-fg shadow-md"
      style={left ? { left: Math.max(0, center + 8) } : { right: Math.max(0, W - center + 8) }}
    >
      <div className="font-medium tabular-nums">{`${fmt(from)}–${fmt(to)}`}</div>
      <div className="tabular-nums">{copy.logs.count(total)}</div>
      {by.length > 1
        ? by.map(([g, c]) => (
            <div key={g} className="flex items-center gap-1.5 text-fg-muted">
              <span className="size-2 rounded-xs" style={{ background: colorOf(g) }} />
              <span>{nameOf(g)}</span>
              <span className="ml-auto pl-3 text-fg tabular-nums">{c.toLocaleString("ko-KR")}</span>
            </div>
          ))
        : null}
    </div>
  );
}
