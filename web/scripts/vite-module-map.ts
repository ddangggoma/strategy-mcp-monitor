import type { Plugin } from "vite";

/** Emits `.vite/modules.json`: { [chunkFileName]: moduleIds[] }, used by the bundle-budget test. */
export function moduleMap(): Plugin {
  return {
    name: "mcpmon:module-map",
    apply: "build",
    generateBundle(_options, bundle) {
      const map: Record<string, string[]> = {};
      for (const [fileName, output] of Object.entries(bundle)) {
        if (output.type === "chunk") map[fileName] = [...output.moduleIds];
      }
      this.emitFile({
        type: "asset",
        fileName: ".vite/modules.json",
        source: JSON.stringify(map, null, 2),
      });
    },
  };
}
