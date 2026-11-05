import { existsSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { chunkModules, entryJsGzipBytes, entryModules } from "./manifest";

const DIST = fileURLToPath(new URL("../../dist", import.meta.url));

it("board initial JS < 200 KB gzip", () => {
  const bytes = entryJsGzipBytes(DIST, "board.html");
  expect(bytes).toBeGreaterThan(1024); // React is in there: a tiny value means we measured nothing
  expect(bytes).toBeLessThan(200 * 1024);
});

it("notice initial JS < 100 KB gzip", () => {
  const bytes = entryJsGzipBytes(DIST, "notice.html");
  expect(bytes).toBeGreaterThan(1024);
  expect(bytes).toBeLessThan(100 * 1024);
});

it("board pulls no admin-only library", () => {
  const bad = /recharts|@codemirror|codemirror|@tanstack\/react-router|cmdk|react-hook-form|zod|[\\/]diff[\\/]/;
  const modules = entryModules(DIST, "board.html");
  expect(modules.some((m) => /[\\/]react-dom[\\/]/.test(m))).toBe(true); // the module list is real
  expect(modules.filter((m) => bad.test(m))).toEqual([]);
});

it("CodeMirror is one lazy chunk, outside the admin entry and the page chunks", () => {
  const editor = /[\\/]@codemirror[\\/]|[\\/]@lezer[\\/]/;
  const chunks = Object.entries(chunkModules(DIST)).filter(([, ids]) => ids.some((id) => editor.test(id)));
  expect(chunks).toHaveLength(1); // shared by the scripts tab and the registration page
  const [, ids] = chunks[0]!;
  expect(ids.some((id) => /[\\/]admin[\\/]scripts[\\/]ScriptEditor\.tsx$/.test(id))).toBe(true);
  expect(ids.some((id) => /McpDetailPage|McpCreatePage|ScriptsTab/.test(id))).toBe(false);
  expect(entryModules(DIST, "admin.html").filter((m) => editor.test(m))).toEqual([]);
});

it("every text asset has .br and .gz siblings", () => {
  const assets = join(DIST, "assets");
  expect(existsSync(assets)).toBe(true);
  const big = readdirSync(assets).filter(
    (f) => /\.(js|css)$/.test(f) && statSync(join(assets, f)).size >= 1024,
  );
  expect(big.length).toBeGreaterThan(0);
  for (const f of big) {
    expect(statSync(join(assets, `${f}.br`)).size, `${f}.br`).toBeGreaterThan(0);
    expect(statSync(join(assets, `${f}.gz`)).size, `${f}.gz`).toBeGreaterThan(0);
  }
});
