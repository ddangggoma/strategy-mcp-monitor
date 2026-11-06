import { createColumnHelper } from "@tanstack/react-table";
import { useCallback, useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import { VirtualTable, vtFeatures } from "@/components/data/VirtualTable";
import { Button } from "@/components/ui/button";
import { copy } from "@/copy/ko";
import type { LogItem, LogQuery } from "@/lib/api-types";
import { formatKstMs } from "@/lib/time";
import { cn } from "@/lib/utils";
import { useLogPages } from "../queries";
import { CATEGORY_GROUP, GROUP_COLOR_VAR } from "./categories";
import { LogDetail } from "./LogDetail";
import { summarize } from "./log-format";

const c = copy.logs.columns;
const ROW = 32;
const MIN_HEIGHT = 240; // px: room for ~6 rows in a 600 px high window
/** When the filters push the table low, it still gets half the window (the page scrolls to it). */
const MIN_SHARE = 0.5;
const BOTTOM_GAP = 24; // main's bottom padding

function Dash() {
  return (
    <span className="text-fg-muted">
      <span aria-hidden="true">—</span>
      <span className="sr-only">{copy.common.none}</span>
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
  helper.display({
    id: "cat",
    header: c.cat,
    meta: { width: "9rem" },
    cell: ({ row: { original: r } }) => (
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden="true" className="size-2 shrink-0 rounded-full" style={{ background: GROUP_COLOR_VAR[CATEGORY_GROUP[r.cat]] }} />
        {copy.logs.cats[r.cat] ?? r.cat}
      </span>
    ),
  }),
  helper.display({ id: "user", header: c.user, meta: { width: "11rem" }, cell: ({ row: { original: r } }) => r.user ?? <Dash /> }),
  helper.display({
    id: "session",
    header: c.session,
    meta: { width: "4.5rem", className: "font-mono" },
    cell: ({ row: { original: r } }) => r.session_id ?? <Dash />,
  }),
  helper.display({
    id: "ip",
    header: c.ip,
    meta: { width: "9rem", className: "font-mono" },
    cell: ({ row: { original: r } }) => r.client_ip ?? <Dash />,
  }),
  helper.display({
    id: "event",
    header: c.event,
    meta: { width: "11rem", className: "font-mono text-xs" },
    cell: ({ row: { original: r } }) => r.event ?? <Dash />,
  }),
  helper.display({ id: "summary", header: c.summary, cell: ({ row: { original: r } }) => summarize(r) }),
]);

/** The scroller takes the rest of the window below it, never less than half the window or MIN_HEIGHT. */
export function useRestOfViewport(ref: RefObject<HTMLElement | null>): number {
  const [height, setHeight] = useState(MIN_HEIGHT);
  useLayoutEffect(() => {
    const measure = () => {
      const el = ref.current;
      if (!el) return;
      const top = el.getBoundingClientRect().top + window.scrollY;
      setHeight(Math.max(MIN_HEIGHT, Math.round(window.innerHeight * MIN_SHARE), Math.floor(window.innerHeight - top - BOTTOM_GAP)));
    };
    measure();
    // the filters wrap and the banner comes and goes: anything above can move the table
    const ro = new ResizeObserver(measure);
    const main = ref.current?.closest("main");
    if (main) ro.observe(main);
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [ref]);
  return height;
}

/**
 * The log lines of the filter set, newest first, in a virtual table that fetches the next page as
 * its end comes near. A row opens the detail dialog.
 */
export function LogTable({
  query, onFilterUser, onFilterSession,
}: {
  query: LogQuery;
  onFilterUser(user: string): void;
  onFilterSession(id: number): void;
}) {
  const q = useLogPages(query);
  const [shown, setShown] = useState<LogItem | null>(null);
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLElement | null>(null);
  const openRow = useCallback((r: LogItem) => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setShown(r);
    setOpen(true);
  }, []);
  const returnFocus = useCallback((e: Event) => {
    e.preventDefault();
    // back to the row; a filter from the dialog can remove it, then to the table (or the page)
    const el = opener.current;
    if (el?.isConnected) el.focus();
    else (frame.current?.querySelector<HTMLElement>("tbody tr[data-index]") ?? document.getElementById("main"))?.focus();
  }, []);
  const frame = useRef<HTMLDivElement>(null);
  const height = useRestOfViewport(frame);
  const pages = q.data?.pages;
  const rows = useMemo(() => pages?.flatMap((p) => p.items) ?? [], [pages]);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = q;
  const loadMore = useCallback(() => {
    if (!isFetchingNextPage) void fetchNextPage();
  }, [fetchNextPage, isFetchingNextPage]);
  const getRowId = useCallback((r: LogItem) => String(r.id), []);

  let body;
  if (q.isPending) {
    // static placeholders: nothing in the log area moves (no pulsing skeleton)
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
        {copy.logs.loadError}
      </p>
    );
  } else if (rows.length === 0) {
    body = <p className="text-sm text-fg-muted">{copy.logs.empty}</p>;
  } else {
    body = (
      <VirtualTable<LogItem>
        // a new filter set starts at the top
        key={JSON.stringify(query)}
        rows={rows}
        columns={columns}
        rowHeight={ROW}
        getRowId={getRowId}
        onRowOpen={openRow}
        hasMore={!!hasNextPage && !q.isPlaceholderData}
        onLoadMore={loadMore}
        ariaLabel={copy.logs.title}
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
        onFilterSession={(id) => {
          setOpen(false);
          onFilterSession(id);
        }}
      />
    </div>
  );
}
