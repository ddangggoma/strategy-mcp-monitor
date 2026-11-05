import { MCP_NAME, adminApi, copy, expect, test } from "./fixtures";

test("anonymous board updates live over SSE without a reload", async ({ page, state, request }) => {
  await page.goto(`${state.externalUrl}/`);
  const card = page.getByTestId("mcp-card").filter({ hasText: MCP_NAME });
  await expect(card.getByText(copy.states.HEALTHY)).toBeVisible();
  await expect(page.getByText(copy.board.sessionsNotReady)).toBeVisible();
  // the anonymous board never shows where an MCP runs (F09: the exact host:port, not any digits)
  await expect(page.locator("body")).not.toContainText(`127.0.0.1:${state.mcpPort}`);
  await expect(page.locator("body")).not.toContainText(`:${state.mcpPort}`);

  // F09: count navigations for the whole wait, and keep a marker that a reload would wipe
  let navigations = 0;
  page.on("framenavigated", (f) => {
    if (f === page.mainFrame()) navigations += 1;
  });
  await page.evaluate(() => ((window as unknown as { __e2eMarker: string }).__e2eMarker = "kept"));

  const api = await adminApi(request, state);
  expect((await api.post(`/api/mcps/${state.mcpId}/actions/stop`)).status()).toBe(202); // another client's action
  await expect(card.getByText(copy.states.MAINTENANCE)).toBeVisible({ timeout: 15_000 });
  // the state turns MAINTENANCE as soon as the stop is accepted; start is refused (409) until the
  // stop script has finished
  await expect
    .poll(async () => (await api.post(`/api/mcps/${state.mcpId}/actions/start`)).status(), { timeout: 30_000 })
    .toBe(202);
  await expect(card.getByText(copy.states.HEALTHY)).toBeVisible({ timeout: 30_000 });

  expect(navigations).toBe(0);
  expect(await page.evaluate(() => (window as unknown as { __e2eMarker?: string }).__e2eMarker)).toBe("kept");
});
