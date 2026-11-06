import AxeBuilder from "@axe-core/playwright";
import { DEV_OTP_CODE, MCP_NAME, UI_USERS, copy, expect, tabTo, test } from "./fixtures";

const PAGES = [
  "/",
  "/admin/login",
  "/admin",
  "/admin/mcps",
  "/admin/mcps/{id}?tab=settings",
  "/admin/mcps/{id}?tab=history",
  "/admin/mcps/{id}?tab=scripts",
  "/admin/sessions",
  "/admin/users",
  "/admin/settings",
  "/admin/notice",
  "/admin/no-such-page",
  "/notice",
  // Plan 5: the log and audit screens
  "/admin/logs?range=today",
  "/admin/logs?range=today&view=timeline",
  "/admin/audit?range=today",
];

// the default 1280 x 800 window, and the smallest supported desktop window (W41): the 640 px
// layouts (icon rail, wrapped filters, sideways table scroll) get the same checks
const WINDOWS = [null, { width: 640, height: 600 }] as const;

for (const [size, path] of WINDOWS.flatMap((w) => PAGES.map((p) => [w, p] as const))) {
  test(`axe ${path}${size ? ` at ${size.width}x${size.height}` : ""}`, async ({ page, state, loginAs }) => {
    if (size) await page.setViewportSize(size);
    if (path !== "/" && path !== "/admin/login") await loginAs(page, "admin", "local");
    await page.goto(`${state.localUrl}${path.replace("{id}", String(state.mcpId))}`);
    // analyse the loaded page, not its skeleton
    await expect(page.locator("[role='status'] .sr-only", { hasText: copy.common.loading })).toHaveCount(0);
    await expect(page.locator("h1, [role='dialog'] h2").first()).toBeVisible();
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    expect(r.violations.map((v) => `${v.id}: ${v.nodes.length} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`)).toEqual([]);
  });
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

test("keyboard-only: command palette opens with Ctrl+K, skips blocked screens, and gives focus back to the page", async ({ page, state, loginAs }) => {
  // every screen is open to an admin since Plan 5 (no planned items left): a developer still has
  // a blocked one (user management is Admin only)
  await loginAs(page, "dev", "local");
  await page.goto(`${state.localUrl}/admin/mcps`);
  await expect(page.locator("main h1")).toBeVisible();
  // nothing focused (the case that used to drop focus on <body>)
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());

  const dialog = page.getByRole("dialog", { name: copy.common.commandTitle });
  await page.keyboard.press("Control+k");
  await expect(dialog).toBeVisible();
  await page.keyboard.type(copy.nav.users);
  const users = dialog.getByRole("option", { name: new RegExp(copy.nav.users) });
  await expect(users).toHaveAttribute("aria-disabled", "true");
  await expect(users).toContainText(copy.deny.admin_only); // the reason, readable (not dimmed text)
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(`${state.localUrl}/admin/mcps`); // a blocked screen does not open

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page.locator("main")).toBeFocused();

  await page.keyboard.press("Control+k");
  await expect(dialog).toBeVisible();
  await page.keyboard.type(copy.nav.sessions);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(`${state.localUrl}/admin/sessions`);
  await expect(dialog).toHaveCount(0);
  await expect(page.locator("main")).toBeFocused();
});

test("an unknown admin address keeps the shell and says how to get back", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/no-such-page`);
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { level: 1, name: copy.common.notFoundTitle })).toBeVisible();
  await expect(page.getByRole("navigation", { name: copy.nav.label })).toBeVisible();
  await main.getByRole("link", { name: copy.common.adminHome }).click();
  await expect(page).toHaveURL(`${state.localUrl}/admin`);
});
