import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { Slot } from "radix-ui"

// Neutral badges (roles, channel, counts). MCP states use status/StatusBadge (icon + label on
// the state's -soft fill), never a color-only badge.
const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-sm border border-transparent px-1.5 py-0.5 text-xs font-medium whitespace-nowrap [&>svg]:pointer-events-none [&>svg]:size-3",
  {
    variants: {
      variant: {
        default: "bg-selected text-fg [a&]:hover:bg-hover",
        secondary: "bg-hover text-fg-muted [a&]:hover:bg-selected",
        destructive: "bg-state-failed-soft text-state-failed-fg",
        outline: "border-border-strong text-fg [a&]:hover:bg-hover",
        ghost: "text-fg-muted [a&]:hover:bg-hover",
        link: "text-fg underline-offset-4 [a&]:hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
