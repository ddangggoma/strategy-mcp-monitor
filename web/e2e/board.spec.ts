import { MCP_NAME, adminApi, copy, expect, test } from "./fixtures";

test("anonymous board updates live over SSE without a reload", async ({ page, state, request }) => {
  await page.goto(`${state.externalUrl}/`);
  const card = page.getByTestId("mcp-card").filter({ hasText: MCP_NAME });
  await expect(card.getByText(copy.states.HEALTHY)).toBeVisible();
  await expect(page.getByText(copy.board.noSession)).toBeVisible();
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

// The app window opens the Local board (`/`): the admin screen is one click away, and back.
test("the Local board leads to the admin screen in one click, and the admin back to the board", async ({ page, state, loginAs }) => {
  await page.goto(`${state.localUrl}/`);
  const banner = page.getByRole("banner");
  // signed out: through the login page, which then opens the admin screen
  await banner.getByRole("link", { name: copy.common.adminHome }).click();
  await expect(page).toHaveURL(/\/admin\/login\?redirect=(%2F|\/)admin$/);
  await expect(page.getByLabel(copy.login.email)).toBeVisible();

  await loginAs(page, "admin", "local"); // lands on /admin
  await page.getByRole("banner").getByRole("link", { name: copy.common.boardHome }).click();
  await expect(page).toHaveURL(`${state.localUrl}/`);
  await expect(page.getByTestId("mcp-card").filter({ hasText: MCP_NAME })).toBeVisible();
  await page.getByRole("banner").getByRole("link", { name: copy.common.adminHome }).click();
  await expect(page).toHaveURL(`${state.localUrl}/admin`);
  await expect(page.getByRole("navigation", { name: copy.nav.label })).toBeVisible();
});

test("the External board keeps only its login link", async ({ page, state }) => {
  await page.goto(`${state.externalUrl}/`);
  const banner = page.getByRole("banner");
  await expect(banner.getByRole("link", { name: copy.common.login })).toBeVisible();
  await expect(banner.getByRole("link", { name: copy.common.adminHome })).toHaveCount(0);
});
