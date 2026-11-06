import { Link } from "@tanstack/react-router";
import { CircleCheckIcon, CircleXIcon, ClockAlertIcon, TriangleAlertIcon, type LucideIcon } from "lucide-react";
import { useId, useMemo, type ReactNode } from "react";
import { ConnectionBanner } from "@/components/status/ConnectionBanner";
import { SessionCard } from "@/components/status/SessionCard";
import { STATE_ICONS, StatusBadge } from "@/components/status/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { copy } from "@/copy/ko";
import type { BoardItem, McpActivity, McpState, ScriptStatus } from "@/lib/api-types";
import { STATE_SEVERITY, useBoard } from "@/lib/board-store";
import { formatKst } from "@/lib/time";
import { cn } from "@/lib/utils";
import { useLive } from "../live";
import { useMcpActivity } from "../queries";
import { LoginFailuresCard } from "./LoginFailuresCard";
import { TamperCard } from "./TamperCard";

/** Rows shown in “최근 이슈와 조치” (the feed holds ACTIVITY_LIMIT). */
const RECENT = 10;

const STATES = (Object.keys(STATE_SEVERITY) as McpState[]).sort((a, b) => STATE_SEVERITY[a] - STATE_SEVERITY[b]);

/** Full class names (Tailwind only sees literal strings). */
const STATE_ICON_TONE: Record<McpState, string> = {
  HEALTHY: "text-state-healthy",
  SUSPECT: "text-state-suspect",
  ACTION: "text-state-action",
  RECOVERING: "text-state-recovering",
  FAILED: "text-state-failed",
  MAINTENANCE: "text-state-maintenance",
};

const STATUS_ICON: Record<ScriptStatus, LucideIcon> = {
  ok: CircleCheckIcon,
  failed: CircleXIcon,
  timeout: ClockAlertIcon,
  error: TriangleAlertIcon,
};

