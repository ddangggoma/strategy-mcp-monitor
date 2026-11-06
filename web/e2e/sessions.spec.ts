import { expect } from "@playwright/test";
import { copy } from "../src/copy/ko";
import { test } from "./fixtures";
import { clearSessions, rdp, setSessions } from "./sessions";

test.afterEach(async ({ state }) => { await clearSessions(state); });

test("board shows 접속 중 within 2 s of an RDP connection and clears on logoff", async ({ page, state }) => {
  await page.goto(`${state.externalUrl}/`);
  await expect(page.getByText(copy.board.noSession)).toBeVisible();
  await setSessions(state, [rdp({ session_id: 42, client_ip: "10.0.3.21" })]); // not this session: no agent, board only
  await expect(page.getByText(copy.board.connected)).toBeVisible({ timeout: 2_000 });
  await expect(page.getByText("10.0.3.21")).toBeVisible();
  await setSessions(state, []);
  await expect(page.getByText(copy.board.noSession)).toBeVisible({ timeout: 2_000 });
});

test("a developer sees the connection history on the remote channel", async ({ page, state, loginAs }) => {
  await setSessions(state, [rdp({ session_id: 43, user: "kim" })]);
  await loginAs(page, "dev", "external");
  await page.goto(`${state.externalUrl}/admin/sessions`);
  await expect(page.getByTestId("connection-row").filter({ hasText: "kim" }).first()).toBeVisible({ timeout: 5_000 });
});
