import { copy } from "@/copy/ko";
import { cn } from "@/lib/utils";

const DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"] as const;

export interface RollingNumberProps {
  value: number | null;
  unit: string;
  /** Places after the decimal point (default 0: a whole number). */
  decimals?: number;
  className?: string;
}

/**
 * A number whose digits roll: each place is a 0–9 column moved with translateY (transform only,
 * ease-out; base.css turns it off for reduced motion). Columns are keyed by place from the right,
 * so 99 → 100 keeps the ones and tens columns rolling; a decimal point or minus sign stays put.
 * On first show every column rolls up from 0. Screen readers get the real value as text; the
 * columns are aria-hidden.
 */
export function RollingNumber({ value, unit, decimals = 0, className }: RollingNumberProps) {
  if (value === null) {
    return (
      <span className={cn("inline-flex items-baseline", className)}>
        <span aria-hidden="true">—</span>
        <span className="sr-only">{copy.board.noData}</span>
      </span>
    );
  }
  const text = decimals > 0 ? value.toFixed(decimals) : String(Math.round(value));
  const chars = [...text];
  return (
    <span className={cn("inline-flex items-baseline", className)} data-numeric="">
      <span aria-hidden="true" data-anim="roll" data-volatile="" className="inline-flex">
        {chars.map((ch, i) => {
          const place = chars.length - 1 - i;
          const d = DIGITS.indexOf(ch as (typeof DIGITS)[number]);
          if (d === -1) {
            return <span key={`s${place}`}>{ch}</span>; // a minus sign or the decimal point
          }
          return (
            <span key={place} className="inline-block h-[1lh] overflow-hidden">
              <span
                data-digit={ch}
                // a new column rolls up from 0 to its digit (base.css digit-roll), later changes glide
                className="digit-roll flex flex-col transition-transform duration-(--motion-glide) ease-out"
                style={{ transform: `translateY(-${d * 10}%)` }}
              >
                {DIGITS.map((digit) => (
                  <span key={digit} className="h-[1lh]">
                    {digit}
                  </span>
                ))}
              </span>
            </span>
          );
        })}
        <span className="ms-1 self-end text-[0.45em] leading-[1.6] font-medium text-fg-muted">{unit}</span>
      </span>
      <span className="sr-only">{`${text} ${unit}`}</span>
    </span>
  );
}
