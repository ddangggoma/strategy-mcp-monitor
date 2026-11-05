import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  // ko.test.ts reads the server's built-in notice text to catch drift between the two copies
  server: {
    fs: {
      allow: [
        fileURLToPath(new URL(".", import.meta.url)),
        fileURLToPath(new URL("../server/app/notice/", import.meta.url)),
      ],
    },
  },
  test: {
    environment: "jsdom",
    environmentOptions: { jsdom: { url: "http://localhost:3000/" } },
    globals: true,
    // CSS is stripped in tests by default; the token tests read src/styles/*.css?raw as text
    css: { include: [/[\\/]src[\\/]styles[\\/][\w-]+\.css\?raw/] },
    setupFiles: ["tests/setup.ts"],
    // route-level tests mount the whole admin app and compile lazy page chunks; under the full
    // parallel run a few of them pass 5 s (the default) on this PC, so the limit is 15 s
    testTimeout: 15_000,
    include: ["src/**/*.test.{ts,tsx}", "tests/**/*.test.{ts,tsx}"],
    exclude: ["tests/budget/**", "e2e/**", "node_modules/**", "dist/**"],
  },
});
