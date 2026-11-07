import { expect } from "@playwright/test";
import { copy } from "../src/copy/ko";
import { adminApi, test } from "./fixtures";
import { clearSessions, logEvents, noticeOpens, rdp, setSessions, waitForNoticeUrl } from "./sessions";

test.afterEach(async ({ state }) => { await clearSessions(state); });

test("each connection shows the notice and the acknowledgement is recorded", async ({ page, context, state, request }) => {
  const before = (await noticeOpens(state)).length;
  const current = await (await (await adminApi(request, state)).get("/api/notice")).json();
  await setSessions(state, [rdp()]);
  const notice = await context.newPage();
  await notice.setViewportSize({ width: 640, height: 600 }); // the agent's Edge app window (C4)
  await notice.goto(await waitForNoticeUrl(state, before + 1));
  await expect(notice.getByRole("dialog")).toContainText(current.title);
  expect(new URL(notice.url()).hash).toBe("");
  expect(await notice.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  await notice.getByRole("button", { name: current.button_text }).click();
  await expect(notice.getByText(copy.notice.acknowledged)).toBeVisible();
  await page.goto(`${state.externalUrl}/`);
  await expect(page.getByText(copy.sessions.noticeAcked)).toBeVisible({ timeout: 2_000 });
  await expect.poll(async () => (await logEvents(state, "notice")).map((e) => e.event))
    .toEqual(expect.arrayContaining(["notice_shown", "notice_acknowledged"]));
});

test("a reload (F5) of the notice window stays on the display and still records the acknowledgement", async ({ context, state }) => {
  const before = (await noticeOpens(state)).length;
  await setSessions(state, [rdp()]);
  const notice = await context.newPage();
  await notice.goto(await waitForNoticeUrl(state, before + 1));
  await expect(notice.getByRole("dialog")).toBeVisible();
  const { id } = (await noticeOpens(state))[before] as { id: number };
  await notice.reload();
  expect(new URL(notice.url()).hash).toBe(""); // the token did not come back into the address
  await notice.getByRole("dialog").getByRole("button").click();
  await expect(notice.getByText(copy.notice.acknowledged)).toBeVisible();
  await expect.poll(async () => (await logEvents(state, "notice")).filter((e) => e.display_id === id).map((e) => e.event))
    .toEqual(["notice_shown", "notice_acknowledged"]);
});

test("reconnect shows the notice again", async ({ context, state, request }) => {
  const api = await adminApi(request, state);
  const before = (await noticeOpens(state)).length;
  await setSessions(state, [rdp({ connected_at: "2026-11-04T13:00:00+09:00" })]);
  await waitForNoticeUrl(state, before + 1);
  await setSessions(state, [rdp({ state: "disconnected", connected_at: "2026-11-04T13:00:00+09:00" })]);
  await expect.poll(async () => (await (await api.get("/api/sessions/current")).json()).sessions.map((s: { state: string }) => s.state))
    .toEqual(["disconnected"]);
  await setSessions(state, [rdp({ connected_at: "2026-11-04T13:30:00+09:00" })]);
  const p = await context.newPage();
  await p.goto(await waitForNoticeUrl(state, before + 2));
  await p.getByRole("dialog").getByRole("button").click();
  await expect(p.getByText(copy.notice.acknowledged)).toBeVisible();
  const shown = (await logEvents(state, "notice")).filter((e) => e.event === "notice_shown");
  expect(shown.at(-1)?.kind).toBe("reconnect");
});
