import type * as React from "react"
import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react"
import { Toaster as Sonner, type ToasterProps } from "sonner"

import { getThemePref } from "@/lib/theme"

// Toasts sit on the raised surface; the icon carries the outcome in its state color (icon +
// text, never color alone). Colors are our light-dark() tokens, so a theme flip needs no
// re-render; `theme` only steers Sonner's own fallbacks.
const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme={getThemePref()}
      className="toaster group"
      icons={{
        success: <CircleCheckIcon aria-hidden="true" className="size-4 text-state-healthy" />,
        info: <InfoIcon aria-hidden="true" className="size-4 text-fg-muted" />,
        warning: <TriangleAlertIcon aria-hidden="true" className="size-4 text-state-suspect" />,
        error: <OctagonXIcon aria-hidden="true" className="size-4 text-state-failed" />,
        loading: <Loader2Icon aria-hidden="true" data-anim="spin" className="size-4 animate-spin text-fg-muted" />,
      }}
      style={
        {
          "--normal-bg": "var(--color-surface-raised)",
          "--normal-text": "var(--color-fg)",
          "--normal-border": "var(--color-border)",
          "--border-radius": "var(--radius-md)",
          zIndex: "var(--z-toast)",
        } as React.CSSProperties
      }
      {...props}
    />
  )
}

export { Toaster }
