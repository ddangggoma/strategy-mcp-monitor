// Contextual help tips (InfoTip): an open tip passes axe, opens on hover, focus and click, and at
// the smallest supported window (640 x 600, W41) stays inside the window without a sideways scroll.
import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page } from "@playwright/test";
import { copy, expect, tabTo, test } from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const tipButton = (page: Page, label: string) => page.getByRole("button", { name: copy.help.label(label) }).first();

async function axeViolations(page: Page): Promise<string[]> {
  const r = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  return r.violations.map((v) => `${v.id}: ${v.nodes.length} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`);
}

async function loaded(page: Page): Promise<void> {
  await expect(page.locator("[role='status'] .sr-only", { hasText: copy.common.loading })).toHaveCount(0);
  await expect(page.locator("h1").first()).toBeVisible();
}

/** The open tip's box lies inside the viewport and the page does not scroll sideways. */
async function expectInsideWindow(page: Page, tip: Locator): Promise<void> {
  const box = await tip.boundingBox();
  const vp = page.viewportSize();
  if (!box || !vp) throw new Error("no tip box or viewport");
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(vp.width);
  expect(box.y + box.height).toBeLessThanOrEqual(vp.height);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
}

test("axe: the MCP settings with a field tip open, and the board with the state legend open", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/mcps/${state.mcpId}?tab=settings`);
  await loaded(page);
  await tipButton(page, copy.mcp.fields.action_delay_sec).click();
  await expect(page.getByRole("tooltip")).toContainText(copy.help.mcp.fields.action_delay_sec);
  expect(await axeViolations(page)).toEqual([]);

  await page.goto(`${state.localUrl}/`);
  await loaded(page);
  await tipButton(page, copy.help.stateLabel).click();
  await expect(page.getByRole("tooltip")).toContainText(copy.help.states.HEALTHY);
  expect(await axeViolations(page)).toEqual([]);
});

test("a tip opens on hover, on keyboard focus and on click, and Escape closes it", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/settings`);
  await loaded(page);
  const button = tipButton(page, copy.settings.fields.ping_interval_sec);
  const tip = page.getByRole("tooltip");

  await button.hover();
  await expect(tip).toContainText(copy.help.settings.ping_interval_sec);
  await page.mouse.move(0, 0);
  await expect(tip).toHaveCount(0);

  await tabTo(page, button);
  await expect(tip).toBeVisible();
  await expect(button).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(tip).toHaveCount(0);
  await expect(button).toBeFocused();

  await page.mouse.move(0, 0);
  await button.click();
  await expect(tip).toBeVisible();
  await page.mouse.move(0, 0); // a click pins it: moving away does not close it
  await page.waitForTimeout(400);
  await expect(tip).toBeVisible();
  await page.locator("main h1").click();
  await expect(tip).toHaveCount(0);
});

test("at 640 x 600 an open tip stays inside the window and adds no sideways scroll", async ({ page, state, loginAs }) => {
  await page.setViewportSize({ width: 640, height: 600 });
  await loginAs(page, "admin", "local");

  // the actions tip sits at the right edge of the detail header; the longest tip (probe kinds) mid-form
  await page.goto(`${state.localUrl}/admin/mcps/${state.mcpId}?tab=settings`);
  await loaded(page);
  for (const label of [copy.mcp.columns.actions, copy.mcp.fields.probe, copy.mcp.fields.auto_recovery]) {
    const button = tipButton(page, label);
    await button.scrollIntoViewIfNeeded();
    await button.click();
    const tip = page.getByRole("tooltip");
    await expect(tip).toBeVisible();
    await expectInsideWindow(page, tip);
    await page.keyboard.press("Escape");
    await expect(tip).toHaveCount(0);
  }

  // a header tip in the MCP table, next to the sticky actions column at the right edge
  await page.goto(`${state.localUrl}/admin/mcps`);
  await loaded(page);
  await tipButton(page, copy.mcp.columns.actions).click();
  await expectInsideWindow(page, page.getByRole("tooltip"));

  // the state legend on the board: the tallest tip
  await page.goto(`${state.localUrl}/`);
  await loaded(page);
  await tipButton(page, copy.help.stateLabel).click();
  await expectInsideWindow(page, page.getByRole("tooltip"));
});
