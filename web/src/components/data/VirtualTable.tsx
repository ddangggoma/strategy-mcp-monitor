// A long, read-only table that renders only the rows in view (log and audit screens, W33).
// TanStack Table owns the column definitions and headers; TanStack Virtual decides which rows exist.
// Rows have one fixed height so the scroll size is exact without measuring, and the table uses a
// fixed layout with declared column widths, so columns never jump as rows scroll in and out.
// No animation anywhere (spec §6.5): rows simply appear.
import { tableFeatures, useTable, type ColumnDef, type RowData } from "@tanstack/react-table";
import { observeElementRect, useVirtualizer, type Virtualizer } from "@tanstack/react-virtual";
import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface VirtualColumnMeta {
  /** CSS width of the column (fixed table layout); one column without it takes the rest. */
  width?: string;
  /** The column whose cell names the row (`<th scope=row>`). */
  rowHeader?: boolean;
  /** Extra classes for the cells of this column. */
  className?: string;
}

/** The feature set every VirtualTable column is typed against (`createColumnHelper<typeof vtFeatures, T>()`). */
export const vtFeatures = tableFeatures({ columnMeta: {} as VirtualColumnMeta });

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- columns of one table hold different value types
export type VirtualColumn<T extends RowData> = ColumnDef<typeof vtFeatures, T, any>;

/**
 * The scroller's viewport, as the virtualizer measures it (client box). A scroller with no client
 * box yet (not laid out, or a DOM without layout) falls back to its border box rather than to zero
 * rows.
 */
function observeRect(instance: Virtualizer<HTMLDivElement, Element>, cb: (rect: { width: number; height: number }) => void) {
  return observeElementRect(instance, (rect) => {
    if (rect.height > 0) return cb(rect);
    const box = instance.scrollElement?.getBoundingClientRect();
    cb(box && box.height > 0 ? { width: Math.round(box.width), height: Math.round(box.height) } : rect);
  });
}

/** Rows from the end at which the next page is requested. */
const LOAD_AHEAD = 20;

export interface VirtualTableProps<T extends RowData> {
  rows: T[];
  columns: VirtualColumn<T>[];
  /** Fixed row height in px (default 32). */
  rowHeight?: number;
  getRowId(r: T): string;
  onRowOpen(r: T): void;
  hasMore: boolean;
  onLoadMore(): void;
  ariaLabel: string;
  /** Viewport size before the first measurement (tests, first paint). */
  initialRect?: { width: number; height: number };
  /** Scroller height (CSS); the caller sizes it to the rest of the viewport. */
  height?: CSSProperties["height"];
  /** The table never gets narrower than this; a narrower scroller scrolls sideways. */
  minWidth?: string;
  /** Under the last row, inside the scroller (a "loading more" line). */
  footer?: ReactNode;
  className?: string;
}

