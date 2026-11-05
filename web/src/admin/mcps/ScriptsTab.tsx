import { copy } from "@/copy/ko";
import type { McpDetail } from "@/lib/api-types";

/** Placeholder (F16/P21): Task 12 replaces it with the script viewer, editor and versions. Title only, no fake data. */
export function ScriptsTab({ mcp }: { mcp: McpDetail }) {
  return (
    <h2 data-mcp={mcp.id} className="text-base font-semibold text-fg">
      {copy.scripts.title}
    </h2>
  );
}
