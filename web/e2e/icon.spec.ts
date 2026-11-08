import { deflateSync } from "node:zlib";
import { MCP_NAME, adminApi, copy, expect, test } from "./fixtures";

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff]! ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

/** A real, solid-colour RGB PNG (the browser must decode it, not fall back). */
function solidPng(size: number, [r, g, b]: [number, number, number]): Buffer {
  const chunk = (kind: string, body: Buffer) => {
    const head = Buffer.alloc(4);
    head.writeUInt32BE(body.length);
    const typed = Buffer.concat([Buffer.from(kind, "ascii"), body]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(typed));
    return Buffer.concat([head, typed, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr.set([8, 2, 0, 0, 0], 8); // 8-bit RGB
  const row = Buffer.concat([Buffer.from([0]), Buffer.from(Array.from({ length: size }, () => [r, g, b]).flat())]);
  const raw = Buffer.concat(Array.from({ length: size }, () => row));
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

// The per-MCP icon (one emoji): picked in the MCP settings, shown on the anonymous board live.
test("an emoji set in the MCP settings shows on the board; clearing it brings back the default icon", async ({ page, state, loginAs, request, browser }) => {
  const api = await adminApi(request, state);
  try {
    const board = await browser.newPage();
    await board.goto(`${state.externalUrl}/`);
    const card = board.getByTestId("mcp-card").filter({ hasText: MCP_NAME });
    await expect(card.getByTestId("mcp-icon")).toHaveAttribute("data-icon", "default");

    await loginAs(page, "admin", "local");
    await page.goto(`${state.localUrl}/admin/mcps/${state.mcpId}`);
    const icons = page.getByRole("radiogroup", { name: copy.mcp.icon.choiceLabel });
    await icons.getByRole("radio", { name: copy.mcp.icon.names["🧮"] }).click();
    await expect(page.getByTestId("mcp-icon-preview").getByTestId("mcp-icon")).toHaveAttribute("data-icon", "🧮");
    await page.getByRole("button", { name: copy.common.save, exact: true }).click();
    await expect(page.getByText(copy.common.saved)).toBeVisible();
    // the detail header shows it too
    await expect(page.getByRole("main").getByTestId("mcp-icon").first()).toHaveAttribute("data-icon", "🧮");

    // the anonymous board picks it up over SSE, without a reload
    await expect(card.getByTestId("mcp-icon")).toHaveAttribute("data-icon", "🧮", { timeout: 15_000 });
    await expect(card.getByTestId("mcp-icon")).toHaveText("🧮");

    // a pasted emoji outside the list
    await page.getByLabel(copy.mcp.icon.pasteLabel).fill("🦄");
    await page.getByRole("button", { name: copy.common.save, exact: true }).click();
    await expect(card.getByTestId("mcp-icon")).toHaveAttribute("data-icon", "🦄", { timeout: 15_000 });

    await icons.getByRole("radio", { name: copy.mcp.icon.defaultIcon }).click();
    await page.getByRole("button", { name: copy.common.save, exact: true }).click();
    await expect(card.getByTestId("mcp-icon")).toHaveAttribute("data-icon", "default", { timeout: 15_000 });
    await board.close();
  } finally {
    // later specs (visual baselines) expect the seeded MCP without an icon
    await api.put(`/api/mcps/${state.mcpId}`, { icon: null });
  }
});

// The MCP's real logo: uploaded from the settings (saved at once), drawn before the emoji on the
// anonymous board (over SSE), the MCP list and the detail header; removing it brings the emoji back.
test("an uploaded logo shows on the board and the MCP list; removing it brings back the emoji", async ({ page, state, loginAs, request, browser }) => {
  const api = await adminApi(request, state);
  try {
    await api.put(`/api/mcps/${state.mcpId}`, { icon: "🧮" });
    const board = await browser.newPage();
    await board.goto(`${state.externalUrl}/`);
    const cardIcon = board.getByTestId("mcp-card").filter({ hasText: MCP_NAME }).getByTestId("mcp-icon");
    await expect(cardIcon).toHaveAttribute("data-icon", "🧮");

    await loginAs(page, "admin", "local");
    await page.goto(`${state.localUrl}/admin/mcps/${state.mcpId}`);
    const imageGroup = page.getByRole("group", { name: copy.mcp.icon.image, exact: true });
    await expect(imageGroup.getByRole("button", { name: copy.mcp.icon.imageUpload })).toBeVisible();
    await page.getByTestId("mcp-icon-file").setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: solidPng(48, [230, 80, 20]) });
    await expect(page.getByText(copy.common.saved)).toBeVisible();
    const previewIcon = page.getByTestId("mcp-icon-preview").getByTestId("mcp-icon");
    await expect(previewIcon).toHaveAttribute("data-icon", "image");
    await expect(page.getByRole("main").getByTestId("mcp-icon").first()).toHaveAttribute("data-icon", "image"); // header
    await expect(imageGroup.getByRole("button", { name: copy.mcp.icon.imageUpload })).toBeVisible();

    // the anonymous board picks it up over SSE and actually draws the image (same origin: CSP img-src 'self')
    await expect(cardIcon).toHaveAttribute("data-icon", "image", { timeout: 15_000 });
    const boardImg = cardIcon.locator("img");
    await expect.poll(() => boardImg.evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth)).toBe(48);
    const src = await boardImg.getAttribute("src");
    expect(src).toMatch(new RegExp(`^/api/mcps/${state.mcpId}/icon-image\\?v=[0-9a-f]{12}$`));
    const served = await request.get(`${state.externalUrl}${src}`);
    expect(served.headers()["content-type"]).toBe("image/png");
    expect(served.headers()["cache-control"]).toBe("public, max-age=31536000, immutable");

    // the MCP list
    await page.goto(`${state.localUrl}/admin/mcps`);
    const row = page.getByRole("row").filter({ hasText: MCP_NAME });
    await expect(row.getByTestId("mcp-icon")).toHaveAttribute("data-icon", "image");

    // remove it: the emoji is back everywhere
    await page.goto(`${state.localUrl}/admin/mcps/${state.mcpId}`);
    await imageGroup.getByRole("button", { name: copy.mcp.icon.imageRemove }).click();
    await expect(previewIcon).toHaveAttribute("data-icon", "🧮");
    await expect(cardIcon).toHaveAttribute("data-icon", "🧮", { timeout: 15_000 });
    await board.close();
  } finally {
    await api.delete(`/api/mcps/${state.mcpId}/icon-image`);
    await api.put(`/api/mcps/${state.mcpId}`, { icon: null });
  }
});

test.describe("a refused logo", () => {
  test.use({ expectedStatuses: [422] }); // the server refuses the SVG

  test("an SVG with a script is refused with the reason, and nothing changes", async ({ page, state, loginAs }) => {
    await loginAs(page, "admin", "local");
    await page.goto(`${state.localUrl}/admin/mcps/${state.mcpId}`);
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><script>alert(1)</script><circle r="9"/></svg>';
    await page.getByTestId("mcp-icon-file").setInputFiles({ name: "logo.svg", mimeType: "image/svg+xml", buffer: Buffer.from(svg) });
    await expect(page.getByRole("alert").filter({ hasText: copy.mcp.icon.imageRejected })).toBeVisible();
    await expect(page.getByTestId("mcp-icon-preview").getByTestId("mcp-icon")).toHaveAttribute("data-icon", "default");
  });
});