export function VirtualTable<T extends RowData>({
  rows,
  columns,
  rowHeight = 32,
  getRowId,
  onRowOpen,
  hasMore,
  onLoadMore,
  ariaLabel,
  initialRect,
  height,
  minWidth,
  footer,
  className,
}: VirtualTableProps<T>) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const table = useTable({ features: vtFeatures, columns, data: rows, getRowId });
  const modelRows = table.getRowModel().rows;

  // the virtualizer re-renders this component itself; none of its functions are memoized here
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: modelRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 20,
    initialRect,
    observeElementRect: observeRect,
  });
  const items = virtualizer.getVirtualItems();
  // roving tabindex: one row is in the tab order (Tab leaves the table in one step). It is the last
  // focused row, or the first rendered one once that row has scrolled out of the rendered window.
  const [active, setActive] = useState(0);
  const tabRow = items.some((i) => i.index === active) ? active : (items[0]?.index ?? -1);
  const lastIndex = items.at(-1)?.index ?? -1;

  // one request per length: a page that is still loading (or failed) is not asked for again
  // until the rows change
  const askedAt = useRef(-1);
  useEffect(() => {
    if (!hasMore || modelRows.length === 0 || lastIndex < modelRows.length - LOAD_AHEAD) return;
    if (askedAt.current === modelRows.length) return;
    askedAt.current = modelRows.length;
    onLoadMore();
  }, [hasMore, lastIndex, modelRows.length, onLoadMore]);

  const focusRow = useCallback(
    (index: number) => {
      const scroller = scrollRef.current;
      if (!scroller || index < 0 || index >= modelRows.length) return;
      const find = () => scroller.querySelector<HTMLElement>(`tbody tr[data-index="${index}"]`);
      virtualizer.scrollToIndex(index, { align: "auto" });
      const now = find();
      if (now) now.focus({ preventScroll: true });
      // a row outside the rendered window exists once the virtualizer has scrolled there
      else requestAnimationFrame(() => find()?.focus({ preventScroll: true }));
    },
    [modelRows.length, virtualizer],
  );

  const onRowKey = (e: KeyboardEvent<HTMLTableRowElement>, index: number, original: T) => {
    if (e.target !== e.currentTarget) return; // a control inside a cell keeps its own keys
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      focusRow(index + (e.key === "ArrowDown" ? 1 : -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      onRowOpen(original);
    }
  };

  const total = virtualizer.getTotalSize();
  const top = items[0]?.start ?? 0;
  const bottom = items.length > 0 ? total - items.at(-1)!.end : 0;
  const headers = table.getHeaderGroups();
  const span = columns.length;

  return (
    <div
      ref={scrollRef}
      data-scroll-container=""
      style={{ height }}
      className={cn("relative min-w-0 overflow-auto overscroll-contain rounded-md border bg-surface", className)}
    >
      <table
        aria-label={ariaLabel}
        aria-rowcount={hasMore ? -1 : modelRows.length + 1}
        style={{ minWidth }}
        className="w-full table-fixed border-separate border-spacing-0 text-sm tabular-nums"
      >
        <colgroup>
          {headers[0]?.headers.map((h) => (
            <col key={h.id} style={{ width: h.column.columnDef.meta?.width }} />
          ))}
        </colgroup>
        <thead className="sticky top-0 z-10 bg-surface">
          {headers.map((group) => (
            <tr key={group.id} aria-rowindex={1}>
              {group.headers.map((header) => (
                <th
                  key={header.id}
                  scope="col"
                  className="h-9 border-b px-3 text-left align-middle text-xs font-medium whitespace-nowrap text-fg-muted"
                >
                  <table.FlexRender header={header} />
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {top > 0 ? (
            <tr aria-hidden="true" style={{ height: top }}>
              <td colSpan={span} className="p-0" />
            </tr>
          ) : null}
          {items.map((item) => {
            const row = modelRows[item.index]!;
            return (
              <tr
                key={row.id}
                data-index={item.index}
                aria-rowindex={item.index + 2}
                tabIndex={item.index === tabRow ? 0 : -1}
                onFocus={() => setActive(item.index)}
                style={{ height: rowHeight }}
                onClick={() => onRowOpen(row.original)}
                onKeyDown={(e) => onRowKey(e, item.index, row.original)}
                // the global focus ring, drawn inside the row so the scroller does not clip it
                className="cursor-default hover:bg-hover focus-visible:bg-selected focus-visible:-outline-offset-2"
              >
                {row.getAllCells().map((cell) => {
                  const meta = cell.column.columnDef.meta;
                  const cls = cn("truncate border-b px-3 align-middle whitespace-nowrap", meta?.className);
                  return meta?.rowHeader ? (
                    <th key={cell.id} scope="row" className={cn(cls, "text-left font-normal")}>
                      <table.FlexRender cell={cell} />
                    </th>
                  ) : (
                    <td key={cell.id} className={cls}>
                      <table.FlexRender cell={cell} />
                    </td>
                  );
                })}
              </tr>
            );
          })}
          {bottom > 0 ? (
            <tr aria-hidden="true" style={{ height: bottom }}>
              <td colSpan={span} className="p-0" />
            </tr>
          ) : null}
        </tbody>
      </table>
      {footer}
    </div>
  );
}
