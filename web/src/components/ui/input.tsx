import * as React from "react"
import { cn } from "@/lib/utils"

// border-strong is a meaningful boundary (3:1 against every surface, WCAG 1.4.11).
function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-(--size-control) w-full min-w-0 rounded-sm border border-border-strong bg-surface px-2.5 py-1 text-sm text-fg transition-[border-color] duration-(--motion-fast) ease-hover placeholder:text-fg-muted hover:border-fg-muted",
        "file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-fg",
        "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 read-only:bg-sunken",
        "aria-invalid:border-danger",
        className
      )}
      {...props}
    />
  )
}

export { Input }
