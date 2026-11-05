import { defineConfig } from "@playwright/test";

// Task 15 replaces this with real-backend projects and deletes e2e/smoke.spec.ts.
export default defineConfig({
  testDir: "./e2e",
  testMatch: "smoke.spec.ts",
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:4173" },
  projects: [{ name: "smoke" }],
  webServer: {
    command: "pnpm exec vite preview --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173/board.html",
    reuseExistingServer: false,
  },
});
