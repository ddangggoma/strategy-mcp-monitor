import { defineConfig, devices } from "@playwright/test";

// E2E against the real backend (U24): globalSetup starts the server on a throwaway root and seeds
// it; every test shares that one backend, so the run is serial. Tests navigate to
// state.localUrl / state.externalUrl themselves (two channels, no single baseURL).
// Browser: Playwright's Chromium. Task 1 found it runs under this PC's app control, so the
// `channel: "msedge"` fallback of U24 is not needed.
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  workers: 1,
  fullyParallel: false,
  retries: 0,
  // a manual action runs a PowerShell script on the server: allow for a slow stop + start
  timeout: 90_000,
  reporter: [["list"]],
  expect: {
    toHaveScreenshot: { animations: "disabled", maxDiffPixelRatio: 0.01 },
  },
  use: {
    ...devices["Desktop Chrome"],
    viewport: { width: 1280, height: 800 },
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium-dark", use: { colorScheme: "dark" } },
    { name: "chromium-light", testMatch: "visual.spec.ts", use: { colorScheme: "light" } },
  ],
});
