// User ruling (2026-11-05): no phone layouts, but the browser window can be small. Every screen
// stays usable from 1920 down to 640 x 600: no horizontal page scroll (tables scroll in their own
// container), and the admin sidebar folds to an icon rail below 1024 px.
import { MCP_NAME, copy, expect, test } from "./fixtures";

const WIDTHS = [1920, 1280, 1024, 800, 640] as const;
const ADMIN_PAGES = [
  "/admin",
  "/admin/mcps",
  "/admin/mcps/{id}?tab=settings",
  "/admin/mcps/{id}?tab=history",
  "/admin/mcps/{id}?tab=scripts",
  "/admin/mcps/new",
  "/admin/users",
  "/admin/settings",
  "/admin/notice",
];

for (const width of WIDTHS) {
  test(`no horizontal page scroll at ${width} px`, async ({ page, state, loginAs }) => {
    await page.setViewportSize({ width, height: width === 640 ? 600 : 900 });
    const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

    for (const path of ["/", "/admin/login"]) {
      await page.goto(`${state.localUrl}${path}`);
      await expect(page.locator("h1").first()).toBeVisible();
      expect(await overflow(), path).toBeLessThanOrEqual(0);
    }

    await loginAs(page, "admin", "local");
    const nav = page.getByRole("navigation", { name: copy.nav.label });
    // the labels are visible text in the full sidebar, screen-reader text in the rail
    if (width < 1024) await expect(nav).toHaveAttribute("data-rail", "");
    else await expect(nav).not.toHaveAttribute("data-rail");
    for (const path of ADMIN_PAGES) {
      await page.goto(`${state.localUrl}${path.replace("{id}", String(state.mcpId))}`);
      await expect(page.locator("main h1").first()).toBeVisible();
      await expect(page.locator("[role='status'] .sr-only", { hasText: copy.common.loading })).toHaveCount(0);
      expect(await overflow(), path).toBeLessThanOrEqual(0);
    }

    // the MCP table keeps its row actions reachable inside its own scroll container
    await page.goto(`${state.localUrl}/admin/mcps`);
    const start = page.getByRole("table", { name: copy.mcp.listLabel }).getByRole("row", { name: new RegExp(MCP_NAME) }).getByRole("button", { name: copy.mcp.start, exact: true });
    await start.scrollIntoViewIfNeeded();
    await expect(start).toBeInViewport();
  });
}
