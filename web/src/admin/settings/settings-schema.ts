// Client copy of the server's Settings rules (server/app/settings/store.py, U27): the server's 422
// names no field, so this schema is what points the user at the field to fix. Same ranges, and the
// same model check that compression cannot start after the logs are deleted.
import { z } from "zod";
import { copy } from "@/copy/ko";
import type { Settings } from "@/lib/api-types";
import { int } from "../mcps/mcp-schema";

/** Everything the page edits; `otp_provider` is fixed ("dummy") and never sent. */
export type SettingsValues = Omit<Settings, "otp_provider">;

/** Number ranges by field, for the hint under each input (same numbers as the schema). */
export const SETTINGS_RANGES = {
  ping_interval_sec: [1, 300],
  issue_check_interval_sec: [5, 60],
  confirm_interval_sec: [1, 10],
  log_retention_days: [7, 3650],
  // the server only says ≥ 1; ≤ retention ≤ 3650 bounds it from above
  log_compress_after_days: [1, 3650],
} as const satisfies Partial<Record<keyof SettingsValues, readonly [number, number]>>;

export const START_TYPES = ["auto", "delayed-auto", "manual"] as const;

const r = SETTINGS_RANGES;
const schema = z
  .object({
    ping_interval_sec: int(...r.ping_interval_sec),
    issue_check_interval_sec: int(...r.issue_check_interval_sec),
    confirm_interval_sec: int(...r.confirm_interval_sec),
    log_retention_days: int(...r.log_retention_days),
    log_compress_after_days: int(...r.log_compress_after_days),
    service_start_type: z.enum(START_TYPES),
  })
  .superRefine((v, ctx) => {
    if (typeof v.log_retention_days !== "number" || typeof v.log_compress_after_days !== "number") return;
    if (v.log_compress_after_days <= v.log_retention_days) return;
    // both fields are wrong together: either one alone may be the one to fix
    for (const path of ["log_compress_after_days", "log_retention_days"] as const) {
      ctx.addIssue({ code: "custom", message: copy.settings.retentionBelowCompress, path: [path] });
    }
  });

/** What the form holds: number fields may be the raw text of their input. */
export type SettingsFormValues = z.input<typeof schema>;

export const settingsSchema: z.ZodType<SettingsValues, SettingsFormValues> = schema;

/** The retention pair travels together: the server checks one against the other. */
export const RETENTION_KEYS = ["log_retention_days", "log_compress_after_days"] as const;
