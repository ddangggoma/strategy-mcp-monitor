// Lowering the log retention (spec §11 P6, W14): the confirm shows what the preview will delete,
// and the purge runs a few seconds after the save. backend.ts seeds two old log files before the
// server starts; both lie inside the default 180 days, so the server's own startup run (60 s after
// start, F05) keeps them and only this spec's 60 days removes the older one.
import { copy, expect, test, type BackendState } from "./fixtures";
import type { Page } from "@playwright/test";

async function oldestDay(page: Page, state: BackendState): Promise<string | null> {
  const res = await page.request.get(`${state.localUrl}/api/logs/status`);
  expect(res.status()).toBe(200);
  return ((await res.json()) as { oldest_day: string | null }).oldest_day;
}

test("lowering retention previews and then purges", async ({ page, state, loginAs }) => {
  const [older, newer] = state.oldLogDays;
  await loginAs(page, "admin", "local");
  // the seed is indexed: the older day is the oldest one (otherwise the purge check below proves nothing)
  await expect.poll(() => oldestDay(page, state), { timeout: 20_000 }).toBe(older);

  await page.goto(`${state.localUrl}/admin/settings`);
  await page.getByLabel(copy.settings.fields.log_compress_after_days, { exact: true }).fill("30");
  await page.getByLabel(copy.settings.fields.log_retention_days, { exact: true }).fill("60");
  await page.getByRole("button", { name: copy.common.save }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText(older);
  await expect(dialog).not.toContainText(newer);
  await expect(dialog).toContainText(copy.settings.retentionRunsSoon);
  await dialog.getByRole("button", { name: copy.settings.confirmDelete }).click();
  await expect(dialog).toHaveCount(0);

  await expect.poll(() => oldestDay(page, state), { timeout: 20_000 }).toBe(newer);

  // restore the default for later specs (a longer retention deletes nothing: no confirm)
  await page.getByLabel(copy.settings.fields.log_retention_days, { exact: true }).fill("180");
  await page.getByRole("button", { name: copy.common.save }).click();
  await expect(page.getByText(copy.common.saved)).toBeVisible();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
});
