import { copy, expect, test } from "./fixtures";

test("owner edits a script in CodeMirror, sees the diff and reverts", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/mcps/${state.mcpId}?tab=scripts&kind=restart`);
  const pane = page.getByRole("region", { name: copy.scripts.kinds.restart });
  const versionText = (v: number) => pane.getByText(copy.scripts.versionLabel(v), { exact: true }).first();
  await expect(page.getByTestId("script-editor")).toBeVisible();
  await expect(versionText(1)).toBeVisible();

  const editor = page.getByRole("textbox", { name: copy.scripts.editorLabel(copy.scripts.kinds.restart) });
  await editor.click();
  await page.keyboard.press("Control+End");
  await page.keyboard.press("Enter");
  await page.keyboard.type("# e2e");
  await page.getByTestId("script-editor").getByRole("button", { name: copy.common.save }).click();
  await expect(page.getByText(copy.scripts.savedVersion(2))).toBeVisible();

  // pick version 1: the diff against the current text shows the added line
  const versions = page.getByRole("list", { name: copy.scripts.versions });
  await versions.getByRole("button", { name: new RegExp(`^${copy.scripts.versionLabel(1)}`) }).click();
  const diff = page.getByRole("region", { name: copy.diff.caption(copy.scripts.versionLabel(1), copy.scripts.current) });
  const added = diff.getByRole("row").filter({ hasText: copy.diff.added });
  await expect(added.filter({ hasText: "# e2e" })).toHaveCount(1);

  // revert to version 1: a new version 3 with the old text
  await page.getByRole("button", { name: copy.scripts.revert }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: copy.scripts.revertAction }).click();
  await expect(page.getByText(copy.scripts.reverted(1, 3))).toBeVisible();
  await expect(versions.getByRole("button", { name: new RegExp(`^${copy.scripts.versionLabel(3)}`) })).toBeVisible();
  await expect(editor).not.toContainText("# e2e");
});
