import { useEffect, useEffectEvent, useRef, type ClipboardEvent, type KeyboardEvent } from "react";
import { copy } from "@/copy/ko";
import { cn } from "@/lib/utils";
import "./OtpInput.css";

export const OTP_LENGTH = 6;
const CELLS = Array.from({ length: OTP_LENGTH }, (_, i) => i);
const NON_DIGITS = /\D/g;

export interface OtpInputProps {
  /** Digits entered so far, always contiguous from the first cell ("", "24", "246810"). */
  value: string;
  onChange(v: string): void;
  /** Called once the sixth digit is in. */
  onComplete(v: string): void;
  /** Turning true shakes the cells, clears them and focuses the first one. */
  invalid: boolean;
  disabled?: boolean;
  /** Id of the text that says where the code was sent (read when focus enters the cells). */
  describedBy?: string;
}

/**
 * Six one-digit cells. Typing moves forward, Backspace in an empty cell moves back, ←/→ move.
 * A paste — or any change carrying several digits, which is how one-time-code autofill and
 * Playwright `fill` arrive (F19) — keeps only the digits and fills from the cursor.
 */
export function OtpInput({ value, onChange, onComplete, invalid, disabled = false, describedBy }: OtpInputProps) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);

  const focusCell = (i: number) => {
    const el = refs.current[Math.max(0, Math.min(OTP_LENGTH - 1, i))];
    el?.focus();
    el?.select();
  };

  /** New value; focus goes to `focusAt` (default: the first empty cell). */
  const commit = (next: string, focusAt?: number) => {
    const v = next.slice(0, OTP_LENGTH);
    focusCell(focusAt ?? v.length); // also when retyping the same digit: the caret still moves on
    if (v === value) return;
    onChange(v);
    if (v.length === OTP_LENGTH) onComplete(v);
  };

  /** Several digits at cell `i`: a full code replaces everything, a fragment is inserted there. */
  const insertDigits = (i: number, digits: string) => {
    if (digits.length >= OTP_LENGTH) commit(digits);
    else commit(value.slice(0, Math.min(i, value.length)) + digits + value.slice(Math.min(i, value.length) + digits.length));
  };

  const handleChange = (i: number, raw: string) => {
    const old = value[i] ?? "";
    const digits = raw.replace(NON_DIGITS, "");
    if (digits === "") {
      if (old !== "") commit(value.slice(0, i) + value.slice(i + 1), i); // the cell was cleared
      return; // a non-digit: nothing changes (React restores the controlled value)
    }
    // typing into a filled cell gives "old + new" (or "new + old"): keep the new digit
    const typedOver = old !== "" && digits.length === 2 && digits.includes(old);
    const incoming = typedOver ? digits.replace(old, "") : digits;
    if (incoming.length > 1) {
      insertDigits(i, incoming);
      return;
    }
    // one digit: overwrite cell i, or append when typed past the first empty cell (no gaps)
    const at = Math.min(i, value.length);
    commit(value.slice(0, at) + incoming + value.slice(at + 1), at + 1);
  };

  const handleKeyDown = (i: number, e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace" && (value[i] ?? "") === "" && i > 0) {
      e.preventDefault();
      focusCell(i - 1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      focusCell(i - 1);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      focusCell(i + 1);
    }
  };

  const handlePaste = (i: number, e: ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    const digits = e.clipboardData.getData("text").replace(NON_DIGITS, "").slice(0, OTP_LENGTH);
    if (digits) insertDigits(i, digits);
  };

  const clearAfterFailure = useEffectEvent(() => {
    if (value !== "") onChange("");
    focusCell(0);
  });
  useEffect(() => {
    if (invalid) clearAfterFailure();
  }, [invalid]);

  // the cells appear right after the user asked for a code: the caret goes straight to them
  const focusOnMount = useEffectEvent(() => focusCell(value.length));
  useEffect(() => {
    focusOnMount();
  }, []);

  return (
    <div
      role="group"
      aria-label={copy.login.codeGroup}
      aria-describedby={describedBy}
      data-invalid={invalid ? "" : undefined}
      data-anim="shake"
      className="otp-cells grid grid-cols-6 gap-2"
    >
      {CELLS.map((i) => (
        <input
          key={i}
          ref={(el) => {
            refs.current[i] = el;
          }}
          aria-label={copy.login.codeDigit(i + 1)}
          aria-invalid={invalid || undefined}
          inputMode="numeric"
          pattern="[0-9]*"
          autoComplete={i === 0 ? "one-time-code" : "off"}
          disabled={disabled}
          value={value[i] ?? ""}
          onChange={(e) => handleChange(i, e.target.value)}
          onKeyDown={(e) => handleKeyDown(i, e)}
          onPaste={(e) => handlePaste(i, e)}
          onFocus={(e) => e.target.select()}
          data-numeric=""
          className={cn(
            "h-14 w-full min-w-0 rounded-sm border border-border-strong bg-surface text-center text-2xl font-semibold text-fg",
            "transition-[border-color] duration-(--motion-fast) ease-hover hover:border-fg-muted",
            "disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-danger",
          )}
        />
      ))}
    </div>
  );
}
