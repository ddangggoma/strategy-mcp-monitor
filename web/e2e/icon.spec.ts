import { MCP_NAME, adminApi, copy, expect, test } from "./fixtures";

// The per-MCP icon (one emoji): picked in the MCP settings, shown on the anonymous board live.
test("an emoji set in the MCP settings shows on the board; clearing it brings back the default icon", async ({ page, state, loginAs, request, browser }) => {
  const api = await adminApi(request, state);
  try {
    const board = await browser.newPage();
    await board.goto(`${state.externalUrl}/`);
    const card = board.getByTestId("mcp-card").filter({ hasText: MCP_NAME });
    await expect(card.getByTestId("mcp-icon")).toHaveAttribute("data-icon", "default");

    await loginAs(page, "admin", "local");
    await page.goto(`${state.localUrl}/admin/mcps/${state.mcpId}`);
    const icons = page.getByRole("radiogroup", { name: copy.mcp.icon.choiceLabel });
    await icons.getByRole("radio", { name: copy.mcp.icon.names["🧮"] }).click();
    await expect(page.getByTestId("mcp-icon-preview").getByTestId("mcp-icon")).toHaveAttribute("data-icon", "🧮");
    await page.getByRole("button", { name: copy.common.save, exact: true }).click();
    await expect(page.getByText(copy.common.saved)).toBeVisible();
    // the detail header shows it too
    await expect(page.getByRole("main").getByTestId("mcp-icon").first()).toHaveAttribute("data-icon", "🧮");

    // the anonymous board picks it up over SSE, without a reload
    await expect(card.getByTestId("mcp-icon")).toHaveAttribute("data-icon", "🧮", { timeout: 15_000 });
    await expect(card.getByTestId("mcp-icon")).toHaveText("🧮");

    // a pasted emoji outside the list
    await page.getByLabel(copy.mcp.icon.pasteLabel).fill("🦄");
    await page.getByRole("button", { name: copy.common.save, exact: true }).click();
    await expect(card.getByTestId("mcp-icon")).toHaveAttribute("data-icon", "🦄", { timeout: 15_000 });

    await icons.getByRole("radio", { name: copy.mcp.icon.defaultIcon }).click();
    await page.getByRole("button", { name: copy.common.save, exact: true }).click();
    await expect(card.getByTestId("mcp-icon")).toHaveAttribute("data-icon", "default", { timeout: 15_000 });
    await board.close();
  } finally {
    // later specs (visual baselines) expect the seeded MCP without an icon
    await api.put(`/api/mcps/${state.mcpId}`, { icon: null });
  }
});
