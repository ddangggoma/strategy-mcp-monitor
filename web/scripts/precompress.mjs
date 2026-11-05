// Usage: node scripts/precompress.mjs <dir>
// Writes <file>.br (brotli q11) and <file>.gz (gzip l9) next to every text asset.
import { brotliCompressSync, constants, gzipSync } from "node:zlib";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { extname, join } from "node:path";

const dir = process.argv[2];
if (!dir) {
  console.error("usage: node scripts/precompress.mjs <dir>");
  process.exit(2);
}

const EXTENSIONS = new Set([".js", ".css", ".html", ".svg", ".json", ".txt"]);
const MIN_BYTES = 1024;

function* walk(root) {
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) yield* walk(path);
    else yield path;
  }
}

let count = 0;
for (const path of walk(dir)) {
  const ext = extname(path);
  if (!EXTENSIONS.has(ext)) continue;
  if (ext !== ".html" && statSync(path).size < MIN_BYTES) continue;
  const data = readFileSync(path);
  writeFileSync(
    `${path}.br`,
    brotliCompressSync(data, {
      params: {
        [constants.BROTLI_PARAM_QUALITY]: 11,
        [constants.BROTLI_PARAM_SIZE_HINT]: data.length,
      },
    }),
  );
  writeFileSync(`${path}.gz`, gzipSync(data, { level: 9 }));
  count += 1;
}
console.log(`precompress: ${count} files in ${dir}`);