function DashCard({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className={cn("@container flex min-w-0 flex-col gap-3 rounded-md border bg-surface p-4", className)}>
      <h2 id={id} className="text-base font-semibold text-fg">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** Count per state, worst first; a count links to the list filtered to that state. */
function McpSummary({ items, loading }: { items: ReadonlyMap<number, BoardItem>; loading: boolean }) {
  const counts = useMemo(() => {
    const c = new Map<McpState, number>();
    for (const it of items.values()) c.set(it.state, (c.get(it.state) ?? 0) + 1);
    return c;
  }, [items]);

  if (loading) {
    return (
      <div role="status" className="grid grid-cols-2 gap-2 @sm:grid-cols-4 @2xl:grid-cols-7">
        <span className="sr-only">{copy.common.loading}</span>
        {STATES.map((s) => (
          <Skeleton key={s} className="h-16" />
        ))}
      </div>
    );
  }
  if (items.size === 0) return <p className="text-sm text-fg-muted">{copy.dashboard.noMcp}</p>;

  const tile = "flex min-h-16 flex-col justify-between gap-1 rounded-sm border px-3 py-2";
  return (
    <ul className="grid grid-cols-2 gap-2 @sm:grid-cols-4 @2xl:grid-cols-7">
      <li>
        <Link to="/admin/mcps" search={{}} className={cn(tile, "transition-colors hover:bg-hover")}>
          <span className="text-sm text-fg-muted">{copy.dashboard.summaryAll}</span>{" "}
          <span className="text-2xl font-semibold tabular-nums text-fg">{items.size}</span>
        </Link>
      </li>
      {STATES.map((s) => {
        const n = counts.get(s) ?? 0;
        const Icon = STATE_ICONS[s];
        const body = (
          <>
            <span className="inline-flex items-center gap-1.5 text-sm">
              <Icon aria-hidden="true" className={cn("size-4", n > 0 ? STATE_ICON_TONE[s] : "text-fg-muted")} />
              {copy.states[s]}
            </span>{" "}
            <span className="text-2xl font-semibold tabular-nums">{n}</span>
          </>
        );
        return (
          <li key={s}>
            {n > 0 ? (
              <Link to="/admin/mcps" search={{ state: s }} className={cn(tile, "text-fg transition-colors hover:bg-hover")}>
                {body}
              </Link>
            ) : (
              <div className={cn(tile, "border-dashed text-fg-muted")}>{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

type ActivityRow =
  | { key: string; at: string; mcpId: number; name: string; type: "transition"; t: McpActivity["transitions"][number] }
  | { key: string; at: string; mcpId: number; name: string; type: "action"; a: McpActivity["actions"][number] };

/** Transitions into a non-healthy state and every action step, newest first. */
function recentRows(activity: McpActivity): ActivityRow[] {
  const rows: ActivityRow[] = [
    ...activity.transitions
      .filter((t) => t.to !== "HEALTHY")
      .map((t, i): ActivityRow => ({ key: `t${i}`, at: t.at, mcpId: t.mcp_id, name: t.name, type: "transition", t })),
    ...activity.actions.map((a): ActivityRow => ({ key: `a${a.id}`, at: a.at, mcpId: a.mcp_id, name: a.name, type: "action", a })),
  ];
  return rows.sort((x, y) => Date.parse(y.at) - Date.parse(x.at)).slice(0, RECENT);
}

function RecentActivity() {
  const { data, isPending, isError } = useMcpActivity();
  const rows = useMemo(() => (data ? recentRows(data) : []), [data]);

  if (isPending) {
    return (
      <div role="status" className="flex flex-col gap-2">
        <span className="sr-only">{copy.common.loading}</span>
        <Skeleton className="h-8" />
        <Skeleton className="h-8" />
        <Skeleton className="h-8" />
      </div>
    );
  }
  if (isError) return <p role="alert" className="text-sm text-fg">{copy.dashboard.activityError}</p>;
  if (rows.length === 0) return <p className="text-sm text-fg-muted">{copy.dashboard.noActivity}</p>;

  return (
    // data-volatile: rows depend on what happened before (screenshot mask, F32)
    <Table data-volatile="">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          {/* w-px: time and name take their content width, the event column the rest */}
          <TableHead scope="col" className="w-px">
            {copy.dashboard.columns.at}
          </TableHead>
          <TableHead scope="col" className="w-px">
            {copy.dashboard.columns.mcp}
          </TableHead>
          <TableHead scope="col">{copy.dashboard.columns.event}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.key}>
            <TableCell>
              <time dateTime={r.at} className="tabular-nums text-fg-muted">
                {formatKst(r.at)}
              </time>
            </TableCell>
            <TableCell>
              <Link
                to="/admin/mcps/$mcpId"
                params={{ mcpId: String(r.mcpId) }}
                className="font-medium text-fg underline-offset-4 hover:underline"
              >
                {r.name}
              </Link>
            </TableCell>
            <TableCell>
              {r.type === "transition" ? <StatusBadge state={r.t.to} issue={r.t.issue} /> : <ActionCell a={r.a} />}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function ActionCell({ a }: { a: McpActivity["actions"][number] }) {
  const Icon = STATUS_ICON[a.status];
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <span>{copy.dashboard.actionLine(copy.mcp.triggers[a.trigger], a.kind)}</span>
      <span className={cn("inline-flex items-center gap-1", a.status === "ok" ? "text-fg-muted" : "font-medium text-fg")}>
        <Icon aria-hidden="true" className="size-3.5" />
        {copy.mcp.scriptStatus[a.status]}
      </span>
    </span>
  );
}

/**
 * The admin landing page: what is wrong now (state counts from the live store), who is connected,
 * what happened recently, the login-failure trend of the last 24 hours and the recent bypass detections.
 */
export function DashboardPage() {
  const { store } = useLive();
  const board = useBoard(store);

  return (
    <>
      <h1 className="text-xl font-semibold text-fg">{copy.dashboard.title}</h1>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <DashCard title={copy.dashboard.mcpSummary}>
          <McpSummary items={board.items} loading={board.now === null} />
        </DashCard>
        <DashCard title={copy.dashboard.currentSessions}>
          <ConnectionBanner sessions={board.sessions} className="text-base" />
          {board.sessions && board.sessions.length > 0 ? (
            <div className="flex flex-col gap-2">
              {board.sessions.map((s) => (
                <SessionCard key={s.session_id} session={s} />
              ))}
            </div>
          ) : null}
        </DashCard>
        <DashCard title={copy.dashboard.recentActivity} className="col-span-full">
          <RecentActivity />
        </DashCard>
        <DashCard title={copy.dashboard.loginFailures.title}>
          <LoginFailuresCard />
        </DashCard>
        <DashCard title={copy.dashboard.bypassEvents}>
          <TamperCard />
        </DashCard>
      </div>
    </>
  );
}
