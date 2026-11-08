import { useState } from "react";
import { DEFAULT_MCP_ICON, drawableIcon } from "@/lib/mcp-icon";
import { cn } from "@/lib/utils";
import "./McpIcon.css";

const DefaultIcon = DEFAULT_MCP_ICON;

/**
 * An MCP's icon: its uploaded image, else its emoji, else the default MCP icon (also when the image
 * fails to load, or the emoji is a value that cannot be one). Decorative — the MCP's name beside it
 * stays the label — so hidden from assistive tech and the image has an empty alt.
 */
export function McpIcon({
  icon,
  image,
  size = "md",
  className,
}: {
  icon: string | null | undefined;
  /** The uploaded image's URL (`icon_image`), or a data: URL for a picked file not uploaded yet. */
  image?: string | null;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const emoji = drawableIcon(icon);
  const src = image && image !== failed ? image : null;
  return (
    <span
      aria-hidden="true"
      data-testid="mcp-icon"
      data-icon={src ? "image" : (emoji ?? "default")}
      data-size={size}
      className={cn("mcp-icon", className)}
    >
      {src ? (
        <img src={src} alt="" draggable={false} decoding="async" onError={() => setFailed(src)} />
      ) : (
        (emoji ?? <DefaultIcon strokeWidth={2} />)
      )}
    </span>
  );
}
