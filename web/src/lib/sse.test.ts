import { createSseParser, type SseEvent } from "./sse";

it("parses events split across chunks, CRLF and comments", () => {
  const out: SseEvent[] = [];
  let pings = 0;
  const feed = createSseParser((e) => out.push(e), () => pings++);
  feed('event: board\ndata: {"now":');
  feed('"x","mcps":[]}\n\n: ping\n\nevent: mcp\r\ndata: {"id":1}\r\n\r\n');
  expect(out).toEqual([
    { event: "board", data: '{"now":"x","mcps":[]}' },
    { event: "mcp", data: '{"id":1}' },
  ]);
  expect(pings).toBe(1);
});

it("joins multi-line data and defaults the event name", () => {
  const out: SseEvent[] = [];
  const feed = createSseParser((e) => out.push(e));
  feed("data: a\ndata: b\n\n");
  expect(out).toEqual([{ event: "message", data: "a\nb" }]);
});

it("does not dispatch an unterminated event", () => {
  const out: SseEvent[] = [];
  createSseParser((e) => out.push(e))("event: mcp\ndata: {}\n");
  expect(out).toEqual([]);
});

it("handles a CRLF split between chunks and bare CR line ends", () => {
  const out: SseEvent[] = [];
  const feed = createSseParser((e) => out.push(e));
  feed("event: a\r");
  feed("\ndata: 1\r");
  feed("\n\r");
  feed("\nevent: b\rdata: 2\r\r");
  expect(out).toEqual([
    { event: "a", data: "1" },
    { event: "b", data: "2" },
  ]);
});

it("strips one leading space only, keeps colons in values and ignores id/retry/unknown fields", () => {
  const out: SseEvent[] = [];
  const feed = createSseParser((e) => out.push(e));
  feed("id: 7\nretry: 10\nfoo: bar\nevent:mcp\ndata:  two spaces: x\n\n");
  expect(out).toEqual([{ event: "mcp", data: " two spaces: x" }]);
});

it("resets the event name after each dispatch and skips blocks without data", () => {
  const out: SseEvent[] = [];
  const feed = createSseParser((e) => out.push(e));
  feed("event: board\n\ndata: x\n\n");
  expect(out).toEqual([{ event: "message", data: "x" }]);
});

it("treats a field line without a colon as a field with an empty value", () => {
  const out: SseEvent[] = [];
  const feed = createSseParser((e) => out.push(e));
  feed("data\ndata\n\n");
  expect(out).toEqual([{ event: "message", data: "\n" }]);
});
