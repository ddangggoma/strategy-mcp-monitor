// Client copy of the server's McpConfig rules (server/app/monitor/models.py, U27): the server's 422
// names no field, so this schema is what points the user at the field to fix. The server stays
// final (host syntax especially). Lengths count code points like Python's len().
import { z } from "zod";
import { copy } from "@/copy/ko";
import type { McpConfig } from "@/lib/api-types";

/** Letters, digits (any script), space, "." "_" "-": the name reaches cmd as %MCP_NAME% (server allowlist). */
export const NAME_PATTERN = /^[\p{L}\p{N} ._-]+$/u;
const PATH_PATTERN = /^\/\S*$/;
// C0 controls, DEL and C1 controls (server _CONTROL_RE)
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u001f\u007f-\u009f]/;
const INTEGER_TEXT = /^[+-]?\d+$/;

const codePoints = (s: string) => [...s].length;

/**
 * An integer in [min, max] from a number or the text of an input. No z.coerce: it reads "" as 0,
 * and an empty field must be an error, not a zero.
 */
function int(min: number, max: number) {
  const message = copy.mcp.rangeError(min, max);
  // NaN (an emptied number input read as a number) fails z.number(): same message
  return z.union([z.number(), z.string()], { error: message }).transform((v, ctx) => {
    const text = typeof v === "string" ? v.trim() : null;
    const n = text === null ? v : INTEGER_TEXT.test(text) ? Number(text) : Number.NaN;
    if (typeof n !== "number" || !Number.isInteger(n) || n < min || n > max) {
      ctx.addIssue({ code: "custom", message });
      return z.NEVER;
    }
    return n;
  });
}

const name = z.string().transform((v, ctx) => {
  const s = v.trim();
  if (s === "") ctx.addIssue({ code: "custom", message: copy.mcp.nameRequired });
  else if (codePoints(s) > 64 || !NAME_PATTERN.test(s)) ctx.addIssue({ code: "custom", message: copy.mcp.nameRule });
  return s;
});

const host = z.string().transform((v, ctx) => {
  const s = v.trim().toLowerCase();
  if (s === "" || s.length > 253 || s.startsWith("-")) ctx.addIssue({ code: "custom", message: copy.mcp.hostRule });
  return s;
});

const path = z.string().refine((s) => s.length <= 200 && PATH_PATTERN.test(s), { message: copy.mcp.pathRule });

const processName = z
  .string()
  .nullable()
  .transform((v, ctx) => {
    if (v === null || v === "") return null;
    if (codePoints(v) > 260 || CONTROL.test(v)) ctx.addIssue({ code: "custom", message: copy.mcp.processNameRule });
    return v;
  });

const schema = z.object({
  name,
  host,
  port: int(1, 65535),
  path,
  probe: z.enum(["mcp_ping", "tcp", "icmp"]),
  expected_process_name: processName,
  action_delay_sec: int(1, 3600),
  startup_grace_sec: int(0, 600),
  max_auto_actions: int(1, 20),
  window_sec: int(60, 86400),
  auto_recovery: z.boolean(),
  autostart_on_boot: z.boolean(),
  maintenance: z.boolean(),
  script_timeout_sec: int(10, 120),
});

/** What the form holds: number fields may be the raw text of their input. */
export type McpFormValues = z.input<typeof schema>;

export const mcpConfigSchema: z.ZodType<McpConfig, McpFormValues> = schema;

/** Number ranges by field, for the hint under each input (same numbers as the schema). */
export const RANGES = {
  port: [1, 65535],
  action_delay_sec: [1, 3600],
  startup_grace_sec: [0, 600],
  max_auto_actions: [1, 20],
  window_sec: [60, 86400],
  script_timeout_sec: [10, 120],
} as const satisfies Partial<Record<keyof McpConfig, readonly [number, number]>>;

/** Only the keys react-hook-form marks dirty (U27: a PUT carries just the changed fields). */
export function dirtyPatch<T extends object>(values: T, dirty: Partial<Record<keyof T, unknown>>): Partial<T> {
  const out: Partial<T> = {};
  for (const key of Object.keys(dirty) as (keyof T)[]) {
    if (dirty[key] && key in values) out[key] = values[key];
  }
  return out;
}
