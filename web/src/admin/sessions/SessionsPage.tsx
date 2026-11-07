import { createColumnHelper, tableFeatures, useTable } from "@tanstack/react-table";
import { getRouteApi } from "@tanstack/react-router";
import {
  CircleCheckIcon, GlobeIcon, InfoIcon, LockIcon, LogInIcon, MonitorIcon, UnplugIcon, type LucideIcon,
} from "lucide-react";
import { useId, useMemo, useRef, useSyncExternalStore, type ReactNode, type Ref } from "react";
import { Caution, FactBadge, SessionCard } from "@/components/status/SessionCard";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { copy } from "@/copy/ko";
import type { CollectorStatus, ConnectionNotice, CurrentSession, LogonFailure, RdpSession, SessionConnection } from "@/lib/api-types";
import { denyReason } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { formatKst } from "@/lib/time";
import { cn } from "@/lib/utils";
import { useLive } from "../live";
import { useCollectors, useSessionsCurrent, useSessionsHistory } from "../queries";
import { DEFAULT_DAYS, SESSION_DAYS, type SessionDays } from "./period";

const route = getRouteApi("/authed/admin/sessions");

const f = copy.sessions.fields;
const c = copy.sessions.columns;

/** `DOMAIN\user`, or the name alone without a domain. */
function account(user: string, domain: string | null): string {
  return domain ? `${domain}\\${user}` : user;
}

function Dash() {
  return (
    <span className="text-fg-muted">
      <span aria-hidden="true">—</span>
      <span className="sr-only">{copy.common.none}</span>
    </span>
  );
}

function Time({ iso }: { iso: string }) {
  return (
    <time dateTime={iso} className="tabular-nums">
      {formatKst(iso)}
    </time>
  );
}

function Section({ title, id, children, busy }: { title: string; id: string; children: ReactNode; busy?: boolean }) {
  return (
    <section aria-labelledby={id} aria-busy={busy || undefined} className={cn("flex min-w-0 flex-col gap-3", busy && "opacity-60")}>
      <h2 id={id} className="text-base font-semibold text-fg">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Loading({ rows, className }: { rows: number; className: string }) {
  return (
    <div role="status" className="flex flex-col gap-2">
      <span className="sr-only">{copy.common.loading}</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={className} />
      ))}
    </div>
  );
}

function LoadError() {
  return (
    <p role="alert" className="text-sm text-fg">
      {copy.sessions.loadError}
    </p>
  );
}

function Empty({ children }: { children: string }) {
  return <p className="text-sm text-fg-muted">{children}</p>;
}

/**
 * Tables scroll sideways inside their own frame; the page never does. A table without controls
 * needs its scroller in the tab order, or a keyboard cannot reach the columns off to the right.
 */
const scroller = (labelledBy: string) => ({ tabIndex: 0, role: "group", "aria-labelledby": labelledBy });

function Frame({ children }: { children: ReactNode }) {
  return <div className="min-w-0 rounded-md border bg-surface">{children}</div>;
}

// ---- current sessions --------------------------------------------------------------------

const STATE_ICON: Record<CurrentSession["state"], LucideIcon> = {
  active: MonitorIcon,
  locked: LockIcon,
  disconnected: UnplugIcon,
  connected: LogInIcon,
};

function LineItem({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-fg-muted">{label}</dt>
      <dd className="truncate">{children}</dd>
    </div>
  );
}

/** A session the board does not show (disconnected, at the logon screen, or not on the board yet): one line. */
function SessionLine({ session: s }: { session: CurrentSession }) {
  const Icon = STATE_ICON[s.state];
  const gone = s.state === "disconnected" && s.disconnected_at !== null;
  const at = gone ? s.disconnected_at : (s.connected_at ?? s.logon_at);
  return (
    <div data-testid="session-line" className="rounded-md border bg-surface px-4 py-3">
      <dl className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
        <LineItem label={f.user}>
          <span className="font-semibold">{account(s.user, s.domain)}</span>
        </LineItem>
        <LineItem label={f.state}>
          <span className="inline-flex items-center gap-1.5">
            <Icon aria-hidden="true" className="size-3.5 shrink-0 text-fg-muted" />
            {copy.sessions.state[s.state]}
          </span>
        </LineItem>
        <LineItem label={f.clientName}>{s.client_name ?? <Dash />}</LineItem>
        <LineItem label={f.clientIp}>{s.client_ip ? <span className="font-mono">{s.client_ip}</span> : <Dash />}</LineItem>
        <LineItem label={gone ? copy.sessions.disconnectedAt : f.connectedAt}>{at ? <Time iso={at} /> : <Dash />}</LineItem>
      </dl>
    </div>
  );
}

