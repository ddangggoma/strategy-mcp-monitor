import { copy } from "@/copy/ko";
import { cn } from "@/lib/utils";

export interface SparklineProps {
  points: (number | null)[];
  width?: number;
  height?: number;
  label: string;
  className?: string;
}

const PAD = 2; // keeps the 2px stroke inside the box
const r1 = (n: number) => Math.round(n * 10) / 10; // one decimal is plenty for a 120×32 box

interface Geometry {
  line: string;
  gaps: string;
  avg: number | null;
  max: number | null;
}

/**
 * Line path with one subpath per run of values (null = failed check breaks the line), plus a
 * floor mark under every null run so a gap never reads as "fine". The y axis starts at 0 and
 * tops out at 110% of the max, so small jitter does not look like a spike (dataviz).
 */
function geometry(points: (number | null)[], w: number, h: number): Geometry {
  let sum = 0;
  let n = 0;
  let max = 0;
  for (const p of points) {
    if (p === null) continue;
    sum += p;
    n++;
    if (p > max) max = p;
  }
  const top = max > 0 ? max * 1.1 : 1;
  const step = points.length > 1 ? w / (points.length - 1) : 0;
  const x = (i: number) => r1(points.length > 1 ? i * step : w / 2);
  const y = (v: number) => r1(h - PAD - (v / top) * (h - 2 * PAD));
  const floor = h - PAD / 2;

  let line = "";
  let gaps = "";
  let runStart = -1; // index of the first value in the current run
  let gapStart = -1; // index of the first null in the current null run
  points.forEach((p, i) => {
    if (p === null) {
      if (runStart !== -1 && i - 1 === runStart) line += "h0.01"; // a lone point still shows as a dot
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
      line += `M${x(i)} ${y(p)}`;
    } else {
      line += `L${x(i)} ${y(p)}`;
    }
  });
  if (runStart !== -1 && runStart === points.length - 1) line += "h0.01";
  if (gapStart !== -1) gaps += `M${x(Math.max(0, gapStart - 1))} ${floor}H${x(points.length - 1)}`;

  return { line, gaps, avg: n ? Math.round(sum / n) : null, max: n ? Math.round(max) : null };
}

/** Hand-drawn latency sparkline (U18: no chart library on the board). Color = `currentColor`. */
export function Sparkline({ points, width = 120, height = 32, label, className }: SparklineProps) {
  const g = geometry(points, width, height);
  const name =
    g.avg === null || g.max === null ? `${label}: ${copy.board.noData}` : copy.board.sparklineSummary(label, g.avg, g.max);
  return (
    <svg
      role="img"
      aria-label={name}
      data-volatile=""
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={cn("block w-full overflow-visible", className)}
      style={{ height }}
    >
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
