import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page } from "@playwright/test";
import { DEV_OTP_CODE, MCP_NAME, UI_USERS, copy, expect, test } from "./fixtures";

const PAGES = [
  "/",
  "/admin/login",
  "/admin",
  "/admin/mcps",
  "/admin/mcps/{id}?tab=settings",
  "/admin/mcps/{id}?tab=history",
  "/admin/mcps/{id}?tab=scripts",
  "/admin/users",
  "/admin/settings",
  "/admin/notice",
  "/notice",
];

for (const path of PAGES) {
  test(`axe ${path}`, async ({ page, state, loginAs }) => {
    if (path !== "/" && path !== "/admin/login") await loginAs(page, "admin", "local");
    await page.goto(`${state.localUrl}${path.replace("{id}", String(state.mcpId))}`);
    // analyse the loaded page, not its skeleton
    await expect(page.locator("[role='status'] .sr-only", { hasText: copy.common.loading })).toHaveCount(0);
    await expect(page.locator("h1, [role='dialog'] h2").first()).toBeVisible();
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    expect(r.violations.map((v) => `${v.id}: ${v.nodes.length} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`)).toEqual([]);
  });
}

/** Presses Tab until `target` has focus (never clicks). */
async function tabTo(page: Page, target: Locator, max = 60): Promise<void> {
  for (let i = 0; i < max; i += 1) {
    if (await target.evaluate((el) => el === document.activeElement).catch(() => false)) return;
    await page.keyboard.press("Tab");
  }
  throw new Error(`could not reach ${String(target)} with Tab`);
}

test("keyboard-only: login and run an action", async ({ page, state }) => {
  await page.goto(`${state.localUrl}/admin/login`);
  await tabTo(page, page.getByLabel(copy.login.email));
  await page.keyboard.type(UI_USERS.keyboard.email);
  await page.keyboard.press("Enter");
  // the code cells take focus themselves
  await expect(page.getByRole("group", { name: copy.login.codeGroup }).locator("input").first()).toBeFocused();
  await page.keyboard.type(DEV_OTP_CODE);
  await expect(page).toHaveURL(`${state.localUrl}/admin`);

  const nav = page.getByRole("navigation", { name: copy.nav.label });
  await tabTo(page, nav.getByRole("link", { name: copy.nav.mcps }));
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(`${state.localUrl}/admin/mcps`);

  const start = page.getByRole("table", { name: copy.mcp.listLabel }).getByRole("row", { name: new RegExp(MCP_NAME) }).getByRole("button", { name: copy.mcp.start, exact: true });
  await tabTo(page, start);
  await page.keyboard.press("Enter");
  await expect(page.getByText(copy.toasts.ok(MCP_NAME, "start"))).toBeVisible({ timeout: 60_000 });
});
