import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  // ko.test.ts reads the server's built-in notice text, NoticeApp.test.tsx the agent's notice window
  // title, to catch drift between the copies
  server: {
    fs: {
      allow: [
        fileURLToPath(new URL(".", import.meta.url)),
        fileURLToPath(new URL("../server/app/notice/", import.meta.url)),
        fileURLToPath(new URL("../agent/mcp_agent/", import.meta.url)),
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
    // the vitest default: route-level files load their lazy chunks in beforeAll (tests/warm.ts), so
    // no test pays a cold chunk compile and a real hang fails fast
    testTimeout: 5_000,
    include: ["src/**/*.test.{ts,tsx}", "tests/**/*.test.{ts,tsx}"],
    exclude: ["tests/budget/**", "e2e/**", "node_modules/**", "dist/**"],
  },
});
