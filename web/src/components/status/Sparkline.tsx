import { useId } from "react";
import { copy } from "@/copy/ko";
import { cn } from "@/lib/utils";

export interface SparklineProps {
  points: (number | null)[];
  width?: number;
  height?: number;
  label: string;
  /** A fixed top of the y axis (100 for percentages); default 110 % of the largest value. */
  max?: number;
  /** The accessible summary from label, average and maximum (default: milliseconds). */
  summary?: (label: string, avg: number, max: number) => string;
  className?: string;
}

const PAD = 2; // keeps the 2px stroke inside the box
const r1 = (n: number) => Math.round(n * 10) / 10; // one decimal is plenty for a 120×32 box

interface Geometry {
  line: string;
  /** Each run of the line closed down to the bottom edge: the soft fill under it. */
  area: string;
  gaps: string;
  avg: number | null;
  max: number | null;
}

/**
 * Line path with one subpath per run of values (null = failed check breaks the line), plus a
 * floor mark under every null run so a gap never reads as "fine". The y axis starts at 0 and
 * tops out at 110% of the max, so small jitter does not look like a spike (dataviz).
 */
function geometry(points: (number | null)[], w: number, h: number, fixedTop?: number): Geometry {
  let sum = 0;
  let n = 0;
  let max = 0;
  for (const p of points) {
    if (p === null) continue;
    sum += p;
    n++;
    if (p > max) max = p;
  }
  const top = fixedTop ?? (max > 0 ? max * 1.1 : 1);
  const step = points.length > 1 ? w / (points.length - 1) : 0;
  const x = (i: number) => r1(points.length > 1 ? i * step : w / 2);
  const y = (v: number) => r1(h - PAD - (v / top) * (h - 2 * PAD));
  const floor = h - PAD / 2;

  let line = "";
  let area = "";
  let run = ""; // the current run's points, for its area
  let runX = 0; // x of the current run's first point
  let lastX = 0;
  const closeRun = () => {
    if (run && lastX > runX) area += `M${runX} ${h}${run}L${lastX} ${h}Z`;
    run = "";
  };
  let gaps = "";
  let runStart = -1; // index of the first value in the current run
  let gapStart = -1; // index of the first null in the current null run
  points.forEach((p, i) => {
    if (p === null) {
      if (runStart !== -1 && i - 1 === runStart) line += "h0.01"; // a lone point still shows as a dot
      closeRun();
      runStart = -1;
      if (gapStart === -1) gapStart = i;
      return;
    }
    if (gapStart !== -1) {
      gaps += `M${x(Math.max(0, gapStart - 1))} ${floor}H${x(i)}`;
      gapStart = -1;
    }
    if (runStart === -1) {
      runStart = i;
      runX = x(i);
      line += `M${x(i)} ${y(p)}`;
    } else {
      line += `L${x(i)} ${y(p)}`;
    }
    run += `L${x(i)} ${y(p)}`;
    lastX = x(i);
  });
  closeRun();
  if (runStart !== -1 && runStart === points.length - 1) line += "h0.01";
  if (gapStart !== -1) gaps += `M${x(Math.max(0, gapStart - 1))} ${floor}H${x(points.length - 1)}`;

  return { line, area, gaps, avg: n ? Math.round(sum / n) : null, max: n ? Math.round(max) : null };
}

/**
 * Hand-drawn latency sparkline (U18: no chart library on the board). Color = `currentColor`: the
 * line, a soft fill fading toward the bottom, and dashed floor marks for failed checks. It draws in
 * from the left when it first shows (a clip-path reveal, data-anim="draw"; off for reduced motion).
 */
export function Sparkline({
  points,
  width = 120,
  height = 32,
  label,
  max,
  summary = copy.board.sparklineSummary,
  className,
}: SparklineProps) {
  const g = geometry(points, width, height, max);
  // useId's punctuation is not safe inside url(#…)
  const fillId = `spark-fill${useId().replace(/[^\w-]/g, "")}`;
  const name =
    g.avg === null || g.max === null ? `${label}: ${copy.board.noData}` : summary(label, g.avg, g.max);
  return (
    <svg
      role="img"
      aria-label={name}
      data-volatile=""
      data-anim="draw"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={cn("spark-draw block w-full overflow-visible", className)}
      style={{ height }}
    >
      <defs>
        <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="currentColor" stopOpacity={0.3} />
          <stop offset="1" stopColor="currentColor" stopOpacity={0} />
        </linearGradient>
      </defs>
      <path data-part="area" d={g.area} fill={`url(#${fillId})`} stroke="none" />
      <path
        data-part="gap"
        d={g.gaps}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeDasharray="2 3"
        strokeOpacity={0.7}
        vectorEffect="non-scaling-stroke"
      />
      <path
        data-part="line"
        d={g.line}
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
