import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { copy } from "@/copy/ko";
import { histogramFixture } from "../../../tests/msw/fixtures";
import { LogHistogram } from "./LogHistogram";

const H = histogramFixture(); // 13:00–14:00 KST, 600 s buckets, counts [1, 2, 3, 0, 0, 4]
const rect = (width: number) => ({ left: 0, top: 0, width, height: 120, right: width, bottom: 120, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;

it("drag across buckets selects their minute-aligned span", () => {
  const onSelect = vi.fn(); render(<LogHistogram data={H} onSelect={onSelect} />);
  const svg = screen.getByTestId("log-histogram"); vi.spyOn(svg, "getBoundingClientRect").mockReturnValue(rect(600));
  fireEvent.pointerDown(svg, { clientX: 150, pointerId: 1 }); fireEvent.pointerMove(svg, { clientX: 350, pointerId: 1 });
  fireEvent.pointerUp(svg, { clientX: 350, pointerId: 1 });
  expect(onSelect).toHaveBeenCalledWith("2026-11-04T13:10:00.000+09:00", "2026-11-04T13:40:00.000+09:00");
});
it("selects with Shift+Arrow and applies with Enter", async () => {
  const onSelect = vi.fn(); render(<LogHistogram data={H} onSelect={onSelect} />);
  screen.getByTestId("log-histogram").focus();
  await userEvent.keyboard("{ArrowRight}{Shift>}{ArrowRight}{ArrowRight}{/Shift}{Enter}");
  expect(onSelect).toHaveBeenCalledWith("2026-11-04T13:10:00.000+09:00", "2026-11-04T13:40:00.000+09:00");
});
it("Escape clears the selection without applying", async () => {
  const onSelect = vi.fn(); render(<LogHistogram data={H} onSelect={onSelect} />);
  screen.getByTestId("log-histogram").focus();
  await userEvent.keyboard("{Shift>}{ArrowRight}{/Shift}{Escape}{Enter}");
  expect(onSelect).toHaveBeenCalledWith("2026-11-04T13:00:00.000+09:00", "2026-11-04T13:10:00.000+09:00");
});
it("histogram keeps a 2px minimum bar and drops labels when narrow", () => {
  const many = histogramFixture({ bucket_sec: 60, starts: Array.from({ length: 200 }, (_, i) => new Date(Date.UTC(2026, 10, 4, 4, 0) + i * 60000).toISOString()),
    series: [{ key: null, counts: Array.from({ length: 200 }, () => 1) }] });
  render(<LogHistogram data={many} onSelect={vi.fn()} width={400} />);
  const bars = screen.getByTestId("log-histogram").querySelectorAll("rect[data-bucket]");
  expect(bars).toHaveLength(200);
  for (const b of bars) expect(Number(b.getAttribute("width"))).toBeGreaterThanOrEqual(2);
  expect(screen.getByTestId("log-histogram").querySelectorAll("text[data-axis]")).toHaveLength(2);
});
it("has no animation markers", () => {
  render(<LogHistogram data={H} onSelect={vi.fn()} />);
  expect(document.querySelector("[data-anim]")).toBeNull();
});

// ---- beyond the plan ------------------------------------------------------------------

it("drags right to left as well, and a click selects the one bucket under it", () => {
  const onSelect = vi.fn(); render(<LogHistogram data={H} onSelect={onSelect} />);
  const svg = screen.getByTestId("log-histogram"); vi.spyOn(svg, "getBoundingClientRect").mockReturnValue(rect(600));
  fireEvent.pointerDown(svg, { clientX: 590, pointerId: 1, button: 0 }); fireEvent.pointerMove(svg, { clientX: 420, pointerId: 1 });
  fireEvent.pointerUp(svg, { clientX: 420, pointerId: 1 });
  expect(onSelect).toHaveBeenLastCalledWith("2026-11-04T13:40:00.000+09:00", "2026-11-04T14:00:00.000+09:00");
  fireEvent.pointerDown(svg, { clientX: 5, pointerId: 2, button: 0 }); fireEvent.pointerUp(svg, { clientX: 5, pointerId: 2 });
  expect(onSelect).toHaveBeenLastCalledWith("2026-11-04T13:00:00.000+09:00", "2026-11-04T13:10:00.000+09:00");
});

it("clamps pointer positions outside the plot to the first and last bucket", () => {
  const onSelect = vi.fn(); render(<LogHistogram data={H} onSelect={onSelect} />);
  const svg = screen.getByTestId("log-histogram"); vi.spyOn(svg, "getBoundingClientRect").mockReturnValue(rect(600));
  fireEvent.pointerDown(svg, { clientX: -40, pointerId: 1 }); fireEvent.pointerMove(svg, { clientX: 900, pointerId: 1 });
  fireEvent.pointerUp(svg, { clientX: 900, pointerId: 1 });
  expect(onSelect).toHaveBeenCalledWith("2026-11-04T13:00:00.000+09:00", "2026-11-04T14:00:00.000+09:00");
});

it("ignores a secondary-button press", () => {
  const onSelect = vi.fn(); render(<LogHistogram data={H} onSelect={onSelect} />);
  const svg = screen.getByTestId("log-histogram"); vi.spyOn(svg, "getBoundingClientRect").mockReturnValue(rect(600));
  fireEvent.pointerDown(svg, { clientX: 150, pointerId: 1, button: 2 }); fireEvent.pointerUp(svg, { clientX: 150, pointerId: 1 });
  expect(onSelect).not.toHaveBeenCalled();
});

it("never ends a selection after the histogram's own end", async () => {
  const short = histogramFixture({ to: "2026-11-04T13:55:00.000+09:00" }); // last bar is cut at 13:55
  const onSelect = vi.fn(); render(<LogHistogram data={short} onSelect={onSelect} />);
  screen.getByTestId("log-histogram").focus();
  await userEvent.keyboard("{End}{Enter}");
  expect(onSelect).toHaveBeenCalledWith("2026-11-04T13:50:00.000+09:00", "2026-11-04T13:55:00.000+09:00");
});

it("keeps keyboard focus inside the buckets", async () => {
  const onSelect = vi.fn(); render(<LogHistogram data={H} onSelect={onSelect} />);
  screen.getByTestId("log-histogram").focus();
  await userEvent.keyboard("{ArrowLeft}{ArrowLeft}{Enter}");
  expect(onSelect).toHaveBeenLastCalledWith("2026-11-04T13:00:00.000+09:00", "2026-11-04T13:10:00.000+09:00");
  await userEvent.keyboard("{ArrowRight>9/}{Home}{Shift>}{End}{/Shift}{Enter}");
  expect(onSelect).toHaveBeenLastCalledWith("2026-11-04T13:00:00.000+09:00", "2026-11-04T14:00:00.000+09:00");
});

it("names the range and total, and announces the selection politely", async () => {
  render(<LogHistogram data={H} onSelect={vi.fn()} />);
  const svg = screen.getByTestId("log-histogram");
  expect(svg).toHaveAccessibleName(copy.logs.histogramLabel("13:00", "14:00", 10));
  svg.focus();
  await userEvent.keyboard("{Shift>}{ArrowRight}{ArrowRight}{/Shift}");
  const live = document.querySelector("[aria-live=polite]");
  expect(live).toHaveTextContent(copy.logs.selection("13:00", "13:30", 6));
});

it("stacks the category groups bottom-up in GROUP_STACK order with a legend", () => {
  const data = histogramFixture({
    series: [
      { key: "activity.command", counts: [4, 0, 0, 0, 0, 0] },
      { key: "auth", counts: [2, 0, 0, 0, 0, 0] },
      { key: "tamper", counts: [2, 0, 0, 0, 0, 0] },
    ],
    total: 8,
  });
  render(<LogHistogram data={data} onSelect={vi.fn()} width={600} />);
  const segs = [...screen.getByTestId("log-histogram").querySelectorAll("rect[data-bucket='0']")];
  expect(segs.map((s) => s.getAttribute("data-group"))).toEqual(["security", "activity"]); // auth + tamper fold into one
  const [security, activity] = segs.map((s) => Number(s.getAttribute("y")));
  expect(security!).toBeGreaterThan(activity!); // the first group sits on the baseline (larger y)
  const legend = screen.getByRole("list", { name: copy.logs.legend });
  expect(legend).toHaveTextContent(`${copy.logs.groups.security}${copy.logs.groups.activity}`);
});

it("has no legend for a single series", () => {
  render(<LogHistogram data={H} onSelect={vi.fn()} width={600} />);
  expect(screen.queryByRole("list", { name: copy.logs.legend })).toBeNull();
});

it("shows the bucket time and count on hover", () => {
  render(<LogHistogram data={H} onSelect={vi.fn()} />);
  const svg = screen.getByTestId("log-histogram"); vi.spyOn(svg, "getBoundingClientRect").mockReturnValue(rect(600));
  fireEvent.pointerMove(svg, { clientX: 250, pointerId: 1 });
  expect(screen.getByTestId("log-histogram-tip")).toHaveTextContent("13:20–13:30");
  expect(screen.getByTestId("log-histogram-tip")).toHaveTextContent(copy.logs.count(3));
  fireEvent.pointerLeave(svg, { pointerId: 1 });
  expect(screen.queryByTestId("log-histogram-tip")).toBeNull();
});

it("labels the axis with dates when the range spans days, and in full when wide", () => {
  const days = histogramFixture({
    from: "2026-11-03T00:00:00.000+09:00",
    to: "2026-11-05T00:00:00.000+09:00",
    bucket_sec: 28800,
    starts: ["2026-11-03T00:00:00.000+09:00", "2026-11-03T08:00:00.000+09:00", "2026-11-03T16:00:00.000+09:00",
      "2026-11-04T00:00:00.000+09:00", "2026-11-04T08:00:00.000+09:00", "2026-11-04T16:00:00.000+09:00"],
  });
  render(<LogHistogram data={days} onSelect={vi.fn()} width={1200} />);
  const labels = [...screen.getByTestId("log-histogram").querySelectorAll("text[data-axis]")].map((t) => t.textContent);
  expect(labels.length).toBeGreaterThan(2);
  expect(labels[0]).toBe("11-03 00:00");
  expect(labels.at(-1)).toBe("11-05 00:00");
});

it("starts the keyboard again at the first bar when new bars arrive", async () => {
  const onSelect = vi.fn();
  const wide = histogramFixture({
    bucket_sec: 60,
    starts: Array.from({ length: 60 }, (_, i) => new Date(Date.UTC(2026, 10, 4, 4, 0) + i * 60000).toISOString().replace("Z", "+00:00")),
    series: [{ key: null, counts: Array.from({ length: 60 }, () => 1) }],
  });
  const { rerender } = render(<LogHistogram data={wide} onSelect={onSelect} />);
  screen.getByTestId("log-histogram").focus();
  await userEvent.keyboard("{End}");
  rerender(<LogHistogram data={H} onSelect={onSelect} />); // 6 bars now
  await userEvent.keyboard("{Shift>}{ArrowRight}{/Shift}{Enter}");
  expect(onSelect).toHaveBeenLastCalledWith("2026-11-04T13:00:00.000+09:00", "2026-11-04T13:20:00.000+09:00");
  expect(document.activeElement).toBe(screen.getByTestId("log-histogram"));
});
