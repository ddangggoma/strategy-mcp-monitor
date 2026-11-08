// §11 P3 completion criteria: permission UI is visible-but-disabled with the reason, and the server
// still decides.
import { MCP_NAME, adminApi, copy, expect, test } from "./fixtures";

const LOCAL_ONLY_APIS = ["/scripts", "/api/users", "/api/settings", "/api/notice"];

test("non-owner developer on local: read-only script with the owner reason", async ({ page, state, loginAs }) => {
  await loginAs(page, "dev", "local");
  await page.goto(`${state.localUrl}/admin/mcps/${state.mcpId}?tab=scripts`);
  await expect(page.getByTestId("script-viewer")).toBeVisible();
  await expect(page.getByTestId("script-editor")).toHaveCount(0);
  const edit = page.getByRole("button", { name: copy.scripts.edit, exact: true });
  await expect(edit).toHaveAttribute("aria-disabled", "true");
  await edit.focus();
  await expect(page.getByRole("tooltip")).toContainText(copy.deny.owner_only);
  // clicking does nothing: still the viewer (force: Playwright itself refuses aria-disabled targets)
  await edit.click({ force: true });
  await expect(page.getByTestId("script-editor")).toHaveCount(0);
});

test("owner admin on external: scripts disabled with the local-only reason and no script request", async ({ page, state, loginAs }) => {
  const seen: string[] = [];
  page.on("request", (r) => seen.push(new URL(r.url()).pathname));
  await loginAs(page, "admin", "external");
  await page.goto(`${state.externalUrl}/admin/mcps/${state.mcpId}?tab=scripts`);
  await expect(page.getByRole("main").getByText(copy.deny.local_only).filter({ visible: true }).first()).toBeVisible();
  await expect(page.getByTestId("script-viewer")).toHaveCount(0);
  expect(seen.filter((p) => p.includes("/scripts"))).toEqual([]);
});

test("external: local-only nav items are disabled and direct URLs explain without calling Local APIs", async ({ page, state, loginAs }) => {
  const seen: string[] = [];
  page.on("request", (r) => seen.push(new URL(r.url()).pathname));
  await loginAs(page, "admin", "external");
  const nav = page.getByRole("navigation", { name: copy.nav.label });
  for (const key of ["users", "notice", "settings"] as const) {
    await expect(nav.getByRole("link", { name: copy.nav[key] })).toHaveAttribute("aria-disabled", "true");
  }
  for (const path of ["/admin/users", "/admin/settings", "/admin/notice", "/admin/mcps/new"]) {
    await page.goto(`${state.externalUrl}${path}`);
    // the explanation is in the page body, not only in the nav tooltips
    await expect(page.getByRole("main").getByText(copy.deny.local_only).filter({ visible: true }).first()).toBeVisible();
  }
  // Task 14 carry: /admin/notice (and the other Local-only pages) never call their APIs externally
  expect(seen.filter((p) => LOCAL_ONLY_APIS.some((api) => p.includes(api)))).toEqual([]);
});

test("the server still refuses a script PUT from a non-owner", async ({ state, request }) => {
  const dev = await adminApi(request, state, "dev");
  const res = await dev.put(`/api/mcps/${state.mcpId}/scripts/start`, { ext: ".ps1", content: "Write-Host 'not mine'" });
  expect(res.status()).toBe(403);
  expect(await res.json()).toEqual({ error: "forbidden" });
  // and the script is unchanged
  const admin = await adminApi(request, state);
  const script = (await (await admin.get(`/api/mcps/${state.mcpId}/scripts/start`)).json()) as { version: number; content: string };
  expect(script.version).toBe(1);
  expect(script.content).not.toContain("not mine");
});

test("an admin transfers MCP ownership from the detail page", async ({ page, state, loginAs, request }) => {
  const admin = await adminApi(request, state);
  const users = (await (await admin.get("/api/users")).json()) as { id: number; email: string; name: string }[];
  const dev = users.find((u) => u.email === state.devEmail)!;
  const me = users.find((u) => u.email === state.adminEmail)!;
  try {
    await loginAs(page, "admin", "local");
    await page.goto(`${state.localUrl}/admin/mcps/${state.mcpId}`);
    await page.getByRole("button", { name: copy.mcp.transferOwner }).click();
    const dialog = page.getByRole("dialog", { name: copy.mcp.transferOwner });
    await dialog.getByRole("combobox", { name: copy.mcp.newOwner }).click();
    await page.getByRole("option", { name: new RegExp(dev.name) }).click();
    await dialog.getByRole("button", { name: copy.mcp.transferSubmit }).click();
    await expect(page.getByText(copy.mcp.transferred(MCP_NAME, dev.name))).toBeVisible();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("main").getByText(dev.name, { exact: true })).toBeVisible();
    const detail = (await (await admin.get(`/api/mcps/${state.mcpId}`)).json()) as { owner: { id: number } | null };
    expect(detail.owner?.id).toBe(dev.id);
  } finally {
    // later specs (and the detail screenshot) expect the seeded owner
    expect((await admin.post(`/api/mcps/${state.mcpId}/owner`, { user_id: me.id })).status()).toBe(200);
  }
});
