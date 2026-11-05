import {
  createColumnHelper,
  createSortedRowModel,
  rowSortingFeature,
  tableFeatures,
  useTable,
  type Row,
} from "@tanstack/react-table";
import { Link, getRouteApi } from "@tanstack/react-router";
import { ArrowDownIcon, ArrowUpIcon, ChevronsUpDownIcon, PlusIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { WithReason } from "@/components/app/WithReason";
import { STATE_ICONS, StatusBadge } from "@/components/status/StatusBadge";
import { UptimeMeter } from "@/components/status/UptimeMeter";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { copy } from "@/copy/ko";
import type { McpDetail, McpState } from "@/lib/api-types";
import { STATE_SEVERITY } from "@/lib/board-store";
import { denyReason } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";
import { useMcps } from "../queries";
import { ConfigErrorBadge } from "./ConfigErrorBadge";
import { McpActions } from "./McpActions";

const route = getRouteApi("/authed/admin/mcps");

/** Filter chips in board order (worst first), so the chip row reads like the board. */
const STATES = (Object.keys(STATE_SEVERITY) as McpState[]).sort((a, b) => STATE_SEVERITY[a] - STATE_SEVERITY[b]);

const byName = new Intl.Collator("ko", { sensitivity: "base", numeric: true });

/** Unmonitored (config error) first, then U17 severity; an MCP the board has not reported yet last. */
function severity(m: McpDetail): number {
  if (m.config_error) return -1;
  return m.live ? STATE_SEVERITY[m.live.state] : 99;
}

const features = tableFeatures({ rowSortingFeature, sortedRowModel: createSortedRowModel() });
const helper = createColumnHelper<typeof features, McpDetail>();
type McpRow = Row<typeof features, McpDetail>;

/** Ties in any column fall back to the name, so the order never jumps between renders. */
const byNameRow = (a: McpRow, b: McpRow) => byName.compare(a.original.name, b.original.name) || a.original.id - b.original.id;

const columns = helper.columns([
  helper.accessor((m) => severity(m), {
    id: "state",
    header: copy.mcp.columns.state,
    sortFn: (a, b) => severity(a.original) - severity(b.original) || byNameRow(a, b),
    cell: ({ row: { original: m } }) => <StateCell mcp={m} />,
  }),
  helper.accessor("name", {
    header: copy.mcp.columns.name,
    sortFn: byNameRow,
    cell: ({ row: { original: m } }) => (
      <Link
        to="/admin/mcps/$mcpId"
        params={{ mcpId: String(m.id) }}
        className="font-semibold text-fg underline-offset-4 hover:underline"
      >
        {m.name}
      </Link>
    ),
  }),
  helper.display({
    id: "hostPort",
    header: copy.mcp.columns.hostPort,
    cell: ({ row: { original: m } }) => <span className="font-mono text-xs">{`${m.host}:${m.port}`}</span>,
  }),
  helper.accessor((m) => m.live?.latency_ms ?? undefined, {
    id: "latency",
    header: copy.mcp.columns.latency,
    sortUndefined: "last",
    sortDescFirst: false,
    cell: ({ getValue }) => {
      const v = getValue();
      return v === undefined ? <Dash /> : <span data-volatile="">{Math.round(v)}</span>;
    },
  }),
  helper.accessor((m) => m.live?.uptime_24h ?? undefined, {
    id: "uptime",
    header: copy.mcp.columns.uptime,
    sortUndefined: "last",
    sortDescFirst: false,
    cell: ({ getValue }) => <UptimeMeter value={getValue() ?? null} className="text-sm font-normal" />,
  }),
  helper.display({
    id: "owner",
    header: copy.mcp.columns.owner,
    cell: ({ row: { original: m } }) =>
      m.owner ? <span>{m.owner.name}</span> : <span className="text-fg-muted">{copy.mcp.noOwner}</span>,
  }),
  helper.display({
    id: "actions",
    header: copy.mcp.columns.actions,
    cell: ({ row: { original: m } }) => <McpActions mcp={m} size="sm" />,
  }),
]);

const SORTABLE = new Set(["state", "name", "latency", "uptime"]);
const NUMERIC = new Set(["latency", "uptime"]);
/** The actions stay in view while a narrow window scrolls the table sideways. */
const STICKY = "sticky right-0 bg-surface shadow-[inset_1px_0_0_var(--color-border)]";

function Dash() {
  return (
    <span className="text-fg-muted">
      <span aria-hidden="true">—</span>
      <span className="sr-only">{copy.common.none}</span>
    </span>
  );
}

function StateCell({ mcp }: { mcp: McpDetail }) {
  if (mcp.config_error) return <ConfigErrorBadge />;
  if (!mcp.live) return <span className="text-xs text-fg-muted">{copy.mcp.noLive}</span>;
  return <StatusBadge state={mcp.live.state} issue={mcp.live.issue} />;
}

/** A chip is current only for its own filter (the plain list must not match ?state=…). */
const EXACT = { exact: true, includeSearch: true } as const;

function FilterChips({ list, active }: { list: McpDetail[]; active: McpState | undefined }) {
  const counts = useMemo(() => {
    const c = new Map<McpState, number>();
    for (const m of list) if (m.live) c.set(m.live.state, (c.get(m.live.state) ?? 0) + 1);
    return c;
  }, [list]);
  const chip =
    "inline-flex h-(--size-control-sm) items-center gap-1.5 rounded-sm border px-2.5 text-sm whitespace-nowrap transition-[background-color,border-color] duration-(--motion-fast) ease-hover hover:bg-hover aria-[current=page]:border-fg aria-[current=page]:bg-selected aria-[current=page]:font-semibold";

  return (
    <nav aria-label={copy.mcp.filterLabel}>
      <ul className="flex flex-wrap gap-1.5">
        <li>
          <Link to="/admin/mcps" search={{}} activeOptions={EXACT} className={chip}>
            {copy.mcp.filterAll} <span className="tabular-nums text-fg-muted">{list.length}</span>
          </Link>
        </li>
        {STATES.map((s) => {
          const Icon = STATE_ICONS[s];
          const n = counts.get(s) ?? 0;
          return (
            <li key={s}>
              <Link
                to="/admin/mcps"
                search={{ state: s }}
                activeOptions={EXACT}
                className={cn(chip, n === 0 && active !== s && "text-fg-muted")}
              >
                <Icon aria-hidden="true" className="size-3.5" />
                {copy.states[s]} <span className="tabular-nums text-fg-muted">{n}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function SortIcon({ dir }: { dir: false | "asc" | "desc" }) {
  if (dir === "asc") return <ArrowUpIcon aria-hidden="true" className="size-3.5" />;
  if (dir === "desc") return <ArrowDownIcon aria-hidden="true" className="size-3.5" />;
  return <ChevronsUpDownIcon aria-hidden="true" className="size-3.5 opacity-60" />;
}

const ARIA_SORT = { asc: "ascending", desc: "descending" } as const;

/** The rows in the given order of ids; rows not in it (new MCPs) go last in their sorted order. */
function holdOrder(rows: McpRow[], order: string[]): McpRow[] {
  const rank = new Map(order.map((id, i) => [id, i]));
  return rows.toSorted((a, b) => (rank.get(a.id) ?? Infinity) - (rank.get(b.id) ?? Infinity));
}

function McpTable({ data }: { data: McpDetail[] }) {
  const table = useTable({
    features,
    columns,
    data,
    getRowId: (m) => String(m.id),
    enableSortingRemoval: false,
    initialState: { sorting: [{ id: "state", desc: false }] },
  });
  // While the pointer is over the rows, a live state change must not move the row under it (the
  // next click would land on another MCP's button): keep the order from when the pointer came in.
  const [held, setHeld] = useState<string[] | null>(null);
  const sorted = table.getRowModel().rows;
  const rows = held ? holdOrder(sorted, held) : sorted;

  return (
    // the table scrolls inside its own frame in a narrow window; the page never scrolls sideways
    <div className="rounded-md border bg-surface">
      <Table aria-label={copy.mcp.listLabel}>
        <TableHeader>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id} className="hover:bg-transparent">
              {group.headers.map((header) => {
                const sortable = SORTABLE.has(header.column.id);
                const dir = header.column.getIsSorted();
                return (
                  <TableHead
                    key={header.id}
                    scope="col"
                    aria-sort={sortable ? (dir ? ARIA_SORT[dir] : "none") : undefined}
                    className={cn(NUMERIC.has(header.column.id) && "text-right", header.column.id === "actions" && STICKY)}
                  >
                    {sortable ? (
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        className={cn(
                          "-mx-1 inline-flex min-h-6 items-center gap-1 rounded-xs px-1 hover:text-fg",
                          dir && "text-fg",
                        )}
                      >
                        <table.FlexRender header={header} />
                        <SortIcon dir={dir} />
                      </button>
                    ) : (
                      <table.FlexRender header={header} />
                    )}
                  </TableHead>
                );
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody onPointerEnter={() => setHeld(sorted.map((r) => r.id))} onPointerLeave={() => setHeld(null)}>
          {rows.map((row) => (
            <TableRow key={row.id} data-id={row.original.id}>
              {row.getAllCells().map((cell) => {
                const id = cell.column.id;
                if (id === "name") {
                  return (
                    <th key={cell.id} scope="row" className="px-3 py-2 text-left align-middle font-normal whitespace-nowrap">
                      <table.FlexRender cell={cell} />
                    </th>
                  );
                }
                return (
                  <TableCell key={cell.id} className={cn(NUMERIC.has(id) && "text-right tabular-nums", id === "actions" && STICKY)}>
                    <table.FlexRender cell={cell} />
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/**
 * Every MCP in one dense table, worst state first (U17), updated live from SSE through the query
 * cache (connectLive) without refetching. `?state=` narrows it; the chips carry the counts. No row
 * animation (tables never move: direction.md §6).
 */
export function McpListPage() {
  const me = useSession();
  const { state } = route.useSearch();
  const { data, isPending, isError } = useMcps();
  const createReason = denyReason(me, "create_mcp");

  const rows = useMemo(() => (data && state ? data.filter((m) => m.live?.state === state) : data), [data, state]);

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-fg">{copy.mcp.title}</h1>
        {createReason === null ? (
          <Button asChild>
            <Link to="/admin/mcps/new">
              <PlusIcon aria-hidden="true" />
              {copy.mcp.create}
            </Link>
          </Button>
        ) : (
          <WithReason reason={createReason} side="left">
            <Button>
              <PlusIcon aria-hidden="true" />
              {copy.mcp.create}
            </Button>
          </WithReason>
        )}
      </div>

      {isPending ? (
        <div role="status" className="flex flex-col gap-2">
          <span className="sr-only">{copy.common.loading}</span>
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : isError ? (
        <p role="alert" className="text-sm text-fg">
          {copy.mcp.listError}
        </p>
      ) : data.length === 0 ? (
        <p className="max-w-(--size-prose) text-sm text-fg-muted">{copy.mcp.listEmpty}</p>
      ) : (
        <>
          <FilterChips list={data} active={state} />
          {rows && rows.length > 0 ? (
            <McpTable data={rows} />
          ) : (
            <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm text-fg-muted">
              {copy.mcp.filterEmpty(state ? copy.states[state] : copy.mcp.filterAll)}
              <Link to="/admin/mcps" search={{}} className="font-semibold text-fg underline underline-offset-4">
                {copy.mcp.clearFilter}
              </Link>
            </p>
          )}
        </>
      )}
    </>
  );
}
