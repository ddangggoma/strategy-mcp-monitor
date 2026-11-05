import { lazy, memo, Suspense, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { StatusBadge } from "@/components/status/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { copy } from "@/copy/ko";
import type { ActionRecord, McpHistory } from "@/lib/api-types";
import { formatDuration, formatKst } from "@/lib/time";
import { cn } from "@/lib/utils";
import { useMcpHistory } from "../queries";
import { ActionOutputDialog } from "./ActionOutputDialog";
import { ActionResult, actionKindLabel, reasonLabel } from "./ActionResult";
import { CHART_HEIGHT, PERIODS, type Period } from "./history-config";

// Recharts stays out of the page chunk: the chart loads only when the history tab opens (§7)
const LatencyChart = lazy(() => import("./LatencyChart").then((m) => ({ default: m.LatencyChart })));


export interface HistoryStats {
  avg: number | null;
  max: number | null;
  uptime: number | null;
}

/** Period-wide numbers for the chart's caption: mean of the minute averages, the largest maximum, Σok/Σtotal. */
export function historyStats(buckets: McpHistory["buckets"]): HistoryStats {
  let sum = 0;
  let n = 0;
  let max: number | null = null;
  let ok = 0;
  let total = 0;
  for (const b of buckets) {
    if (b.avg_latency_ms !== null) {
      sum += b.avg_latency_ms;
      n++;
    }
    if (b.max_latency_ms !== null && (max === null || b.max_latency_ms > max)) max = b.max_latency_ms;
    ok += b.ok;
    total += b.total;
  }
  return { avg: n > 0 ? sum / n : null, max, uptime: total > 0 ? ok / total : null };
}

const ms = (v: number | null) => (v === null ? copy.common.none : copy.common.units.ms(Math.round(v)));
const pct = (v: number | null) => (v === null ? copy.common.none : copy.common.units.percent((v * 100).toFixed(1)));

/**
 * Latency chart, state transitions and script actions for one period. The period is local state
 * (not in the URL). While a new period loads, the previous one stays on screen, dimmed. Tables and
 * the chart have no animation (direction §6, U-constraints).
 */
// memo: the detail page re-renders on every live board event for this MCP; the history only
// changes when its own query does (an SSE action invalidates it), so the chart is not redrawn every few seconds
export const HistoryTab = memo(function HistoryTab({ mcpId }: { mcpId: number }) {
  const [hours, setHours] = useState<Period>(24);
  const history = useMcpHistory(mcpId, hours);
  const [selected, setSelected] = useState<ActionRecord | null>(null);
  const [outputOpen, setOutputOpen] = useState(false);
  const opener = useRef<HTMLButtonElement | null>(null);

  const data = history.data;
  const stats = useMemo(() => (data ? historyStats(data.buckets) : null), [data]);
  const stale = history.isPlaceholderData;

  const open = (a: ActionRecord, button: HTMLButtonElement | null) => {
    opener.current = button;
    setSelected(a);
    setOutputOpen(true);
  };

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <div role="group" aria-label={copy.mcp.periodLabel} className="inline-flex w-fit rounded-md border border-border-strong p-0.5">
        {PERIODS.map((h) => (
          <button
            key={h}
            type="button"
            aria-pressed={h === hours}
            onClick={() => setHours(h)}
            className="h-(--size-control-sm) rounded-sm px-3 text-sm text-fg-muted transition-[background-color,color] duration-(--motion-fast) ease-hover hover:text-fg aria-pressed:bg-selected aria-pressed:font-semibold aria-pressed:text-fg"
          >
            {copy.mcp.periods[h]}
          </button>
        ))}
      </div>

      {history.isError && !data ? (
        <p role="alert" className="text-sm text-fg">
          {copy.mcp.historyError}
        </p>
      ) : !data || !stats ? (
        <div role="status" className="flex flex-col gap-3">
          <span className="sr-only">{copy.common.loading}</span>
          <Skeleton style={{ height: CHART_HEIGHT }} className="w-full" />
        </div>
      ) : (
        <div aria-busy={stale || undefined} className={cn("flex min-w-0 flex-col gap-6", stale && "opacity-60")}>
          <Section title={copy.mcp.chartTitle}>
            {data.buckets.length === 0 ? (
              <p className="text-sm text-fg-muted">{copy.mcp.noChartData}</p>
            ) : (
              <figure className="flex min-w-0 flex-col gap-3">
                <figcaption>
                  <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
                    <Stat label={copy.mcp.chartAvg} value={ms(stats.avg)} />
                    <Stat label={copy.mcp.chartMax} value={ms(stats.max)} />
                    <Stat label={copy.mcp.chartUptime} value={pct(stats.uptime)} />
                  </dl>
                  <span className="sr-only">
                    {copy.mcp.chartSummary(copy.mcp.periods[hours], ms(stats.avg), ms(stats.max), pct(stats.uptime))}
                  </span>
                </figcaption>
                <Suspense fallback={<Skeleton style={{ height: CHART_HEIGHT }} className="w-full" />}>
                  <LatencyChart mcpId={mcpId} buckets={data.buckets} transitions={data.transitions} />
                </Suspense>
              </figure>
            )}
          </Section>

          {data.transitions.length === 0 && data.actions.length === 0 ? (
            <p className="text-sm text-fg-muted">{copy.mcp.noHistory}</p>
          ) : (
            <>
              <TransitionsTable transitions={data.transitions} />
              <ActionsTable actions={data.actions} onOpen={open} />
            </>
          )}
        </div>
      )}

      <ActionOutputDialog
        mcpId={mcpId}
        action={selected}
        open={outputOpen}
        onClose={() => setOutputOpen(false)}
        returnFocus={() => opener.current?.focus()}
      />
    </div>
  );
});

