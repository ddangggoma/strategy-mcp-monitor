import { CirclePauseIcon, PlayIcon } from "lucide-react";
import { m } from "motion/react";
import { useId } from "react";
import { InfoTip } from "@/components/app/InfoTip";
import { copy } from "@/copy/ko";
import type { BoardItem } from "@/lib/api-types";
import { useClock } from "@/lib/clock";
import { formatKst, relativeKo } from "@/lib/time";
import { CountdownBar } from "./CountdownBar";
import { McpIcon } from "./McpIcon";
import { RollingNumber } from "./RollingNumber";
import { Sparkline } from "./Sparkline";
import { StatusBadge } from "./StatusBadge";
import { UptimeMeter } from "./UptimeMeter";
import "./McpCard.css";

// --motion-slow with --ease-in-out: cards already on screen move to their new place (U17 reorder)
const REORDER = { duration: 0.36, ease: [0.77, 0, 0.175, 1] } as const;

function LastCheck({ at }: { at: string | null }) {
  const { wall } = useClock();
  if (at === null) return <span>—</span>;
  return (
    <time dateTime={at} title={formatKst(at)} data-volatile="">
      {relativeKo(at, new Date(Math.max(wall, Date.parse(at))))}
    </time>
  );
}

/**
 * One MCP on the board: icon and name, state, issue, latency, sparkline, 24 h uptime, last check; the
 * countdown only while the server runs one (`action_in_sec`, F23); a running script; maintenance.
 * Host, port and owner are never shown (anonymous screen). Rows line up across cards through
 * subgrid (McpCard.css); Motion `layout` glides the card when the board re-sorts (needs a
 * LazyMotion with domMax above; elsewhere it is a plain article).
 */
export function McpCard({ item, receivedAt }: { item: BoardItem; receivedAt: number }) {
  const nameId = useId();
  const recovering = item.state === "RECOVERING";
  return (
    <m.article
      layout="position"
      transition={REORDER}
      aria-labelledby={nameId}
      data-testid="mcp-card"
      data-id={item.id}
      data-state={item.state}
      data-anim={recovering ? "spin" : undefined}
      className="mcp-card"
    >
      <header className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          {/* the chosen icon, or the default MCP icon; decorative (the name is the label) */}
          <McpIcon icon={item.icon} />
          <h2 id={nameId} className="min-w-0 text-lg leading-tight font-semibold break-words">
            {item.name}
          </h2>
        </div>
        <StatusBadge state={item.state} />
      </header>

      <p className="flex items-center gap-0.5 text-sm font-medium text-fg">
        {item.issue ? (
          <>
            {copy.issues[item.issue]}
            <InfoTip label={copy.issues[item.issue]} content={copy.help.issues[item.issue]} />
          </>
        ) : null}
      </p>

      <dl className="mcp-card-metrics">
        <div>
          <dt className="flex items-center gap-0.5 text-xs text-fg-muted">
            {copy.board.latency}
            <InfoTip label={copy.board.latency} content={copy.help.latency} />
          </dt>
          <dd className="mcp-card-metric">
            <RollingNumber value={item.latency_ms} unit="ms" />
          </dd>
        </div>
        <div>
          <dt className="flex items-center gap-0.5 text-xs text-fg-muted">
            {copy.board.uptime24h}
            <InfoTip label={copy.board.uptime24h} content={copy.help.uptime} />
          </dt>
          <dd className="mcp-card-metric">
            <UptimeMeter value={item.uptime_24h} />
          </dd>
        </div>
      </dl>

      <div className="flex flex-col gap-2 self-end">
        <Sparkline points={item.sparkline} label={copy.board.sparklineLabel(item.name)} className="mcp-card-spark" />
        {item.action_in_sec !== null ? (
          <div className="flex items-center gap-1">
            <CountdownBar inSec={item.action_in_sec} totalSec={item.action_delay_sec} receivedAt={receivedAt} className="min-w-0 flex-1" />
            <InfoTip label={copy.board.autoAction} content={copy.help.countdown} />
          </div>
        ) : null}
      </div>

      <footer className="flex flex-col gap-1 text-xs text-fg-muted">
        {item.running ? (
          <p className="flex items-center gap-1.5 font-medium text-fg">
            <PlayIcon aria-hidden="true" className="size-3.5" />
            {copy.board.running(item.running)}
          </p>
        ) : null}
        {item.maintenance ? (
          <p className="flex items-center gap-1.5">
            <CirclePauseIcon aria-hidden="true" className="size-3.5" />
            {copy.board.maintenanceOn}
          </p>
        ) : null}
        <p>
          {copy.board.lastCheck} <LastCheck at={item.last_check_at} />
        </p>
      </footer>
    </m.article>
  );
}
