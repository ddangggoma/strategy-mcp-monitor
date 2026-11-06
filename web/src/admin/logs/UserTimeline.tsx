import { useRef, useState, type KeyboardEvent } from "react";
import { copy } from "@/copy/ko";
import type { LogHistogram, LogQuery } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { useLogHistogram } from "../queries";
import { bucketSpan, sameKstDay, timeLabel } from "./LogHistogram";

const OTHER = "__other__";
const MIN_SHADE = 12; // % accent for the smallest non-zero cell, so one line is still visible

interface Lane {
  key: string | null;
  name: string;
  counts: number[];
  total: number;
  /** A real user: the lane links to that user's table. */
  linked: boolean;
}

function lanes(data: LogHistogram): Lane[] {
  const out = data.series.map((s) => ({
    key: s.key,
    name: s.key === null ? copy.logs.noUser : s.key === OTHER ? copy.logs.otherUsers : s.key,
    counts: s.counts,
    total: s.counts.reduce((a, b) => a + b, 0),
    linked: s.key !== null && s.key !== OTHER,
  }));
  // people first by activity; "other" and "no user" at the end
  return out.toSorted((a, b) => Number(b.linked) - Number(a.linked) || b.total - a.total);
}

/**
 * One row per user over the same buckets as the histogram: a strip of cells whose shade is the
 * line count (accent mixed into transparent, so light and dark themes both work). A cell opens that
 * user's table for that bucket. Lanes use a roving tabindex: ↑/↓ between lanes, ←/→ between cells.
 */
export function UserTimeline({
  query, buckets, onOpen,
}: {
  query: LogQuery;
  buckets: number;
  onOpen(user: string, from: string, to: string): void;
}) {
  const { data, isPending, isError, isPlaceholderData } = useLogHistogram(query, "user", buckets, { enabled: buckets > 0 });

  if (isPending) {
    return (
      <div role="status" className="flex flex-col gap-2">
        <span className="sr-only">{copy.common.loading}</span>
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} aria-hidden="true" className="h-8 rounded-sm bg-selected" />
        ))}
      </div>
    );
  }
  if (isError && !data) {
    return (
      <p role="alert" className="text-sm text-fg">
        {copy.logs.loadError}
      </p>
    );
  }
  const all = lanes(data);
  if (all.every((l) => l.total === 0)) return <p className="text-sm text-fg-muted">{copy.logs.empty}</p>;
  return <Lanes data={data} lanes={all} stale={isPlaceholderData} onOpen={onOpen} />;
}

