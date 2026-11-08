import { copy, expect, tabTo, test } from "./fixtures";

const TITLE = "E2E 점검 공지";
const KEYBOARD_TITLE = "E2E 키보드 공지";

test("notice editor preview, save, full-screen preview in place, standalone page, revert to default", async ({ page, context, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/notice`);
  const preview = page.getByRole("group", { name: copy.notice.previewLabel });
  await expect(preview).toContainText(copy.notice.builtIn.title);

  const title = page.getByLabel(copy.notice.fields.title);
  await title.fill(TITLE);
  await expect(preview).toContainText(TITLE); // live preview, before saving
  await page.getByRole("button", { name: copy.common.save, exact: true }).click();
  await expect(page.getByText(copy.notice.savedVersion(1))).toBeVisible();

  // the full-screen preview opens in place over the editor and closes back to it: no navigation
  const navigations: string[] = [];
  page.on("framenavigated", (f) => f === page.mainFrame() && navigations.push(f.url()));
  const pagesBefore = context.pages().length;
  const trigger = page.getByRole("button", { name: copy.notice.fullPreview });
  await title.fill(`${TITLE} (저장 안 함)`); // unsaved: the preview shows the saved text
  await trigger.click();
  const full = page.getByRole("dialog", { name: copy.notice.fullPreview });
  await expect(full.getByRole("heading", { name: TITLE, exact: true })).toBeVisible();
  const close = full.getByRole("button", { name: copy.notice.fullPreviewClose });
  await expect(close).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(full).toBeHidden();
  await expect(trigger).toBeFocused();
  await trigger.click();
  await full.getByRole("button", { name: copy.notice.fullPreviewClose }).click();
  await expect(full).toBeHidden();
  await expect(trigger).toBeFocused();
  await expect(title).toHaveValue(`${TITLE} (저장 안 함)`);
  expect(navigations).toEqual([]);
  expect(new URL(page.url()).pathname).toBe("/admin/notice");
  expect(context.pages()).toHaveLength(pagesBefore);
  await title.fill(TITLE); // back to the saved text: nothing left unsaved

  // /notice opened directly (preview mode) shows the saved text as the modal notice, with a way back
  const standalone = await context.newPage();
  await standalone.goto(`${state.localUrl}/notice`);
  const dialog = standalone.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: TITLE })).toBeVisible();
  await expect(dialog.getByRole("button", { name: copy.notice.builtIn.button_text })).toBeFocused();

  // revert to the built-in text (version 0): a new version 2
  const versions = page.getByRole("list", { name: copy.notice.versions });
  await versions.getByRole("button", { name: new RegExp(`^${copy.notice.defaultVersion}`) }).click();
  await page.getByRole("button", { name: copy.notice.revert }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: copy.notice.revertAction }).click();
  await expect(page.getByText(copy.notice.revertedTo(0, 2))).toBeVisible();
  await expect(title).toHaveValue(copy.notice.builtIn.title);

  await standalone.reload();
  await expect(standalone.getByRole("dialog").getByRole("heading", { name: copy.notice.builtIn.title })).toBeVisible();
  // the button acknowledges and the page says it may be closed
  await standalone.getByRole("dialog").getByRole("button", { name: copy.notice.builtIn.button_text }).click();
  await expect(standalone.getByText(copy.notice.acknowledged)).toBeVisible();
  await standalone.getByRole("link", { name: copy.notice.backToAdmin }).click();
  await expect(standalone).toHaveURL(/\/admin\/notice$/);
  await expect(standalone.getByLabel(copy.notice.fields.title)).toHaveValue(copy.notice.builtIn.title);
});

test("keyboard-only: edit the notice title and save it", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/notice`);
  const title = page.getByLabel(copy.notice.fields.title);
  await expect(title).toHaveValue(copy.notice.builtIn.title);
  await tabTo(page, title);
  await page.keyboard.press("Control+a");
  await page.keyboard.type(KEYBOARD_TITLE);
  await tabTo(page, page.getByRole("button", { name: copy.common.save, exact: true }));
  await page.keyboard.press("Enter");
  await expect(page.getByText(copy.notice.savedVersion(3))).toBeVisible();
  await expect(page.getByRole("group", { name: copy.notice.previewLabel })).toContainText(KEYBOARD_TITLE);

  // and back to the built-in title the same way (the visual baselines show the default notice)
  await tabTo(page, title, { back: true });
  await page.keyboard.press("Control+a");
  await page.keyboard.type(copy.notice.builtIn.title);
  await tabTo(page, page.getByRole("button", { name: copy.common.save, exact: true }));
  await page.keyboard.press("Enter");
  await expect(page.getByText(copy.notice.savedVersion(4))).toBeVisible();
});
