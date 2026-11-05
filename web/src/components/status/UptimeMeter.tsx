import { copy } from "@/copy/ko";
import { cn } from "@/lib/utils";

/**
 * 24 h uptime as a number, not a bar: values sit at 99.x% almost always, where a meter is a full
 * bar that says nothing (dataviz: a single ratio is a stat). `value` is a 0–1 ratio.
 */
export function UptimeMeter({ value, className }: { value: number | null; className?: string }) {
  if (value === null) return <span className={cn("text-base font-medium text-fg-muted", className)}>{copy.board.noRecord}</span>;
  return (
    <data value={value} className={className}>
      {copy.common.units.percent((value * 100).toFixed(1))}
    </data>
  );
}
