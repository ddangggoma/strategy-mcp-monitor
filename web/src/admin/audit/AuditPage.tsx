import { createColumnHelper } from "@tanstack/react-table";
import { BanIcon, CircleCheckIcon, CircleXIcon, TriangleAlertIcon, type LucideIcon } from "lucide-react";
import { useCallback, useId, useMemo, useRef, useState } from "react";
import { VirtualTable, vtFeatures } from "@/components/data/VirtualTable";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { copy } from "@/copy/ko";
import type { AuditQuery, Channel, LogCategory, LogItem, LogOutcome, LogQuery } from "@/lib/api-types";
import { auditExportUrl } from "@/lib/endpoints";
import { denyReason } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { formatKstMs } from "@/lib/time";
import { cn } from "@/lib/utils";
import { ExportMenu } from "../logs/ExportMenu";
import { keepText, TypedFilter } from "../logs/FilterBar";
import { LogDetail } from "../logs/LogDetail";
import { useRestOfViewport } from "../logs/LogTable";
import { resolveRange, type AuditKind, type AuditSearch, type QuickRange } from "../logs/search";
import { TimeRangePicker, Toggle, ToggleGroup } from "../logs/TimeRangePicker";
import { UserFilter } from "../logs/UserFilter";
import { useAuditPages } from "../queries";
import { useAuditNavigate, useAuditSearch, type AuditSearchPatch } from "./use-audit-search";

const KINDS: readonly AuditKind[] = ["admin", "auth", "all"];
/** Admin actions are rare: a week is the useful first look (the log screen starts at an hour). */
const DEFAULT_RANGE: QuickRange = "7d";
const KIND_CATS: Record<AuditKind, LogCategory[]> = { admin: ["admin.audit"], auth: ["auth"], all: ["admin.audit", "auth"] };
type Result = "ok" | "fail" | "denied" | "error";
/** The results each kind can have: admin actions are ok/denied/error, logins ok/fail. */
const KIND_RESULTS: Record<AuditKind, readonly Result[]> = {
  admin: ["ok", "denied", "error"],
  auth: ["ok", "fail"],
  all: ["ok", "fail", "denied", "error"],
};
const RESULT_ICON: Record<Result, LucideIcon> = { ok: CircleCheckIcon, fail: CircleXIcon, denied: BanIcon, error: TriangleAlertIcon };
const CHANNELS: readonly (Channel | "all")[] = ["all", "local", "external"];
const TARGET_MAX = 120;
const UA_MAX = 60;
const ROW = 32;

const c = copy.audit.columns;

function Dash() {
  return (
    <span className="text-fg-muted">
      <span aria-hidden="true">—</span>
      <span className="sr-only">{copy.common.none}</span>
    </span>
  );
}

