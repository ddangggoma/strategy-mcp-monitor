import { cn } from "@/lib/utils"

// data-anim marks animated elements for the reduced-motion E2E check.
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      data-anim="pulse"
      aria-hidden="true"
      className={cn("animate-pulse rounded-sm bg-selected", className)}
      {...props}
    />
  )
}

export { Skeleton }
