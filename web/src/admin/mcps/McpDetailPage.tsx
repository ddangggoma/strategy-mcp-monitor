import { copy } from "@/copy/ko";

/** Route placeholder (F16): Tasks 11 and 12 replace it with the real page. Title only, no fake data. */
export function McpDetailPage() {
  return <h1 className="text-xl font-semibold text-fg">{copy.mcp.detail}</h1>;
}