function Section({ title, children, id: given }: { title: string; children: ReactNode; id?: string }) {
  const own = useId();
  const id = given ?? own;
  return (
    <section aria-labelledby={id} className="flex min-w-0 flex-col gap-3">
      <h2 id={id} className="text-base font-semibold text-fg">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <dt className="text-fg-muted">{label}</dt>
      <dd className="font-medium text-fg tabular-nums" data-volatile="">
        {value}
      </dd>
    </div>
  );
}

function Empty({ cols }: { cols: number }) {
  return (
    <TableRow>
      <TableCell colSpan={cols} className="text-fg-muted">
        {copy.common.none}
      </TableCell>
    </TableRow>
  );
}

function TransitionsTable({ transitions }: { transitions: McpHistory["transitions"] }) {
  const id = useId();
  const c = copy.mcp.historyColumns;
  return (
    <Section title={copy.mcp.transitionsTitle} id={id}>
      <Table aria-labelledby={id}>
        <TableHeader>
          <TableRow>
            <TableHead className="w-px">{c.at}</TableHead>
            <TableHead>{c.change}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {transitions.length === 0 ? <Empty cols={2} /> : null}
          {transitions.map((t) => (
            <TableRow key={`${t.at}-${t.to}`}>
              <TableCell className="font-mono text-xs whitespace-nowrap" data-volatile="">
                {formatKst(t.at)}
              </TableCell>
              <TableCell>
                <span className="inline-flex flex-wrap items-center gap-2">
                  <span className="text-xs text-fg-muted">{copy.states[t.from]}</span>
                  <span aria-hidden="true" className="text-fg-muted">→</span>
                  <StatusBadge state={t.to} issue={t.issue} />
                </span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Section>
  );
}

function ActionsTable({
  actions,
  onOpen,
}: {
  actions: ActionRecord[];
  onOpen: (a: ActionRecord, button: HTMLButtonElement | null) => void;
}) {
  const id = useId();
  const c = copy.mcp.historyColumns;
  return (
    <Section title={copy.mcp.actionsTitle} id={id}>
      <Table aria-labelledby={id}>
        <TableHeader>
          <TableRow>
            <TableHead className="w-px">{c.at}</TableHead>
            <TableHead>{c.kind}</TableHead>
            <TableHead>{c.trigger}</TableHead>
            <TableHead>{c.reason}</TableHead>
            <TableHead>{c.actor}</TableHead>
            <TableHead>{c.result}</TableHead>
            <TableHead className="text-right">{c.exitCode}</TableHead>
            <TableHead className="text-right">{c.duration}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {actions.length === 0 ? <Empty cols={8} /> : null}
          {actions.map((a) => (
            // the whole row opens the output for the mouse; the time button is the keyboard path
            <TableRow
              key={a.id}
              className="cursor-pointer"
              onClick={(e) => onOpen(a, e.currentTarget.querySelector("button"))}
            >
              <TableCell className="whitespace-nowrap">
                <button
                  type="button"
                  className="font-mono text-xs text-fg underline decoration-border-strong underline-offset-4 hover:decoration-fg"
                >
                  {formatKst(a.at)}
                  <span className="sr-only"> {copy.mcp.viewOutput}</span>
                </button>
              </TableCell>
              <TableCell className="whitespace-nowrap">{actionKindLabel(a)}</TableCell>
              <TableCell className="whitespace-nowrap">{copy.mcp.triggers[a.trigger]}</TableCell>
              <TableCell>{reasonLabel(a.reason)}</TableCell>
              <TableCell className={a.actor ? undefined : "text-fg-muted"}>{a.actor?.name ?? copy.mcp.systemActor}</TableCell>
              <TableCell>
                <ActionResult status={a.status} />
              </TableCell>
              <TableCell className="text-right">{a.exit_code ?? <Dash />}</TableCell>
              <TableCell className="text-right whitespace-nowrap">{formatDuration(a.duration_ms)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Section>
  );
}

function Dash() {
  return (
    <span className="text-fg-muted">
      <span aria-hidden="true">—</span>
      <span className="sr-only">{copy.common.none}</span>
    </span>
  );
}
