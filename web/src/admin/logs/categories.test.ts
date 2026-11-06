import { CATEGORY_GROUP, GROUP_COLOR_VAR, LOG_CATEGORIES, LOG_GROUPS } from "./categories";

it("lists the 12 categories in the server's order", () => {
  expect(LOG_CATEGORIES).toEqual([
    "session", "notice", "activity.process", "activity.command", "activity.window", "activity.idle",
    "tamper", "mcp.health", "mcp.action", "auth", "admin.audit", "system",
  ]);
});

it("puts every category in one of five colour groups", () => {
  expect(CATEGORY_GROUP).toEqual({
    session: "session",
    notice: "session",
    "activity.process": "activity",
    "activity.command": "activity",
    "activity.window": "activity",
    "activity.idle": "activity",
    tamper: "security",
    "mcp.health": "mcp",
    "mcp.action": "mcp",
    auth: "security",
    "admin.audit": "security",
    system: "system",
  });
  expect(LOG_GROUPS).toEqual(["session", "activity", "mcp", "security", "system"]);
  for (const g of LOG_GROUPS) expect(GROUP_COLOR_VAR[g]).toBe(`var(--color-cat-${g})`);
});
