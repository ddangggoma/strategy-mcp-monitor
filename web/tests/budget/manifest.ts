import { readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

export type Entry = "board.html" | "admin.html" | "notice.html";

interface ManifestChunk {
  file: string;
  imports?: string[];
}

type Manifest = Record<string, ManifestChunk>;

function readManifest(dist: string): Manifest {
  return JSON.parse(readFileSync(join(dist, ".vite", "manifest.json"), "utf8")) as Manifest;
}

/** Entry chunk plus every statically imported chunk (dynamic imports are not initial load). */
function initialChunks(dist: string, entry: Entry): string[] {
  const manifest = readManifest(dist);
  if (!manifest[entry]) throw new Error(`${entry} is missing from dist/.vite/manifest.json`);
  const files = new Set<string>();
  const seen = new Set<string>();
  const visit = (key: string) => {
    if (seen.has(key)) return;
    seen.add(key);
    const chunk = manifest[key];
    if (!chunk) throw new Error(`manifest key ${key} not found (imported by ${entry})`);
    files.add(chunk.file);
    for (const child of chunk.imports ?? []) visit(child);
  };
  visit(entry);
  return [...files];
}

export function entryJsGzipBytes(dist: string, entry: Entry): number {
  return initialChunks(dist, entry)
    .filter((file) => file.endsWith(".js"))
    .reduce((sum, file) => sum + gzipSync(readFileSync(join(dist, file)), { level: 9 }).length, 0);
}

/** Module ids bundled into the entry's initial chunks (from dist/.vite/modules.json). */
export function entryModules(dist: string, entry: Entry): string[] {
  const modules = JSON.parse(readFileSync(join(dist, ".vite", "modules.json"), "utf8")) as Record<
    string,
    string[]
  >;
  return initialChunks(dist, entry)
    .filter((file) => file.endsWith(".js"))
    .flatMap((file) => {
      const ids = modules[file];
      if (!ids) throw new Error(`${file} is missing from dist/.vite/modules.json`);
      return ids;
    });
}
