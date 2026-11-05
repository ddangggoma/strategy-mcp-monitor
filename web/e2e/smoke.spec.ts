import { test, expect } from "@playwright/test";

test("browser launches and renders the board entry", async ({ page }) => {
  await page.goto("/board.html");
  await expect(page.locator("h1")).toBeVisible();
});
