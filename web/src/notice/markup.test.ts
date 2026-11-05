import { render } from "@testing-library/react";
import { createElement } from "react";
import { parseNoticeMarkup, renderNoticeMarkup } from "./markup";

it("parses paragraphs, line breaks, bullets and bold", () => {
  expect(parseNoticeMarkup("**안내**입니다\n둘째 줄\n\n- 접속 정보\n- **명령** 기록")).toEqual([
    { t: "p", lines: [[{ t: "strong", v: "안내" }, { t: "text", v: "입니다" }], [{ t: "text", v: "둘째 줄" }]] },
    { t: "ul", items: [[{ t: "text", v: "접속 정보" }], [{ t: "strong", v: "명령" }, { t: "text", v: " 기록" }]] },
  ]);
});

it("keeps unclosed ** and HTML as literal text", () => {
  expect(parseNoticeMarkup("a ** b <b>x</b>")).toEqual([{ t: "p", lines: [[{ t: "text", v: "a ** b <b>x</b>" }]] }]);
});

it("a block with a non-bullet line is a paragraph", () => {
  expect(parseNoticeMarkup("- a\nb")[0]!.t).toBe("p");
  expect(parseNoticeMarkup("- a\nb")).toEqual([{ t: "p", lines: [[{ t: "text", v: "- a" }], [{ t: "text", v: "b" }]] }]);
});

it("normalizes CRLF and collapses multiple blank lines", () => {
  expect(parseNoticeMarkup("a\r\n\r\n\r\nb")).toHaveLength(2);
  expect(parseNoticeMarkup("a\r\rb\rc")).toEqual([
    { t: "p", lines: [[{ t: "text", v: "a" }]] },
    { t: "p", lines: [[{ t: "text", v: "b" }], [{ t: "text", v: "c" }]] },
  ]);
  // a line of spaces is a blank line too; leading and trailing blank lines make no empty blocks
  expect(parseNoticeMarkup("\n\na\n   \nb\n\n")).toHaveLength(2);
  expect(parseNoticeMarkup("")).toEqual([]);
  expect(parseNoticeMarkup(" \n\t\n")).toEqual([]);
});

it("reads several bold runs, and an empty or unmatched marker as text", () => {
  expect(parseNoticeMarkup("**a** 그리고 **b**")).toEqual([
    { t: "p", lines: [[{ t: "strong", v: "a" }, { t: "text", v: " 그리고 " }, { t: "strong", v: "b" }]] },
  ]);
  expect(parseNoticeMarkup("****")).toEqual([{ t: "p", lines: [[{ t: "text", v: "****" }]] }]);
  expect(parseNoticeMarkup("**a** **b")).toEqual([
    { t: "p", lines: [[{ t: "strong", v: "a" }, { t: "text", v: " **b" }]] },
  ]);
  // bold never spans a line break
  expect(parseNoticeMarkup("**a\nb**")).toEqual([
    { t: "p", lines: [[{ t: "text", v: "**a" }], [{ t: "text", v: "b**" }]] },
  ]);
});

it("needs a space after the dash for a bullet", () => {
  expect(parseNoticeMarkup("-a\n-b")[0]!.t).toBe("p");
  expect(parseNoticeMarkup("- a\n-  b")).toEqual([{ t: "ul", items: [[{ t: "text", v: "a" }], [{ t: "text", v: " b" }]] }]);
});

it("renders paragraphs with <br> between lines, lists and <strong>, all as text", () => {
  const blocks = parseNoticeMarkup("**굵게** 첫 줄\n둘째 줄\n\n- 하나\n- <img src=x onerror=alert(1)>");
  const { container } = render(createElement("div", null, renderNoticeMarkup(blocks)));
  const p = container.querySelector("p")!;
  expect(p.querySelector("strong")).toHaveTextContent("굵게");
  expect(p.querySelectorAll("br")).toHaveLength(1);
  expect(p).toHaveTextContent("굵게 첫 줄둘째 줄");
  const items = [...container.querySelectorAll("ul > li")].map((li) => li.textContent);
  expect(items).toEqual(["하나", "<img src=x onerror=alert(1)>"]);
  expect(container.querySelector("img")).toBeNull();
});
