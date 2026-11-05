import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";
import { moduleMap } from "./scripts/vite-module-map.ts";

/** Dev-only: map the production routes onto the three HTML entries. */
function spaFallback(): Plugin {
  const target = (path: string): string | null => {
    if (path === "/") return "/board.html";
    if (path === "/admin" || path.startsWith("/admin/")) return "/admin.html";
    if (path === "/notice") return "/notice.html";
    return null;
  };
  return {
    name: "mcpmon:spa-fallback",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const url = req.url ?? "/";
        const queryAt = url.indexOf("?");
        const path = queryAt === -1 ? url : url.slice(0, queryAt);
        const rewritten = target(path);
        if (rewritten) req.url = rewritten + (queryAt === -1 ? "" : url.slice(queryAt));
        next();
      });
    },
  };
}

export default defineConfig({
  base: "/",
  plugins: [react(), tailwindcss(), spaFallback(), moduleMap()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8700", changeOrigin: true },
    },
  },
  build: {
    manifest: true,
    sourcemap: false,
    target: ["chrome123", "edge123", "firefox128", "safari17.5"],
    rollupOptions: {
      input: { board: "board.html", admin: "admin.html", notice: "notice.html" },
    },
  },
});
