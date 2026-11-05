import * as React from "react"
import { cn } from "@/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex field-sizing-content min-h-20 w-full rounded-sm border border-border-strong bg-surface px-2.5 py-2 text-sm text-fg transition-[border-color] duration-(--motion-fast) ease-hover placeholder:text-fg-muted hover:border-fg-muted disabled:cursor-not-allowed disabled:opacity-50 read-only:bg-sunken aria-invalid:border-danger",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
