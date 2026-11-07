// The audit screen (Plan 5 Task 12) on the real index: admin actions and login attempts with
// their channel and result. The seed's user_create lines are among the oldest of the run, so the
// keyword narrows to them first (F15: the virtual table renders only rows near the viewport).
import { copy, expect, test } from "./fixtures";

test("audit page lists the admin's actions with channel and result", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/audit?range=today&q=user_create`);
  const table = page.getByRole("table", { name: copy.audit.title });
  const row = table.getByRole("row").filter({ hasText: "user_create" }).first();
  await expect(row).toContainText(copy.channel.local, { timeout: 10_000 });
  await expect(row).toContainText(copy.audit.results.ok);

  await page.goto(`${state.localUrl}/admin/audit?range=today`);
  await page.getByRole("tab", { name: copy.audit.kinds.auth }).click();
  await expect(page).toHaveURL(/kind=/);
  const auth = page.getByRole("table", { name: copy.audit.title });
  await expect(auth.getByRole("row").filter({ hasText: "login" }).first()).toBeVisible({ timeout: 10_000 });
  // the auth tab holds login attempts only: no admin action is listed there
  await expect(auth.getByRole("row").filter({ hasText: "user_create" })).toHaveCount(0);
});