function Lanes({ data, lanes: all, stale, onOpen }: { data: LogHistogram; lanes: Lane[]; stale: boolean; onOpen(user: string, from: string, to: string): void }) {
  const n = data.starts.length;
  const last = Math.max(0, n - 1);
  const linked = all.filter((l) => l.linked);
  const [active, setActive] = useState(0); // index into `linked`
  const [cell, setCell] = useState(0);
  const [keyboard, setKeyboard] = useState(false);
  const refs = useRef<(HTMLDivElement | null)[]>([]);
  const oneDay = sameKstDay(data.from, data.to);
  const fmt = (iso: string) => timeLabel(iso, oneDay);

  // people share one scale (the busiest person's busiest cell). "Other users" sums many people and
  // "no user" is not a person: each is shaded against itself, in muted ink, so neither washes the
  // real lanes out or competes with them
  let max = 0;
  for (const l of linked) for (const c of l.counts) if (c > max) max = c;
  const laneMax = (l: Lane) => (l.linked ? max : Math.max(0, ...l.counts));

  const open = (lane: Lane, i: number) => {
    const s = bucketSpan(data, i, i);
    onOpen(lane.key!, s.from, s.to);
  };

  const onKey = (e: KeyboardEvent<HTMLDivElement>, li: number) => {
    const lane = linked[li]!;
    let nextCell = cell;
    let nextLane = li;
    if (e.key === "ArrowRight") nextCell = Math.min(last, cell + 1);
    else if (e.key === "ArrowLeft") nextCell = Math.max(0, cell - 1);
    else if (e.key === "Home") nextCell = 0;
    else if (e.key === "End") nextCell = last;
    else if (e.key === "ArrowDown") nextLane = Math.min(linked.length - 1, li + 1);
    else if (e.key === "ArrowUp") nextLane = Math.max(0, li - 1);
    else if (e.key === "Enter") {
      e.preventDefault();
      open(lane, cell);
      return;
    } else return;
    e.preventDefault();
    setKeyboard(true);
    setCell(nextCell);
    if (nextLane !== li) {
      setActive(nextLane);
      refs.current[nextLane]?.focus();
    }
  };

  const activeLane = linked[Math.min(active, linked.length - 1)];
  const live =
    keyboard && activeLane
      ? copy.logs.selection(fmt(data.starts[cell]!), fmt(bucketSpan(data, cell, cell).to), activeLane.counts[cell] ?? 0)
      : "";

  return (
    <div
      aria-busy={stale || undefined}
      className={cn("@container/timeline flex min-w-0 flex-col gap-1 rounded-md border bg-surface p-3", stale && "opacity-60")}
      data-volatile=""
    >
      <div className="grid gap-x-3 @min-[36rem]/timeline:grid-cols-[12rem_minmax(0,1fr)]">
        <span aria-hidden="true" className="hidden @min-[36rem]/timeline:block" />
        <div aria-hidden="true" className="flex justify-between text-xs text-fg-muted tabular-nums">
          <span>{fmt(data.from)}</span>
          <span>{fmt(data.to)}</span>
        </div>
      </div>
      {all.map((lane) => {
        const li = linked.indexOf(lane);
        const focusable = li >= 0;
        return (
          // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- a keyboard lane (roving tabindex); cells are its pointer targets
          <div
            key={lane.key ?? "\u0000null"}
            ref={focusable ? (el) => void (refs.current[li] = el) : undefined}
            role="group"
            aria-label={copy.logs.timelineLane(lane.name, lane.total)}
            tabIndex={focusable ? (li === Math.min(active, linked.length - 1) ? 0 : -1) : undefined}
            onKeyDown={focusable ? (e) => onKey(e, li) : undefined}
            onFocus={focusable ? () => setActive(li) : undefined}
            onBlur={(e) => {
              // moving between lanes keeps the keyboard cell; leaving the timeline drops it
              if (!e.currentTarget.parentElement?.contains(e.relatedTarget)) setKeyboard(false);
            }}
            className="grid items-center gap-x-3 gap-y-1 rounded-sm py-1 focus-visible:-outline-offset-1 @min-[36rem]/timeline:grid-cols-[12rem_minmax(0,1fr)]"
          >
            <div aria-hidden="true" className="flex min-w-0 items-baseline justify-between gap-2 text-sm">
              <span className={cn("truncate", !lane.linked && "text-fg-muted")}>{lane.name}</span>
              <span className="shrink-0 text-xs text-fg-muted tabular-nums">{copy.logs.count(lane.total)}</span>
            </div>
            <div
              aria-hidden="true"
              className="grid h-5 gap-px rounded-xs bg-sunken"
              style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}
            >
              {lane.counts.map((c, i) => {
                const pct = c === 0 ? 0 : Math.min(100, Math.max(MIN_SHADE, Math.round((c / laneMax(lane)) * 100)));
                const ink = lane.linked ? "var(--color-accent)" : "var(--color-fg-muted)";
                const isActive = keyboard && focusable && li === active && i === cell;
                return (
                  // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions -- the lane's ←/→/Enter is the keyboard path
                  <div
                    key={i}
                    data-cell={i}
                    data-shade={pct > 0 ? `${ink} ${pct}%` : undefined}
                    onClick={lane.linked ? () => open(lane, i) : undefined}
                    className={cn(
                      "min-w-0",
                      lane.linked && "cursor-pointer hover:outline hover:outline-1 hover:outline-fg-muted",
                      isActive && "outline-2 outline-focus outline-solid",
                    )}
                    style={pct > 0 ? { background: `color-mix(in oklch, ${ink} ${pct}%, transparent)` } : undefined}
                    title={lane.linked ? `${fmt(data.starts[i]!)} ${copy.logs.count(c)}` : undefined}
                  />
                );
              })}
            </div>
          </div>
        );
      })}
      <div aria-live="polite" className="sr-only">
        {live}
      </div>
    </div>
  );
}