function cut(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function valueText(v: unknown): string {
  if (typeof v === "string") return v;
  if (v === undefined) return "";
  return JSON.stringify(v) ?? String(v);
}

/**
 * What an audit line is about. Admin actions: `target` as `key=value` pairs (nested values as
 * compact JSON), at most 120 characters. Logins: for a local login the Windows account behind it
 * (Plan 4), and the browser (first 60 characters).
 */
export function auditTarget(item: LogItem): string {
  const d = item.data;
  if (item.cat === "auth") {
    // the Windows account first: the browser string is long and the cell cuts its end
    const parts: string[] = [];
    if (typeof d.windows_user === "string" && d.windows_user) parts.push(copy.audit.windowsUser(d.windows_user));
    if (typeof d.user_agent === "string" && d.user_agent) parts.push(cut(d.user_agent, UA_MAX + 1));
    return parts.join(", ");
  }
  const target = d.target;
  if (typeof target !== "object" || target === null || Array.isArray(target)) return target === undefined ? "" : cut(valueText(target), TARGET_MAX);
  return cut(
    Object.entries(target)
      .map(([k, v]) => `${k}=${valueText(v)}`)
      .join(", "),
    TARGET_MAX,
  );
}

function ResultMark({ result }: { result: LogOutcome | null }) {
  if (result === null || !(result in RESULT_ICON)) return result === null ? <Dash /> : <span>{result}</span>;
  const r = result as Result;
  const Icon = RESULT_ICON[r];
  // an icon and a word, never the colour alone
  return (
    <span data-result={r} className={cn("inline-flex items-center gap-1.5", r === "ok" ? "text-fg-muted" : "font-medium text-fg")}>
      <Icon aria-hidden="true" className={cn("size-3.5 shrink-0", r !== "ok" && "text-danger")} />
      {copy.audit.results[r]}
    </span>
  );
}

const helper = createColumnHelper<typeof vtFeatures, LogItem>();
const columns = helper.columns([
  helper.display({
    id: "ts",
    header: c.ts,
    meta: { width: "13.5rem", rowHeader: true },
    cell: ({ row: { original: r } }) => (
      <time dateTime={r.ts} data-volatile="">
        {formatKstMs(r.ts)}
      </time>
    ),
  }),
  helper.display({ id: "actor", header: c.actor, meta: { width: "13rem" }, cell: ({ row: { original: r } }) => r.user ?? <Dash /> }),
  helper.display({
    id: "channel",
    header: c.channel,
    meta: { width: "8rem" },
    cell: ({ row: { original: r } }) => {
      const ch = r.data.channel;
      return ch === "local" || ch === "external" ? copy.channel[ch] : <Dash />;
    },
  }),
  helper.display({ id: "ip", header: c.ip, meta: { width: "9rem", className: "font-mono" }, cell: ({ row: { original: r } }) => r.client_ip ?? <Dash /> }),
  helper.display({
    id: "action",
    header: c.action,
    meta: { width: "14.5rem", className: "font-mono text-xs" },
    cell: ({ row: { original: r } }) => r.event ?? <Dash />,
  }),
  helper.display({ id: "target", header: c.target, cell: ({ row: { original: r } }) => auditTarget(r) || <Dash /> }),
  helper.display({ id: "result", header: c.result, meta: { width: "6.5rem" }, cell: ({ row: { original: r } }) => <ResultMark result={r.outcome} /> }),
]);

/** The API query for the URL state at `now`: minute bounds, kind always sent, empty filters left out. */
export function toAuditQuery(s: AuditSearch, now: Date): AuditQuery {
  const q = s.q?.trim();
  const out: AuditQuery = {
    ...resolveRange({ range: s.range ?? DEFAULT_RANGE, from: s.from, to: s.to }, now),
    kind: s.kind ?? "admin",
  };
  if (s.users?.length) out.users = [...s.users];
  if (s.result?.length) out.result = [...s.result];
  if (s.channel) out.channel = s.channel;
  if (q) out.q = q;
  return out;
}

function AuditFilters({
  search, query, onChange, onQuickRange,
}: {
  search: AuditSearch;
  query: AuditQuery;
  onChange(patch: AuditSearchPatch, opts?: { replace?: boolean }): void;
  onQuickRange(r: QuickRange): void;
}) {
  const kind = query.kind ?? "admin";
  const resultsLabel = useId();
  // actor counts: the same window and categories, read from the log index (W13)
  const facet = useMemo<LogQuery>(
    () => ({ from: query.from, to: query.to, cat: KIND_CATS[kind], ...(query.result ? { outcome: query.result } : {}), ...(query.q ? { q: query.q } : {}) }),
    [query.from, query.to, kind, query.result, query.q],
  );
  const commitQ = useCallback((v: string) => onChange({ q: v === "" ? undefined : v }, { replace: true }), [onChange]);
  const toggle = (list: readonly string[] | undefined, v: string) => (list?.includes(v) ? list.filter((x) => x !== v) : [...(list ?? []), v]);
  const filtered = !!search.users?.length || !!search.result?.length || !!search.channel || !!search.q;

  return (
    <div className="@container/filters flex min-w-0 flex-col gap-3 rounded-md border bg-surface p-3">
      <TimeRangePicker
        range={search.range ?? DEFAULT_RANGE}
        custom={search.from !== undefined && search.to !== undefined}
        from={query.from}
        to={query.to}
        onQuick={onQuickRange}
        onCustom={(from, to) => onChange({ from, to, range: undefined })}
      />
      <div className="flex min-w-0 flex-wrap items-end gap-x-4 gap-y-2">
        <div role="group" aria-labelledby={resultsLabel} className="flex flex-col gap-1">
          <span id={resultsLabel} className="text-xs text-fg-muted">
            {c.result}
          </span>
          <div className="flex flex-wrap gap-1.5">
            {KIND_RESULTS[kind].map((r) => {
              const Icon = RESULT_ICON[r];
              const on = search.result?.includes(r) ?? false;
              return (
                <button
                  key={r}
                  type="button"
                  aria-pressed={on}
                  onClick={() => onChange((s) => ({ result: toggle(s.result, r) as LogOutcome[] }))}
                  className="inline-flex h-(--size-control-sm) items-center gap-1.5 rounded-full border border-border-strong px-3 text-sm whitespace-nowrap text-fg-muted hover:bg-hover hover:text-fg aria-pressed:border-fg aria-pressed:bg-selected aria-pressed:text-fg"
                >
                  <Icon aria-hidden="true" className="size-3.5" />
                  {copy.audit.results[r]}
                </button>
              );
            })}
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <span aria-hidden="true" className="text-xs text-fg-muted">
            {c.channel}
          </span>
          <ToggleGroup label={c.channel}>
            {CHANNELS.map((ch) => (
              <Toggle key={ch} pressed={(search.channel ?? "all") === ch} onClick={() => onChange({ channel: ch === "all" ? undefined : ch })}>
                {copy.audit.channels[ch]}
              </Toggle>
            ))}
          </ToggleGroup>
        </div>
      </div>
      <div className="flex min-w-0 flex-wrap items-end gap-2">
        <UserFilter
          query={facet}
          selected={search.users ?? []}
          onToggle={(u) => onChange((s) => ({ users: toggle(s.users, u) }))}
          label={c.actor}
        />
        <TypedFilter
          label={copy.logs.keyword}
          value={search.q ?? ""}
          normalize={keepText}
          onCommit={commitQ}
          hint={copy.logs.keywordHint}
          className="w-[min(100%,16rem)] max-w-96 grow"
        />
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {filtered ? (
            <Button variant="ghost" onClick={() => onChange({ users: undefined, result: undefined, channel: undefined, q: undefined })}>
              {copy.logs.clear}
            </Button>
          ) : null}
          <ExportMenu hrefFor={(f) => auditExportUrl(query, f)} />
        </div>
      </div>
    </div>
  );
}

function AuditTable({ query, onFilterUser }: { query: AuditQuery; onFilterUser(user: string): void }) {
  const q = useAuditPages(query);
  const [shown, setShown] = useState<LogItem | null>(null);
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLElement | null>(null);
  const frame = useRef<HTMLDivElement>(null);
  const height = useRestOfViewport(frame);
  const openRow = useCallback((r: LogItem) => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setShown(r);
    setOpen(true);
  }, []);
  const returnFocus = useCallback((e: Event) => {
    e.preventDefault();
    const el = opener.current;
    if (el?.isConnected) el.focus();
    else (frame.current?.querySelector<HTMLElement>("tbody tr[data-index]") ?? document.getElementById("main"))?.focus();
  }, []);
  const pages = q.data?.pages;
  const rows = useMemo(() => pages?.flatMap((p) => p.items) ?? [], [pages]);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = q;
  const loadMore = useCallback(() => {
    if (!isFetchingNextPage) void fetchNextPage();
  }, [fetchNextPage, isFetchingNextPage]);
  const getRowId = useCallback((r: LogItem) => String(r.id), []);

  let body;
  if (q.isPending) {
    // static placeholders: nothing in the log area moves
    body = (
      <div role="status" className="flex flex-col gap-2">
        <span className="sr-only">{copy.common.loading}</span>
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} aria-hidden="true" className="h-8 rounded-sm bg-selected" />
        ))}
      </div>
    );
  } else if (!pages) {
    body = (
      <p role="alert" className="text-sm text-fg">
        {copy.audit.loadError}
      </p>
    );
  } else if (rows.length === 0) {
    body = <p className="text-sm text-fg-muted">{copy.audit.empty}</p>;
  } else {
    body = (
      <VirtualTable<LogItem>
        key={JSON.stringify(query)}
        rows={rows}
        columns={columns}
        rowHeight={ROW}
        getRowId={getRowId}
        onRowOpen={openRow}
        hasMore={!!hasNextPage && !q.isPlaceholderData}
        onLoadMore={loadMore}
        ariaLabel={copy.audit.title}
        height={height}
        minWidth="76rem"
        footer={
          isFetchingNextPage ? (
            <p role="status" className="sticky left-0 px-3 py-2 text-sm text-fg-muted">
              {copy.common.loading}
            </p>
          ) : q.isFetchNextPageError ? (
            <div className="sticky left-0 flex flex-wrap items-center gap-3 px-3 py-2">
              <p role="alert" className="text-sm text-fg">
                {copy.logs.loadMoreError}
              </p>
              <Button variant="outline" size="sm" onClick={() => void fetchNextPage()}>
                {copy.common.retry}
              </Button>
            </div>
          ) : null
        }
      />
    );
  }

  return (
    <div ref={frame} aria-busy={q.isPlaceholderData || undefined} className={cn("min-w-0", q.isPlaceholderData && "opacity-60")}>
      {body}
      <LogDetail
        item={shown}
        open={open}
        onClose={() => setOpen(false)}
        onCloseAutoFocus={returnFocus}
        onFilterUser={(u) => {
          setOpen(false);
          onFilterUser(u);
        }}
      />
    </div>
  );
}