/** The board's sessions only: this list does not re-render on MCP events. */
function useBoardSessions(): RdpSession[] | undefined {
  const { store } = useLive();
  return useSyncExternalStore(store.subscribe, () => store.getSnapshot().sessions);
}

/**
 * Every watched session. One that is on the board gets the board's live card (elapsed time, idle
 * time, notice); the others (disconnected, logon screen) a status line.
 */
function CurrentSessions() {
  const { data, isPending, isError } = useSessionsCurrent();
  const board = useBoardSessions();
  const live = useMemo(() => new Map((board ?? []).map((s) => [s.session_id, s])), [board]);

  if (isPending) return <Loading rows={1} className="h-40" />;
  if (isError && !data) return <LoadError />;
  if (!data.ready) {
    return (
      <p className="flex items-center gap-2 text-sm text-fg-muted">
        <InfoIcon aria-hidden="true" className="size-4 shrink-0" />
        {copy.board.sessionsNotReady}
      </p>
    );
  }
  if (data.sessions.length === 0) return <Empty>{copy.sessions.currentEmpty}</Empty>;

  const cards: RdpSession[] = [];
  const lines: CurrentSession[] = [];
  for (const s of data.sessions) {
    const b = live.get(s.session_id);
    if (b) cards.push(b);
    else lines.push(s);
  }
  return (
    <div className="flex flex-col gap-3">
      {cards.length > 0 ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,36rem),1fr))] gap-3">
          {cards.map((s) => (
            <SessionCard key={s.session_id} session={s} />
          ))}
        </div>
      ) : null}
      {lines.map((s) => (
        <SessionLine key={s.session_id} session={s} />
      ))}
    </div>
  );
}

// ---- period ------------------------------------------------------------------------------

