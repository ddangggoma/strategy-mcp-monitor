import { defineConfig } from "vitest/config";

// Runs against the production build in dist/ (run `pnpm build` first).
export default defineConfig({
  test: {
    environment: "node",
    globals: true,
    include: ["tests/budget/**/*.test.ts"],
  },
});
