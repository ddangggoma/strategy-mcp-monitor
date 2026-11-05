import { DEV_OTP_CODE, UI_USERS, copy, expect, test } from "./fixtures";

test("email → OTP login lands on the dashboard with role and channel badges", async ({ page, state }) => {
  await page.goto(`${state.localUrl}/admin/login`);
  await expect(page.getByText(copy.login.devBadge)).toBeVisible();
  await page.getByLabel(copy.login.email).fill(UI_USERS.login.email);
  await page.getByRole("button", { name: copy.login.sendCode }).click();
  await page.getByRole("group", { name: copy.login.codeGroup }).locator("input").first().fill(DEV_OTP_CODE);
  await expect(page).toHaveURL(`${state.localUrl}/admin`);
  await expect(page.getByRole("banner").getByText(copy.channel.local)).toBeVisible();
  await expect(page.getByRole("navigation", { name: copy.nav.label }).getByText(copy.roles.admin)).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: copy.dashboard.title })).toBeVisible();
});

test.describe("a wrong code", () => {
  test.use({ expectedStatuses: [401] }); // the rejected verify

  test("shows the failure count and the lock hint, and stays on the code step", async ({ page, state }) => {
    await page.goto(`${state.localUrl}/admin/login`);
    await page.getByLabel(copy.login.email).fill(UI_USERS.wrongCode.email);
    await page.getByRole("button", { name: copy.login.sendCode }).click();
    const cells = page.getByRole("group", { name: copy.login.codeGroup }).locator("input");
    await cells.first().fill("000000");
    await expect(page.getByText(copy.login.failureHint)).toBeVisible();
    await expect(page.getByText(copy.login.failedCount(1))).toBeVisible();
    await expect(cells.first()).toHaveAttribute("aria-invalid", "true");
    await expect(page).toHaveURL(`${state.localUrl}/admin/login`);
  });
});

test("logout returns to anonymous and the stream reconnects anonymously", async ({ page, state, loginViaUi }) => {
  await loginViaUi(page, "logout", "local");
  const reconnect = page.waitForRequest((r) => new URL(r.url()).pathname === "/api/stream");
  await page.getByRole("button", { name: copy.common.accountMenu(UI_USERS.logout.name) }).click();
  await page.getByRole("menuitem", { name: copy.common.logout }).click();
  await expect(page).toHaveURL(`${state.localUrl}/admin/login`);
  const stream = await reconnect;
  expect((await stream.allHeaders()).cookie ?? "").not.toContain("mcpmon_sid_local=");
  const me = (await (await page.request.get(`${state.localUrl}/api/auth/me`)).json()) as { user: unknown };
  expect(me.user).toBeNull();
});

test("both channels stay signed in at once on one host", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await loginAs(page, "admin", "external"); // same context, same host 127.0.0.1, different cookie names (U3)
  for (const url of [state.localUrl, state.externalUrl]) {
    const me = (await (await page.request.get(`${url}/api/auth/me`)).json()) as { user: { email: string } | null };
    expect(me.user?.email).toBe(state.adminEmail);
  }
});
