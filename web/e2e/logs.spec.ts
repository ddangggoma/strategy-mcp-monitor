// Log search against the real backend and its log index (Plan 5 Tasks 3–5, 10–11). The index
// trails the writer by about a second, so every row assertion waits for it (no widened timeouts
// beyond that). The table is virtual: only rows near the viewport exist, so a test that looks for
// an old line narrows the filter first (F15) instead of hoping the line is rendered.
import { readFile } from "node:fs/promises";
import { MCP_NAME, copy, expect, test } from "./fixtures";

test("finds the bootstrap audit line by category on the external channel", async ({ page, state, loginAs }) => {
  await loginAs(page, "dev", "external");
  await page.goto(`${state.externalUrl}/admin/logs?range=today&q=bootstrap`);
  await page.getByRole("button", { name: copy.logs.cats["admin.audit"] }).click();
  await expect(page.getByRole("button", { name: copy.logs.cats["admin.audit"] })).toHaveAttribute("aria-pressed", "true");
  await expect(page).toHaveURL(/cat=/);
  const table = page.getByRole("table", { name: copy.logs.title });
  await expect(table.getByRole("row").filter({ hasText: "bootstrap" }).first()).toBeVisible({ timeout: 10_000 });
});

test("keyword search narrows rows", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/logs?range=today`);
  await page.getByLabel(copy.logs.keyword, { exact: true }).fill(MCP_NAME);
  await expect(page).toHaveURL(/q=/);
  const table = page.getByRole("table", { name: copy.logs.title });
  const rows = table.getByRole("row").filter({ hasText: MCP_NAME });
  await expect(rows.first()).toBeVisible({ timeout: 10_000 });
  // narrowed: every rendered data row mentions the keyword (the header row is a row too)
  const all = table.locator("tbody tr[data-index]");
  await expect.poll(async () => (await all.allInnerTexts()).every((t) => t.includes(MCP_NAME)), { timeout: 10_000 }).toBe(true);
});

test("dragging the histogram sets a custom range in the URL", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/logs?range=1h`);
  const histogram = page.getByTestId("log-histogram");
  await expect(histogram).toBeVisible({ timeout: 10_000 });
  const box = (await histogram.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.6, box.y + box.height / 2, { steps: 5 });
  await page.mouse.up();
  await expect(page).toHaveURL(/from=/);
  await expect(page).not.toHaveURL(/range=/);
});

test("keyboard-only histogram selection", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/logs?range=1h`);
  const histogram = page.getByTestId("log-histogram");
  await expect(histogram).toBeVisible({ timeout: 10_000 });
  await histogram.focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Shift+ArrowRight");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/from=/);
  await expect(page).not.toHaveURL(/range=/);
});

test("export CSV downloads a file with the header", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/logs?range=today`);
  await page.getByRole("button", { name: copy.logs.export.menu }).click();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("menuitem", { name: copy.logs.export.csv }).click(),
  ]);
  const text = await readFile((await download.path())!, "utf-8");
  expect(text.startsWith("﻿ts,cat,event,user,session_id,client_ip,client_name,outcome,summary")).toBe(true);
});

test("anonymous visitors are sent to login", async ({ page, state }) => {
  await page.goto(`${state.externalUrl}/admin/logs`);
  await expect(page).toHaveURL(/\/admin\/login\?redirect=/);
});
