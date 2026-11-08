// The same cases run in server/tests/test_icon_emoji.py: client and server agree on what one emoji is.
import cases from "./mcp-icon-cases.json";
import { isMcpEmoji, MAX_ICON_UTF16 } from "./mcp-emoji";

const show = (v: string) => [...v].map((c) => c.codePointAt(0)!.toString(16)).join(" ") || "empty";

it.each(cases.valid.map((v) => [show(v), v]))("accepts %s", (_label, v) => {
  expect(isMcpEmoji(v)).toBe(true);
});

it.each(cases.invalid.map((v) => [show(v), v]))("refuses %s", (_label, v) => {
  expect(isMcpEmoji(v)).toBe(false);
});

it("refuses non-strings and keeps the UTF-16 limit", () => {
  for (const v of [null, undefined, 1, {}, ["🤖"]]) expect(isMcpEmoji(v)).toBe(false);
  expect(Math.max(...cases.invalid.map((v) => v.length))).toBeGreaterThan(MAX_ICON_UTF16);
});
