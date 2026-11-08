// What the board, lists and detail need to draw an MCP's icon (one emoji, or null for the default
// MCP icon). Kept tiny: the board bundle loads it. The full emoji rules and the picker's list live
// in mcp-emoji.ts (admin only); the server validates every stored icon (app/monitor/icons.py).
import { PlugIcon, type LucideIcon } from "lucide-react";

/** The icon of an MCP without an emoji. */
export const DEFAULT_MCP_ICON: LucideIcon = PlugIcon;

// a last guard for display only: short, and no letters, digits, spaces, controls or markup
const DRAWABLE = /^[^\p{L}\p{N}\p{Z}\p{Cc}<>&"']{1,16}$/u;

/** The emoji to draw, or null for the default icon. React renders it as text, never as markup. */
export function drawableIcon(icon: string | null | undefined): string | null {
  return typeof icon === "string" && DRAWABLE.test(icon) ? icon : null;
}
