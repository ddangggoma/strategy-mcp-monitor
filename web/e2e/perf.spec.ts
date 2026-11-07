import { copy, expect, test } from "./fixtures";

test("board LCP under 1.5 s on the LAN-equivalent loopback", async ({ page, state }) => {
  await page.goto(`${state.externalUrl}/`);
  await expect(page.getByTestId("mcp-card").getByText(copy.states.HEALTHY)).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  // F07: the final LCP is the last entry once the page has painted its content, not the first batch
  const lcp = await page.evaluate(
    () =>
      new Promise<number[]>((res) => {
        new PerformanceObserver((list) => res(list.getEntries().map((e) => e.startTime))).observe({
          type: "largest-contentful-paint",
          buffered: true,
        });
      }),
  );
  expect(lcp.length).toBeGreaterThan(0);
  expect(lcp.at(-1)).toBeLessThan(1500);
});

test("hashed assets are immutable and precompressed", async ({ page, state }) => {
  const res: { url: string; cc: string | null; ce: string | null }[] = [];
  page.on("response", (r) => {
    if (new URL(r.url()).pathname.startsWith("/assets/"))
      res.push({ url: r.url(), cc: r.headers()["cache-control"] ?? null, ce: r.headers()["content-encoding"] ?? null });
  });
  // F07: not networkidle (the SSE stream never goes idle): the load event plus the first card
  await page.goto(`${state.externalUrl}/`, { waitUntil: "load" });
  await expect(page.getByTestId("mcp-card").first()).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  expect(res.length).toBeGreaterThan(0);
  for (const r of res) expect(r.cc, r.url).toBe("public, max-age=31536000, immutable");
  expect(res.filter((r) => r.url.endsWith(".js")).some((r) => r.ce === "br")).toBe(true); // chunks under 1 KB are not precompressed
});
