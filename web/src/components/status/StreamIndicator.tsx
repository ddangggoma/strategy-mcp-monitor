import { RefreshCwIcon, UnplugIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { copy } from "@/copy/ko";
import type { StreamStatus } from "@/lib/board-stream";
import { cn } from "@/lib/utils";

/** Shown only after a reconnect has lasted this long: short blips should not flash a warning. */
const QUIET_MS = 3000;

function Late() {
  const [show, setShow] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setShow(true), QUIET_MS);
    return () => clearTimeout(t);
  }, []);
  if (!show) return null;
  return (
    <>
      <RefreshCwIcon aria-hidden="true" className="size-4 shrink-0" />
      <span className="max-sm:sr-only">{copy.stream.reconnecting}</span>
    </>
  );
}

/**
 * Live-stream health in the top bar. Silent while connecting or open; “다시 시도 중” once a
 * reconnect lasts 3 s (the status region is always present so screen readers hear the change).
 */
export function StreamIndicator({ status, className }: { status: StreamStatus; className?: string }) {
  return (
    <div role="status" className={cn("flex items-center gap-1.5 text-xs text-fg-muted", className)}>
      {status === "reconnecting" ? <Late /> : null}
      {status === "stopped" ? (
        <>
          <UnplugIcon aria-hidden="true" className="size-4 shrink-0" />
          <span className="max-sm:sr-only">{copy.stream.offline}</span>
        </>
      ) : null}
    </div>
  );
}
