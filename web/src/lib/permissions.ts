// Client mirror of the server policy (app/auth/policy.py), used to show controls as disabled with a
// reason instead of hiding them (spec §4.4). The server stays final. policy-rules.json is checked
// against the server's RULES by server/tests/test_web_policy_mirror.py (U23).
import type { DisabledReason } from "@/copy/ko";
import type { Me, Role } from "./api-types";
import policyRules from "./policy-rules.json";

export const ACTIONS = [
  "view_board", "view_mcp_history", "view_session_history", "view_logs", "export_logs", "view_audit",
  "edit_mcp_settings", "mcp_manual_action", "create_mcp", "delete_mcp", "view_scripts", "edit_scripts",
  "transfer_ownership", "manage_users", "edit_global_settings", "edit_retention", "edit_notice",
] as const;
export type Action = (typeof ACTIONS)[number];

export type DenyReason = Extract<DisabledReason, "login" | "local_only" | "admin_only" | "owner_only" | "no_owner">;
export type { DisabledReason };

interface Rule {
  min_role: Role | null;
  local_only: boolean;
  /** none: owner irrelevant; always: only the owner (admins too); developer_only: admins exempt. */
  owner: "none" | "always" | "developer_only";
}

const RULES = policyRules as Record<Action, Rule>;
const RANK: Record<Role, number> = { developer: 1, admin: 2 };

/** Why `me` may not do `action` (null = allowed). Same decision order as the server's can(). */
export function denyReason(me: Me | null, action: Action, ownerId?: number | null): DenyReason | null {
  const rule = RULES[action];
  const user = me?.user ?? null;
  if (rule.min_role !== null && user === null) return "login";
  if (rule.local_only && me?.channel !== "local") return "local_only";
  if (rule.min_role !== null && user !== null && RANK[user.role] < RANK[rule.min_role]) return "admin_only";
  const ownerRequired = rule.owner === "always" || (rule.owner === "developer_only" && user?.role !== "admin");
  if (ownerRequired) {
    if (ownerId == null) return "no_owner";
    if (user === null || ownerId !== user.id) return "owner_only";
  }
  return null;
}

export function can(me: Me | null, action: Action, ownerId?: number | null): boolean {
  return denyReason(me, action, ownerId) === null;
}
