import { useLayoutEffect, useRef } from "react";
import { copy } from "@/copy/ko";
import { useClock } from "@/lib/clock";
import { cn } from "@/lib/utils";
import "./CountdownBar.css";

export interface CountdownBarProps {
  /** Seconds left when the item was received (`action_in_sec`). */
  inSec: number;
  /** Full countdown length (`action_delay_sec`); null → `inSec` is the full length. */
  totalSec: number | null;
  /** performance.now() at receipt (BoardState.receivedAt). */
  receivedAt: number;
  className?: string;
}

function secondsLeft(inSec: number, receivedAt: number, now: number): number {
  return Math.max(0, inSec - Math.max(0, now - receivedAt) / 1000);
}

/**
 * Time left until the automatic action. Elapsed time is measured on this PC since receipt, so the
 * server's and the PC's clocks never have to agree (U8). The gauge drains with one CSS animation
 * (scaleX from --gauge-from to 0, length = seconds left; no per-frame JS, U25); the number ticks
 * once a second and is not announced (role=timer, aria-live=off).
 */
export function CountdownBar({ inSec, totalSec, receivedAt, className }: CountdownBarProps) {
  const { perf } = useClock();
  const total = totalSec ?? inSec;
  const left = Math.ceil(secondsLeft(inSec, receivedAt, perf));

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-state-suspect-soft">
        {/* a new receipt remounts the gauge, which restarts its animation from the new ratio */}
        <Gauge key={`${receivedAt}:${inSec}:${total}`} inSec={inSec} total={total} receivedAt={receivedAt} />
      </div>
      <span role="timer" aria-live="off" data-volatile="" className="shrink-0 text-xs font-medium text-fg" data-numeric="">
        {copy.board.actionIn(left)}
      </span>
    </div>
  );
}

function Gauge({ inSec, total, receivedAt }: { inSec: number; total: number; receivedAt: number }) {
  const ref = useRef<HTMLDivElement>(null);
  // before paint: the start ratio and length come from the time of mount, outside React's render
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const left = secondsLeft(inSec, receivedAt, performance.now());
    el.style.setProperty("--gauge-from", String(total > 0 ? Math.min(1, left / total) : 0));
    el.style.animationDuration = `${Math.round(left * 1000)}ms`;
  }, [inSec, total, receivedAt]);
  return <div ref={ref} data-testid="gauge" data-anim="countdown" data-volatile="" className="countdown-gauge h-full" />;
}
