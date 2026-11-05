import { render, screen, within } from "@testing-library/react";
import { copy } from "@/copy/ko";
import { TextDiff } from "./TextDiff";

const rows = () => screen.getAllByRole("row").filter((r) => r.hasAttribute("data-op"));

it("marks removed and added lines", () => {
  render(<TextDiff before={"a\nb\n"} after={"a\nc\n"} labels={["v1", "현재"]} />);
  expect(screen.getByText("b").closest("[data-op]")).toHaveAttribute("data-op", "del");
  expect(screen.getByText("c").closest("[data-op]")).toHaveAttribute("data-op", "add");
  expect(screen.getByText("a").closest("[data-op]")).toHaveAttribute("data-op", "same");
});

it("numbers lines on each side and shows a sign besides the colour", () => {
  render(<TextDiff before={"a\nb\n"} after={"a\nc\nd\n"} labels={["v1", "현재"]} />);
  const [same, del, add1, add2] = rows() as [HTMLElement, HTMLElement, HTMLElement, HTMLElement];
  expect(within(same).getAllByRole("cell").map((c) => c.textContent)).toEqual(["1", "1", "", "a"]);
  expect(within(del).getAllByRole("cell").map((c) => c.textContent)).toEqual(["2", "", `−${copy.diff.removed}`, "b"]);
  expect(within(add1).getAllByRole("cell").map((c) => c.textContent)).toEqual(["", "2", `+${copy.diff.added}`, "c"]);
  expect(within(add2).getAllByRole("cell").map((c) => c.textContent)).toEqual(["", "3", `+${copy.diff.added}`, "d"]);
});

it("ignores CRLF versus LF and a missing final newline", () => {
  render(<TextDiff before={"a\r\nb\r\n"} after={"a\nb"} labels={["v1", "현재"]} />);
  expect(screen.getByText(copy.diff.same)).toBeInTheDocument();
  expect(rows().every((r) => r.getAttribute("data-op") === "same")).toBe(true);
});

it("names the two sides in the table caption and column headers", () => {
  render(<TextDiff before={"x\n"} after={"y\n"} labels={["버전 1", "현재"]} />);
  expect(screen.getByRole("table", { name: copy.diff.caption("버전 1", "현재") })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "버전 1" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "현재" })).toBeInTheDocument();
  expect(screen.getByText(copy.diff.summary(1, 1))).toBeInTheDocument();
});

it("keeps empty lines as rows", () => {
  render(<TextDiff before={"a\n\nb\n"} after={"a\n\nb\n"} labels={["v1", "현재"]} />);
  expect(rows()).toHaveLength(3);
});