/**
 * Audit log (spec §6.4 #8, W13, docs/design/screens/audit.md): admin actions and login attempts from
 * the same index as the log screen. Tabs pick the kind; filters and the table follow the log screen's
 * rules (URL state only, minute bounds, a virtual table in its own scroller, no animation).
 */
export function AuditPage() {
  const me = useSession();
  const reason = denyReason(me, "view_audit");
  const search = useAuditSearch();
  const go = useAuditNavigate();
  const [refreshed, setRefreshed] = useState(0);
  const query = useMemo(
    // reading the clock is the point: once per navigation, so quick ranges end at "now" (W34)
    // eslint-disable-next-line react-hooks/purity
    () => toAuditQuery(search, new Date(Math.max(Date.now(), refreshed))),
    [search, refreshed],
  );
  const kind = query.kind ?? "admin";

  const onQuickRange = (r: QuickRange) => {
    setRefreshed(Date.now());
    go({ range: r, from: undefined, to: undefined });
  };
  const onKind = (v: string) => {
    const next = v as AuditKind;
    // results the new kind cannot have leave the filter
    go((s) => ({ kind: next === "admin" ? undefined : next, result: s.result?.filter((r) => (KIND_RESULTS[next] as readonly string[]).includes(r)) }));
  };

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <h1 className="text-xl font-semibold text-fg">{copy.audit.title}</h1>
      {reason ? (
        <p className="text-sm text-fg-muted">{copy.deny[reason]}</p>
      ) : (
        <Tabs value={kind} onValueChange={onKind}>
          <TabsList variant="line" aria-label={copy.audit.tabsLabel}>
            {KINDS.map((k) => (
              <TabsTrigger key={k} value={k}>
                {copy.audit.kinds[k]}
              </TabsTrigger>
            ))}
          </TabsList>
          {KINDS.map((k) => (
            <TabsContent key={k} value={k} className="flex min-w-0 flex-col gap-4 pt-2">
              {k === kind ? (
                <>
                  <AuditFilters search={search} query={query} onChange={go} onQuickRange={onQuickRange} />
                  <AuditTable query={query} onFilterUser={(u) => go({ users: [u] })} />
                </>
              ) : null}
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  );
}
