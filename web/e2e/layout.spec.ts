// User ruling (2026-11-05): no phone layouts, but the browser window can be small. Every screen
// stays usable from 1920 down to 640 x 600: no horizontal page scroll (tables scroll in their own
// container), and the admin sidebar folds to an icon rail below 1024 px.
import { MCP_NAME, copy, expect, test } from "./fixtures";
import { clearSessions, rdp, setSessions } from "./sessions";

const WIDTHS = [1920, 1280, 1024, 800, 640] as const;
const ADMIN_PAGES = [
  "/admin",
  "/admin/mcps",
  "/admin/mcps/{id}?tab=settings",
  "/admin/mcps/{id}?tab=history",
  "/admin/mcps/{id}?tab=scripts",
  "/admin/mcps/new",
  "/admin/sessions",
  "/admin/users",
  "/admin/settings",
  "/admin/notice",
  // Plan 5 (W41, F12): the log and audit screens join the same sweep instead of a second spec
  "/admin/logs?range=today",
  "/admin/logs?range=today&view=timeline",
  "/admin/audit?range=today",
];

// C4 / F11: the session screens are measured with content: a connected session with long values
// (a card on the board, the dashboard and the sessions page) and a disconnected one (the sessions
// page's status line). Neither is this PC's own session, so no agent starts.
const CARD_USER = "hong.gildong-contractor-account";
const SEEDED = [
  rdp({
    session_id: 42, user: CARD_USER, domain: "CORPORATE-DOMAIN", client_name: "HONG-LAPTOP-WORKSTATION-01",
    client_ip: "10.0.3.21", resolution: "1920x1080@32", idle_sec: 3725,
  }),
  rdp({ session_id: 43, user: "kim", client_ip: "10.0.3.22", state: "disconnected", disconnected_at: new Date().toISOString() }),
];
/** Pages that must show the seeded session before they are measured. */
const WITH_CARD = new Set(["/", "/admin", "/admin/sessions"]);

test.beforeEach(async ({ state }) => { await setSessions(state, SEEDED); });
test.afterEach(async ({ state }) => { await clearSessions(state); });

for (const width of WIDTHS) {
  test(`no horizontal page scroll at ${width} px`, async ({ page, state, loginAs }) => {
    await page.setViewportSize({ width, height: width === 640 ? 600 : 900 });
    const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    const card = page.getByRole("article", { name: CARD_USER });

    for (const path of ["/", "/admin/login"]) {
      await page.goto(`${state.localUrl}${path}`);
      await expect(page.locator("h1").first()).toBeVisible();
      if (WITH_CARD.has(path)) await expect(card).toBeVisible();
      expect(await overflow(), path).toBeLessThanOrEqual(0);
    }

    // the notice window is a 640 x 600 Edge app window; the page must fit it (and anything wider)
    await page.goto(`${state.localUrl}/notice`);
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(await overflow(), "/notice").toBeLessThanOrEqual(0);

    await loginAs(page, "admin", "local");
    const nav = page.getByRole("navigation", { name: copy.nav.label });
    // the labels are visible text in the full sidebar, screen-reader text in the rail
    if (width < 1024) await expect(nav).toHaveAttribute("data-rail", "");
    else await expect(nav).not.toHaveAttribute("data-rail");
    for (const path of ADMIN_PAGES) {
      await page.goto(`${state.localUrl}${path.replace("{id}", String(state.mcpId))}`);
      await expect(page.locator("main h1").first()).toBeVisible();
      await expect(page.locator("[role='status'] .sr-only", { hasText: copy.common.loading })).toHaveCount(0);
      if (WITH_CARD.has(path)) await expect(card).toBeVisible();
      if (path === "/admin/sessions") await expect(page.getByTestId("session-line").filter({ hasText: "kim" })).toBeVisible();
      expect(await overflow(), path).toBeLessThanOrEqual(0);
    }

    // the MCP table keeps its row actions reachable inside its own scroll container
    await page.goto(`${state.localUrl}/admin/mcps`);
    const start = page.getByRole("table", { name: copy.mcp.listLabel }).getByRole("row", { name: new RegExp(MCP_NAME) }).getByRole("button", { name: copy.mcp.start, exact: true });
    await start.scrollIntoViewIfNeeded();
    await expect(start).toBeInViewport();
  });
}

// W41: at 640 x 600 the log table is wider than the window; it scrolls inside its own frame, and a
// row opened from the keyboard shows a detail dialog whose close button is on screen.
test("the log table scrolls inside its own container at 640", async ({ page, state, loginAs }) => {
  await page.setViewportSize({ width: 640, height: 600 });
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/logs?range=today`);
  const table = page.getByRole("table", { name: copy.logs.title });
  await expect(table).toBeVisible({ timeout: 10_000 });
  const scroller = table.locator("xpath=ancestor::*[@data-scroll-container][1]");
  await expect(scroller).toBeVisible();
  expect(await scroller.evaluate((el) => getComputedStyle(el).overflowX)).toMatch(/auto|scroll/);
  expect(await scroller.evaluate((el) => el.scrollWidth > el.clientWidth), "the table is wider than its frame").toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);

  await table.getByRole("row").nth(1).focus();
  await page.keyboard.press("Enter");
  const detail = page.getByRole("dialog", { name: copy.logs.detail });
  // two ways out (the corner X and the footer button): both on screen
  const closers = detail.getByRole("button", { name: copy.common.close });
  await expect(closers).toHaveCount(2);
  for (const closer of await closers.all()) await expect(closer).toBeInViewport();
  await page.keyboard.press("Escape");
  await expect(detail).toHaveCount(0);
});

// WCAG 1.4.10 Reflow: 200% zoom of a 1280 px window is the 640 px case above; 400% is 320 CSS px.
// No phone layout is built for it (user ruling), but nothing may need a sideways page scroll.
test("reflows at 400% zoom (320 CSS px) without horizontal page scroll", async ({ page, state, loginAs }) => {
  await page.setViewportSize({ width: 320, height: 256 });
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  for (const path of ["/", "/admin/login"]) {
    await page.goto(`${state.localUrl}${path}`);
    await expect(page.locator("h1").first()).toBeAttached();
    expect(await overflow(), path).toBeLessThanOrEqual(0);
  }
  await loginAs(page, "admin", "local");
  for (const path of [...ADMIN_PAGES, "/notice"]) {
    await page.goto(`${state.localUrl}${path.replace("{id}", String(state.mcpId))}`);
    await expect(page.locator("h1, [role='dialog'] h2").first()).toBeAttached();
    await expect(page.locator("[role='status'] .sr-only", { hasText: copy.common.loading })).toHaveCount(0);
    expect(await overflow(), path).toBeLessThanOrEqual(0);
  }
});
