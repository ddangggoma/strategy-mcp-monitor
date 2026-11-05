import { copy } from "@/copy/ko";
import { NAME_PATTERN, dirtyPatch, mcpConfigSchema } from "./mcp-schema";

const base = { name: "calc", host: "127.0.0.1", port: 9102, path: "/mcp", probe: "mcp_ping", expected_process_name: null, action_delay_sec: 30,
  startup_grace_sec: 30, max_auto_actions: 3, window_sec: 600, auto_recovery: true, autostart_on_boot: false, maintenance: false, script_timeout_sec: 120 };

/** The first issue message for `key` when `value` is parsed. */
function messageFor(key: string, value: unknown): string | undefined {
  const r = mcpConfigSchema.safeParse({ ...base, [key]: value });
  return r.success ? undefined : r.error.issues.find((i) => i.path[0] === key)?.message;
}

it.each(["서울 날씨_v2.1-a", "calc", "Ａ１"])("accepts name %s", (name) => expect(mcpConfigSchema.safeParse({ ...base, name }).success).toBe(true));
it.each(["a&b", "a(b)", "a%b", "a\"b", "", " ".repeat(3), "x".repeat(65)])("rejects name %j", (name) => expect(mcpConfigSchema.safeParse({ ...base, name }).success).toBe(false));
it.each([["port", 0], ["port", 65536], ["path", "mcp"], ["path", "/a b"], ["script_timeout_sec", 121], ["window_sec", 59], ["startup_grace_sec", -1]])(
  "rejects %s=%j", (k, v) => expect(mcpConfigSchema.safeParse({ ...base, [k]: v }).success).toBe(false));
it("maps an empty expected process name to null", () => expect(mcpConfigSchema.parse({ ...base, expected_process_name: "" }).expected_process_name).toBeNull());
it("dirtyPatch keeps only dirty keys", () => expect(dirtyPatch({ a: 1, b: 2 }, { b: true })).toEqual({ b: 2 }));

it("accepts every boundary the server accepts", () => {
  const edges = {
    port: [1, 65535], action_delay_sec: [1, 3600], startup_grace_sec: [0, 600], max_auto_actions: [1, 20],
    window_sec: [60, 86400], script_timeout_sec: [10, 120],
  } as const;
  for (const [k, [lo, hi]] of Object.entries(edges)) {
    expect(mcpConfigSchema.safeParse({ ...base, [k]: lo }).success, `${k}=${lo}`).toBe(true);
    expect(mcpConfigSchema.safeParse({ ...base, [k]: hi }).success, `${k}=${hi}`).toBe(true);
    expect(mcpConfigSchema.safeParse({ ...base, [k]: lo - 1 }).success, `${k}=${lo - 1}`).toBe(false);
    expect(mcpConfigSchema.safeParse({ ...base, [k]: hi + 1 }).success, `${k}=${hi + 1}`).toBe(false);
  }
});

it("turns input strings into numbers but never an empty one (no z.coerce)", () => {
  expect(mcpConfigSchema.parse({ ...base, port: "9200", action_delay_sec: " 45 " })).toMatchObject({ port: 9200, action_delay_sec: 45 });
  expect(messageFor("port", "")).toBe(copy.mcp.rangeError(1, 65535));
  expect(messageFor("action_delay_sec", "  ")).toBe(copy.mcp.rangeError(1, 3600));
  expect(messageFor("max_auto_actions", "2.5")).toBe(copy.mcp.rangeError(1, 20));
  expect(messageFor("port", "12abc")).toBe(copy.mcp.rangeError(1, 65535));
  expect(messageFor("port", Number.NaN)).toBe(copy.mcp.rangeError(1, 65535));
});

it("trims the name, counts code points and says the rule", () => {
  expect(mcpConfigSchema.parse({ ...base, name: "  calc  " }).name).toBe("calc");
  expect(mcpConfigSchema.safeParse({ ...base, name: "가".repeat(64) }).success).toBe(true);
  expect(mcpConfigSchema.safeParse({ ...base, name: "𝟙".repeat(64) }).success).toBe(true); // 2 UTF-16 units each
  expect(messageFor("name", "a&b")).toBe(copy.mcp.nameRule);
  expect(messageFor("name", "  ")).toBe(copy.mcp.nameRequired);
  expect(NAME_PATTERN.test("a\tb")).toBe(false);
});

it("normalizes the host and rejects what can never be a host", () => {
  expect(mcpConfigSchema.parse({ ...base, host: "  Example.COM " }).host).toBe("example.com");
  for (const bad of ["", "   ", "-x.example.com", "x".repeat(254)]) expect(messageFor("host", bad), bad).toBe(copy.mcp.hostRule);
  expect(mcpConfigSchema.safeParse({ ...base, host: "x".repeat(253) }).success).toBe(true);
});

it("limits the path to 200 characters", () => {
  expect(mcpConfigSchema.safeParse({ ...base, path: "/" + "a".repeat(199) }).success).toBe(true);
  expect(messageFor("path", "/" + "a".repeat(200))).toBe(copy.mcp.pathRule);
  expect(mcpConfigSchema.safeParse({ ...base, path: "/" }).success).toBe(true);
});

it("checks the expected process name like the server", () => {
  expect(mcpConfigSchema.parse({ ...base, expected_process_name: "python.exe" }).expected_process_name).toBe("python.exe");
  expect(mcpConfigSchema.parse({ ...base, expected_process_name: null }).expected_process_name).toBeNull();
  expect(mcpConfigSchema.safeParse({ ...base, expected_process_name: "x".repeat(260) }).success).toBe(true);
  for (const bad of ["x".repeat(261), "a\u0007b", "a\u009fb", "a\nb"]) expect(messageFor("expected_process_name", bad), bad).toBe(copy.mcp.processNameRule);
});

it("rejects an unknown probe and non-boolean switches", () => {
  expect(mcpConfigSchema.safeParse({ ...base, probe: "http" }).success).toBe(false);
  for (const probe of ["mcp_ping", "tcp", "icmp"]) expect(mcpConfigSchema.safeParse({ ...base, probe }).success).toBe(true);
  expect(mcpConfigSchema.safeParse({ ...base, maintenance: "true" }).success).toBe(false);
});

it("dirtyPatch ignores keys marked clean and keys without a value", () => {
  expect(dirtyPatch({ a: 1, b: 2, c: 3 }, { a: false, c: true })).toEqual({ c: 3 });
  expect(dirtyPatch({ a: 1 }, {})).toEqual({});
});
