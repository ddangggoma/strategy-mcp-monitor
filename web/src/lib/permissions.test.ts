import type { Me } from "./api-types";
import { ACTIONS, can, denyReason, type Action } from "./permissions";
import rules from "./policy-rules.json";

const dev = (id = 5): Me => ({ user: { id, email: "d@x", name: "d", role: "developer" }, channel: "local", csrf_token: "t", otp_provider: "dummy" });
const ext = (m: Me): Me => ({ ...m, channel: "external" });
const admin = (id = 1): Me => ({ ...dev(id), user: { id, email: "a", name: "a", role: "admin" } });
const anonLocal: Me = { user: null, channel: "local", csrf_token: null, otp_provider: "dummy" };

it.each([
  [null, "view_board", undefined, true, null],
  [null, "view_mcp_history", undefined, false, "login"],
  [ext(dev()), "view_scripts", undefined, false, "local_only"],
  [dev(), "view_scripts", undefined, true, null],
  [dev(5), "edit_scripts", 5, true, null],
  [dev(5), "edit_scripts", 6, false, "owner_only"],
  [dev(5), "edit_scripts", null, false, "no_owner"],
  [ext(dev(5)), "edit_scripts", 5, false, "local_only"],
  [dev(), "manage_users", undefined, false, "admin_only"],
  [admin(1), "edit_scripts", 2, false, "owner_only"],
  [admin(1), "delete_mcp", 2, true, null],
  [admin(1), "delete_mcp", null, true, null],
  // extra rows: priority order and the remaining rule shapes
  [anonLocal, "view_board", undefined, true, null],
  [ext(anonLocal), "manage_users", undefined, false, "login"], // login comes before local_only
  [ext(dev()), "manage_users", undefined, false, "local_only"], // local_only comes before admin_only
  [ext(dev()), "view_mcp_history", undefined, true, null],
  [ext(dev()), "mcp_manual_action", undefined, true, null],
  [dev(5), "delete_mcp", 5, true, null],
  [dev(5), "delete_mcp", 6, false, "owner_only"],
  [dev(5), "delete_mcp", undefined, false, "no_owner"],
  [dev(), "edit_mcp_settings", undefined, true, null],
  [dev(), "create_mcp", undefined, true, null],
  [ext(admin()), "create_mcp", undefined, false, "local_only"],
  [admin(), "manage_users", undefined, true, null],
  [admin(), "edit_notice", undefined, true, null],
  [ext(admin()), "edit_notice", undefined, false, "local_only"],
  [admin(1), "edit_scripts", 1, true, null],
  [dev(), "transfer_ownership", undefined, false, "admin_only"],
])("%#: can/denyReason", (me, action, owner, allowed, reason) => {
  expect(can(me, action as Action, owner)).toBe(allowed);
  expect(denyReason(me, action as Action, owner)).toBe(reason);
});

it("has a rule for every action", () => {
  expect(ACTIONS).toHaveLength(17);
  expect(Object.keys(rules).sort()).toEqual([...ACTIONS].sort());
  for (const r of Object.values(rules)) {
    expect([null, "developer", "admin"]).toContain(r.min_role);
    expect(typeof r.local_only).toBe("boolean");
    expect(["none", "always", "developer_only"]).toContain(r.owner);
  }
});
