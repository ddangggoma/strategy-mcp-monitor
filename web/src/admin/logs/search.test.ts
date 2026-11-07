import { floorKstMinute, parseAuditSearch, parseLogSearch, resolveRange, toLogQuery } from "./search";

const NOW = new Date("2026-11-04T05:03:27.123Z"); // 14:03:27 KST

it.each([
  ["1h", "2026-11-04T13:04:00.000+09:00", "2026-11-04T14:04:00.000+09:00"],
  ["today", "2026-11-04T00:00:00.000+09:00", "2026-11-04T14:04:00.000+09:00"],
  ["yesterday", "2026-11-03T00:00:00.000+09:00", "2026-11-04T00:00:00.000+09:00"],
  ["7d", "2026-10-29T00:00:00.000+09:00", "2026-11-04T14:04:00.000+09:00"],
] as const)("resolves %s in KST minutes", (range, from, to) => {
  expect(resolveRange({ range }, NOW)).toEqual({ from, to });
});

it("custom from/to win over range and are minute-aligned", () => {
  expect(resolveRange({ range: "7d", from: "2026-11-04T01:15:42.000Z", to: "2026-11-04T11:00:00.000+09:00" }, NOW))
    .toEqual({ from: "2026-11-04T10:15:00.000+09:00", to: "2026-11-04T11:00:00.000+09:00" });
});

it("defaults to the last hour", () => {
  expect(resolveRange({}, NOW)).toEqual(resolveRange({ range: "1h" }, NOW));
});

it("drops invalid search values", () => {
  expect(parseLogSearch({ range: "2y", cat: ["auth", "nope"], users: "x", session: -1, view: "grid", from: "2026-11-04T10:00:00" }))
    .toEqual({ cat: ["auth"] });
});

it("builds the API query without empty filters", () => {
  expect(toLogQuery({ range: "1h", users: [], cat: ["auth"], q: "" }, NOW))
    .toEqual({ from: "2026-11-04T13:04:00.000+09:00", to: "2026-11-04T14:04:00.000+09:00", cat: ["auth"] });
});

it("keeps every valid search value exactly", () => {
  const raw = {
    range: "7d",
    from: "2026-11-04T10:15:00.000+09:00",
    to: "2026-11-04T01:00:00Z",
    users: ["CORP\\hong", "a@x.com"],
    cat: ["auth", "activity.command"],
    event: ["login"],
    outcome: ["fail", "timeout"],
    session: 3,
    ip: "10.0.3.21",
    q: "notepad",
    view: "timeline",
  };
  expect(parseLogSearch(raw)).toEqual(raw);
});

it("names every key, undefined when dropped, so the router cannot keep a malformed raw value", () => {
  // TanStack Router merges validateSearch's result over the raw search: an absent key would survive
  const parsed = parseLogSearch({ session: -1, view: "grid" });
  expect(Object.keys(parsed).sort()).toEqual(["cat", "event", "from", "ip", "outcome", "q", "range", "session", "to", "users", "view"]);
  expect(Object.values(parsed).every((v) => v === undefined)).toBe(true);
  expect(Object.keys(parseAuditSearch({})).sort()).toEqual(["channel", "from", "kind", "q", "range", "result", "to", "users"]);
});

it("reads values the router parsed as numbers back as text and drops the rest", () => {
  // TanStack Router JSON-parses each search value: a typed ?q=8812 arrives as a number
  expect(parseLogSearch({ q: 8812, session: "4", ip: "" })).toEqual({ q: "8812", session: 4 });
  expect(parseLogSearch({ session: 1.5, users: ["a", 3, ""], event: [], outcome: ["nope"], cat: "auth" })).toEqual({ users: ["a"] });
  expect(parseLogSearch({ from: "yesterday", to: "2026-13-40T10:00:00+09:00" })).toEqual({});
});

it("uses the range when only one custom bound is set", () => {
  expect(resolveRange({ range: "today", from: "2026-11-04T10:00:00.000+09:00" }, NOW))
    .toEqual({ from: "2026-11-04T00:00:00.000+09:00", to: "2026-11-04T14:04:00.000+09:00" });
});

it("does not move a now that is already on the minute", () => {
  expect(resolveRange({ range: "1h" }, new Date("2026-11-04T05:03:00.000Z")))
    .toEqual({ from: "2026-11-04T13:03:00.000+09:00", to: "2026-11-04T14:03:00.000+09:00" });
});

it("uses the KST day, not the UTC one, for today and yesterday", () => {
  const earlyKst = new Date("2026-11-03T15:30:00.000Z"); // 2026-11-04 00:30 KST, still 11-03 in UTC
  expect(resolveRange({ range: "today" }, earlyKst))
    .toEqual({ from: "2026-11-04T00:00:00.000+09:00", to: "2026-11-04T00:30:00.000+09:00" });
  expect(resolveRange({ range: "yesterday" }, earlyKst))
    .toEqual({ from: "2026-11-03T00:00:00.000+09:00", to: "2026-11-04T00:00:00.000+09:00" });
});

it("floors any offset time to its KST minute", () => {
  expect(floorKstMinute("2026-11-04T05:03:59.999Z")).toBe("2026-11-04T14:03:00.000+09:00");
  expect(floorKstMinute("2026-11-04T23:59:30-05:00")).toBe("2026-11-05T13:59:00.000+09:00");
});

it("passes every non-empty filter to the API, trimming the keyword", () => {
  expect(toLogQuery({ users: ["a"], event: ["login"], outcome: ["fail"], session: 0, ip: "10.0.0.1", q: "  calc  " }, NOW)).toEqual({
    from: "2026-11-04T13:04:00.000+09:00",
    to: "2026-11-04T14:04:00.000+09:00",
    users: ["a"],
    event: ["login"],
    outcome: ["fail"],
    session: 0,
    ip: "10.0.0.1",
    q: "calc",
  });
  expect(toLogQuery({ q: "   " }, NOW)).not.toHaveProperty("q");
});

it("parses the audit search with its own kinds, results and channel", () => {
  expect(parseAuditSearch({ kind: "auth", result: ["fail", "x"], channel: "external", users: ["a@x.com"], q: "login", range: "today" }))
    .toEqual({ kind: "auth", result: ["fail"], channel: "external", users: ["a@x.com"], q: "login", range: "today" });
  expect(parseAuditSearch({ kind: "logs", channel: "lan", cat: ["auth"], session: 2 })).toEqual({});
});