function PeriodPicker({ days, onChange }: { days: SessionDays; onChange(d: SessionDays): void }) {
  return (
    <div role="group" aria-label={copy.sessions.periodLabel} className="flex flex-wrap items-center gap-3">
      <span aria-hidden="true" className="text-sm text-fg-muted">
        {copy.sessions.periodLabel}
      </span>
      <div className="flex w-fit max-w-full flex-wrap rounded-md border border-border-strong p-0.5">
        {SESSION_DAYS.map((d) => (
          <button
            key={d}
            type="button"
            aria-pressed={d === days}
            onClick={() => onChange(d)}
            className="h-(--size-control-sm) rounded-sm px-3 text-sm whitespace-nowrap text-fg-muted transition-[background-color,color] duration-(--motion-fast) ease-hover hover:text-fg aria-pressed:bg-selected aria-pressed:font-semibold aria-pressed:text-fg"
          >
            {copy.sessions.days(d)}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---- connection history ------------------------------------------------------------------

function NoticeCell({ notice }: { notice: ConnectionNotice | null }) {
  if (notice === null) return <Dash />;
  if (notice.closed_reason === "acknowledged" && notice.ack_ms !== null) return <>{copy.sessions.ackIn(notice.ack_ms)}</>;
  // still open, or closed another way (superseded, logoff, service restart): never acknowledged
  return <Caution>{copy.sessions.unacked}</Caution>;
}

const features = tableFeatures({});
const helper = createColumnHelper<typeof features, SessionConnection>();

const columns = helper.columns([
  helper.display({
    id: "connectedAt",
    header: f.connectedAt,
    cell: ({ row: { original: r } }) => <Time iso={r.connected_at} />,
  }),
  helper.display({
    id: "user",
    header: f.user,
    cell: ({ row: { original: r } }) => <span className="font-medium">{account(r.user, r.domain)}</span>,
  }),
  helper.display({
    id: "client",
    header: f.clientName,
    cell: ({ row: { original: r } }) => (
      <span className="inline-flex items-center gap-2">
        {r.client_name ?? <Dash />}
        {r.first_seen_device ? <FactBadge icon={MonitorIcon}>{copy.sessions.firstSeenDevice}</FactBadge> : null}
      </span>
    ),
  }),
  helper.display({
    id: "ip",
    header: f.clientIp,
    cell: ({ row: { original: r } }) => (
      <span className="flex flex-col">
        <span className="inline-flex items-center gap-2">
          {r.client_ip ? <span className="font-mono">{r.client_ip}</span> : <Dash />}
          {r.first_seen_ip ? <FactBadge icon={GlobeIcon}>{copy.sessions.firstSeenIp}</FactBadge> : null}
        </span>
        {r.reverse_dns ? <span className="font-mono text-xs text-fg-muted">{r.reverse_dns}</span> : null}
      </span>
    ),
  }),
  helper.display({
    id: "kind",
    header: c.kind,
    cell: ({ row: { original: r } }) => copy.sessions.kinds[r.kind],
  }),
  helper.display({
    id: "end",
    header: c.end,
    cell: ({ row: { original: r } }) =>
      r.ended_at === null ? (
        copy.sessions.ongoing
      ) : (
        <span className="flex flex-col">
          <Time iso={r.ended_at} />
          {r.end_reason ? <span className="text-xs text-fg-muted">{copy.sessions.endReasons[r.end_reason]}</span> : null}
        </span>
      ),
  }),
  helper.display({
    id: "notice",
    header: f.notice,
    cell: ({ row: { original: r } }) => <NoticeCell notice={r.notice} />,
  }),
]);

/** No animation: rows that "더 보기" adds simply appear (tables never move, direction.md §6). */
function ConnectionsTable({ data, labelledBy, frameRef }: { data: SessionConnection[]; labelledBy: string; frameRef: Ref<HTMLDivElement> }) {
  const table = useTable({ features, columns, data, getRowId: (r) => String(r.id) });
  return (
    <Frame>
      <Table aria-labelledby={labelledBy} containerProps={{ ...scroller(labelledBy), ref: frameRef }}>
        <TableHeader>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id} className="hover:bg-transparent">
              {group.headers.map((header) => (
                <TableHead key={header.id} scope="col">
                  <table.FlexRender header={header} />
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow key={row.id} data-testid="connection-row">
              {row.getAllCells().map((cell) =>
                cell.column.id === "connectedAt" ? (
                  // the time a connection began names the row
                  <th key={cell.id} scope="row" className="px-3 py-2 text-left align-middle font-normal whitespace-nowrap">
                    <table.FlexRender cell={cell} />
                  </th>
                ) : (
                  <TableCell key={cell.id}>
                    <table.FlexRender cell={cell} />
                  </TableCell>
                ),
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Frame>
  );
}

function FailuresTable({ failures, labelledBy }: { failures: LogonFailure[]; labelledBy: string }) {
  return (
    <Frame>
      <Table aria-labelledby={labelledBy} containerProps={scroller(labelledBy)}>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead scope="col">{c.at}</TableHead>
            <TableHead scope="col">{f.user}</TableHead>
            <TableHead scope="col">{f.clientIp}</TableHead>
            <TableHead scope="col">{c.workstation}</TableHead>
            <TableHead scope="col">{c.logonType}</TableHead>
            <TableHead scope="col">{c.status}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {failures.map((x) => (
            <TableRow key={x.id}>
              <th scope="row" className="px-3 py-2 text-left align-middle font-normal whitespace-nowrap">
                <Time iso={x.at} />
              </th>
              <TableCell>{x.user ? account(x.user, x.domain) : <Dash />}</TableCell>
              <TableCell>{x.client_ip ? <span className="font-mono">{x.client_ip}</span> : <Dash />}</TableCell>
              <TableCell>{x.workstation ?? <Dash />}</TableCell>
              <TableCell>{x.logon_type === null ? <Dash /> : copy.sessions.logonType(x.logon_type)}</TableCell>
              <TableCell>
                {x.status ? (
                  <span className="flex flex-col font-mono">
                    <span>{x.status}</span>
                    {x.sub_status ? <span className="text-xs text-fg-muted">{x.sub_status}</span> : null}
                  </span>
                ) : (
                  <Dash />
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Frame>
  );
}

/**
 * Connection history and logon failures of the period: one paged read (`before_id`), the failures
 * come with its first page. While another period loads, the previous one stays, dimmed.
 */
function Records({ days }: { days: SessionDays }) {
  const historyId = useId();
  const failuresId = useId();
  const q = useSessionsHistory(days);
  const frame = useRef<HTMLDivElement>(null);
  const pages = q.data?.pages;
  const connections = useMemo(() => pages?.flatMap((p) => p.connections) ?? [], [pages]);
  const failures = pages?.[0]?.failures ?? [];
  const stale = q.isPlaceholderData;

  let history: ReactNode;
  let failed: ReactNode;
  if (q.isPending) {
    history = <Loading rows={3} className="h-9" />;
    failed = <Loading rows={2} className="h-9" />;
  } else if (!pages) {
    history = <LoadError />;
    failed = <LoadError />;
  } else {
    history =
      connections.length === 0 ? (
        <Empty>{copy.sessions.empty}</Empty>
      ) : (
        <>
          <ConnectionsTable data={connections} labelledBy={historyId} frameRef={frame} />
          {q.hasNextPage ? (
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="outline"
                aria-busy={q.isFetchingNextPage || undefined}
                onClick={() => {
                  if (q.isFetchingNextPage) return;
                  void q.fetchNextPage().then((r) => {
                    // the last page removes this button: keep focus at the table it extended, not on <body>
                    if (!r.isError && !r.hasNextPage) frame.current?.focus();
                  });
                }}
              >
                {copy.sessions.more}
              </Button>
              {q.isFetchNextPageError ? (
                <p role="alert" className="text-sm text-fg">
                  {copy.sessions.moreError}
                </p>
              ) : null}
            </div>
          ) : null}
        </>
      );
    failed =
      failures.length === 0 ? <Empty>{copy.sessions.failuresEmpty}</Empty> : <FailuresTable failures={failures} labelledBy={failuresId} />;
  }

  return (
    <>
      <Section title={copy.sessions.history} id={historyId} busy={stale}>
        {history}
      </Section>
      <Section title={copy.sessions.failures} id={failuresId} busy={stale}>
        {failed}
      </Section>
    </>
  );
}

// ---- collectors --------------------------------------------------------------------------

function CollectorState({ s }: { s: CollectorStatus }) {
  if (!s.ok) return <Caution>{s.error ? copy.sessions.collectorDown(s.error) : copy.sessions.collectorStopped}</Caution>;
  return (
    <span className="inline-flex items-center gap-1">
      <CircleCheckIcon aria-hidden="true" className="size-3.5 shrink-0 text-fg-muted" />
      {copy.sessions.collectorOk}
    </span>
  );
}

function Collectors({ labelledBy }: { labelledBy: string }) {
  const { data, isPending, isError } = useCollectors();
  if (isPending) return <Loading rows={2} className="h-9" />;
  if (isError && !data) return <LoadError />;
  if (data.length === 0) return <Empty>{copy.sessions.collectorsEmpty}</Empty>;
  return (
    <Frame>
      <Table aria-labelledby={labelledBy}>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead scope="col">{c.collector}</TableHead>
            <TableHead scope="col">{c.collectorState}</TableHead>
            <TableHead scope="col">{c.since}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((s) => (
            <TableRow key={s.name}>
              <th scope="row" className="px-3 py-2 text-left align-middle font-mono text-xs font-normal whitespace-nowrap">
                {s.name}
              </th>
              <TableCell className="whitespace-normal">
                <CollectorState s={s} />
              </TableCell>
              <TableCell>
                <Time iso={s.since} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Frame>
  );
}

/**
 * Remote desktop sessions (spec §6.4 #3): who is on now, the connection history of a period with
 * first-seen and notice facts, logon failures and the collectors' health. Both channels
 * (`view_session_history`, V31). The period lives in the URL (`?days=`, 7 when absent).
 */
export function SessionsPage() {
  const me = useSession();
  const reason = denyReason(me, "view_session_history");
  const { days = DEFAULT_DAYS } = route.useSearch();
  const navigate = route.useNavigate();
  const currentId = useId();
  const collectorsId = useId();

  return (
    <>
      <h1 className="text-xl font-semibold text-fg">{copy.sessions.title}</h1>
      {reason ? (
        <p className="text-sm text-fg-muted">{copy.deny[reason]}</p>
      ) : (
        <>
          <Section title={copy.sessions.current} id={currentId}>
            <CurrentSessions />
          </Section>
          <PeriodPicker
            days={days}
            onChange={(d) => void navigate({ search: { days: d === DEFAULT_DAYS ? undefined : d } })}
          />
          <Records days={days} />
          <Section title={copy.sessions.collectors} id={collectorsId}>
            <Collectors labelledBy={collectorsId} />
          </Section>
        </>
      )}
    </>
  );
}
