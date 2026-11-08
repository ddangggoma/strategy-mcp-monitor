import { DEFAULT_MCP_ICON, drawableIcon } from "@/lib/mcp-icon";
import { cn } from "@/lib/utils";
import "./McpIcon.css";

const DefaultIcon = DEFAULT_MCP_ICON;

/**
 * An MCP's icon: its emoji, or the default MCP icon when it has none (or a value that cannot be
 * one). Decorative — the MCP's name beside it stays the label — so hidden from assistive tech.
 */
export function McpIcon({ icon, size = "md", className }: { icon: string | null | undefined; size?: "sm" | "md" | "lg"; className?: string }) {
  const emoji = drawableIcon(icon);
  return (
    <span
      aria-hidden="true"
      data-testid="mcp-icon"
      data-icon={emoji ?? "default"}
      data-size={size}
      className={cn("mcp-icon", className)}
    >
      {emoji ?? <DefaultIcon strokeWidth={2} />}
    </span>
  );
}
