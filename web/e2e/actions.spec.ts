import { MCP_NAME, copy, expect, test } from "./fixtures";

test("manual restart shows a pending toast and then the result from the action event", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "external");
  await page.goto(`${state.externalUrl}/admin/mcps`);
  await page
    .getByRole("table", { name: copy.mcp.listLabel })
    .getByRole("row", { name: new RegExp(MCP_NAME) })
    .getByRole("button", { name: copy.mcp.restart, exact: true })
    .click();
  await expect(page.getByText(copy.toasts.pending(MCP_NAME, "restart"))).toBeVisible();
  await expect(page.getByText(copy.toasts.ok(MCP_NAME, "restart"))).toBeVisible({ timeout: 60_000 });

  await page.goto(`${state.externalUrl}/admin/mcps/${state.mcpId}?tab=history`);
  const row = page
    .getByRole("table", { name: copy.mcp.actionsTitle })
    .getByRole("row")
    .filter({ hasText: copy.mcp.restart })
    .filter({ hasText: copy.mcp.triggers.manual })
    .first();
  await expect(row).toBeVisible();
  await expect(row).toContainText(copy.mcp.scriptStatus.ok);
});
