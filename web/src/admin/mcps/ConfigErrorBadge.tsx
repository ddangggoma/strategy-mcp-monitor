import { OctagonAlertIcon } from "lucide-react";
import { copy } from "@/copy/ko";
import { cn } from "@/lib/utils";

/** An unmonitored MCP (its saved config fails validation): outline only, no state hue. */
export function ConfigErrorBadge({ size = "sm" }: { size?: "sm" | "lg" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm border border-border-strong font-medium whitespace-nowrap text-fg",
        size === "sm" ? "gap-1 px-1.5 py-0.5 text-xs [&_svg]:size-3.5" : "gap-1.5 px-2 py-1 text-sm [&_svg]:size-4",
      )}
    >
      <OctagonAlertIcon aria-hidden="true" />
      {copy.mcp.configErrorBadge}
    </span>
  );
}
