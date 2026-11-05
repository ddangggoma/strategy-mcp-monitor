import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { Slot } from "radix-ui"

// Emphasis is luminance, not hue: the primary button is an inverse fill (accent), so a colored
// control is never mistaken for an MCP state. Focus uses the global :focus-visible outline.
// aria-disabled (U26) looks disabled but stays focusable so its reason tooltip is reachable.
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-md text-sm font-medium whitespace-nowrap select-none transition-[background-color,color,border-color,transform] duration-(--motion-fast) ease-hover active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 aria-disabled:cursor-not-allowed aria-disabled:opacity-50 aria-disabled:active:scale-100 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-accent text-accent-fg hover:bg-accent/85",
        destructive: "bg-danger text-danger-fg hover:bg-danger/85",
        outline: "border border-border-strong bg-transparent text-fg hover:bg-hover",
        secondary: "bg-hover text-fg hover:bg-selected",
        ghost: "text-fg hover:bg-hover",
        link: "text-fg underline decoration-border-strong underline-offset-4 hover:decoration-fg active:scale-100",
      },
      size: {
        default: "h-(--size-control) px-3.5 has-[>svg]:px-3",
        xs: "h-6 gap-1 rounded-sm px-2 text-xs has-[>svg]:px-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-(--size-control-sm) gap-1.5 px-2.5 has-[>svg]:px-2",
        lg: "h-11 px-5 text-base has-[>svg]:px-4",
        icon: "size-(--size-control)",
        "icon-xs": "size-6 rounded-sm [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-(--size-control-sm)",
        "icon-lg": "size-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  type,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      // a plain <button> inside a form must not submit it by accident
      type={asChild ? type : (type ?? "button")}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
