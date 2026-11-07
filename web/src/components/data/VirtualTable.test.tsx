import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createColumnHelper } from "@tanstack/react-table";
import { VirtualTable, vtFeatures } from "./VirtualTable";

interface Row {
  id: number;
  name: string;
}

const helper = createColumnHelper<typeof vtFeatures, Row>();
const columns = helper.columns([
  helper.accessor("id", { header: "번호", meta: { width: "6rem", rowHeader: true } }),
  helper.accessor("name", { header: "이름", meta: { width: "12rem" } }),
]);
const rows = (n: number): Row[] => Array.from({ length: n }, (_, i) => ({ id: i, name: `row-${i}` }));

beforeEach(() => {
  // jsdom lays nothing out: the scroller reports a 320 px viewport (10 rows of 32 px)
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(320);
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(800);
});

function renderTable(p: Partial<Parameters<typeof VirtualTable<Row>>[0]> = {}) {
  const props = {
    rows: rows(1000),
    columns,
    getRowId: (r: Row) => String(r.id),
    onRowOpen: vi.fn(),
    hasMore: false,
    onLoadMore: vi.fn(),
    ariaLabel: "목록",
    ...p,
  };
  render(<VirtualTable<Row> {...props} />);
  return props;
}

const bodyRows = () => within(screen.getByRole("table", { name: "목록" })).getAllByRole("row").filter((r) => r.closest("tbody"));

it("renders a semantic table with only a window of the rows", () => {
  renderTable();
  const table = screen.getByRole("table", { name: "목록" });
  expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["번호", "이름"]);
  const visible = bodyRows();
  expect(visible.length).toBeGreaterThanOrEqual(10);
  expect(visible.length).toBeLessThanOrEqual(10 + 2 * 20 + 1); // viewport + overscan 20
  expect(visible[0]).toHaveAttribute("aria-rowindex", "2"); // the header row is 1
  expect(visible[0]).toHaveAttribute("tabindex", "0");
  expect(within(visible[0]!).getByRole("rowheader")).toHaveTextContent("0");
  expect(table).toHaveAttribute("aria-rowcount", "1001");
});

it("pads the scroll height with hidden spacer rows instead of real ones", () => {
  renderTable();
  const spacers = document.querySelectorAll("tbody tr[aria-hidden=true]");
  expect(spacers.length).toBeGreaterThanOrEqual(1);
  const bottom = spacers[spacers.length - 1] as HTMLElement;
  expect(parseFloat(bottom.style.height)).toBeGreaterThan(900 * 32);
});

it("moves focus with the arrow keys and opens a row with Enter", async () => {
  const p = renderTable();
  bodyRows()[0]!.focus();
  await userEvent.keyboard("{ArrowDown}{ArrowDown}{ArrowUp}");
  expect(document.activeElement).toHaveAttribute("aria-rowindex", "3");
  await userEvent.keyboard("{Enter}");
  expect(p.onRowOpen).toHaveBeenCalledWith({ id: 1, name: "row-1" });
});

it("opens a row on click", async () => {
  const p = renderTable({ rows: rows(3) });
  await userEvent.click(screen.getByText("row-2"));
  expect(p.onRowOpen).toHaveBeenCalledWith({ id: 2, name: "row-2" });
});

it("asks for more once the last rendered row is within 20 of the end", () => {
  const p = renderTable({ rows: rows(30), hasMore: true });
  expect(p.onLoadMore).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("table", { name: "목록" })).toHaveAttribute("aria-rowcount", "-1"); // total unknown
});

it("does not ask for more far from the end or when there is no more", () => {
  const far = renderTable({ hasMore: true });
  expect(far.onLoadMore).not.toHaveBeenCalled();
});

it("does not ask for more when the server said this was the last page", () => {
  const p = renderTable({ rows: rows(30), hasMore: false });
  expect(p.onLoadMore).not.toHaveBeenCalled();
});

it("scrolls inside its own container and never animates", () => {
  renderTable();
  const scroller = document.querySelector("[data-scroll-container]") as HTMLElement;
  expect(scroller).toContainElement(screen.getByRole("table", { name: "목록" }));
  expect(scroller.className).toMatch(/overflow-auto/);
  expect(document.querySelector("[data-anim]")).toBeNull();
  expect(document.querySelector("[class*='transition'], [class*='animate']")).toBeNull();
});

it("keeps one row in the tab order (roving tabindex), following the focused row", async () => {
  renderTable();
  const [first, second] = bodyRows();
  expect(first).toHaveAttribute("tabindex", "0");
  expect(second).toHaveAttribute("tabindex", "-1");
  first!.focus();
  await userEvent.keyboard("{ArrowDown}");
  expect(bodyRows()[1]).toHaveAttribute("tabindex", "0");
  expect(bodyRows()[0]).toHaveAttribute("tabindex", "-1");
  expect(bodyRows().filter((r) => r.getAttribute("tabindex") === "0")).toHaveLength(1);
});
