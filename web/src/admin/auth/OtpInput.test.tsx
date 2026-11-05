import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { copy } from "@/copy/ko";
import { OtpInput } from "./OtpInput";

interface HarnessProps {
  onComplete?: (v: string) => void;
  onChange?: (v: string) => void;
  invalid?: boolean;
  disabled?: boolean;
  initial?: string;
}

/** OtpInput is controlled: the harness holds the value like LoginPage does. */
function Harness({ onComplete = () => {}, onChange, invalid = false, disabled, initial = "" }: HarnessProps) {
  const [value, setValue] = useState(initial);
  return (
    <OtpInput
      value={value}
      onChange={(v) => {
        setValue(v);
        onChange?.(v);
      }}
      onComplete={onComplete}
      invalid={invalid}
      disabled={disabled}
    />
  );
}

function renderOtp(props: HarnessProps = {}) {
  const r = render(<Harness {...props} />);
  return { ...r, rerenderOtp: (p: HarnessProps) => r.rerender(<Harness {...props} {...p} />) };
}

const cell = (i: number) => screen.getByLabelText(copy.login.codeDigit(i + 1)) as HTMLInputElement;
const values = () => [0, 1, 2, 3, 4, 5].map((i) => cell(i).value).join("");

it("fills all cells from a paste with separators and completes", async () => {
  const onComplete = vi.fn();
  renderOtp({ onComplete });
  await userEvent.click(cell(0));
  await userEvent.paste("12 34-56");
  expect(onComplete).toHaveBeenCalledWith("123456");
  expect(values()).toBe("123456");
});

it("moves focus forward on a digit and back on Backspace in an empty cell", async () => {
  renderOtp();
  await userEvent.click(cell(0));
  await userEvent.keyboard("1");
  expect(cell(0).value).toBe("1");
  expect(cell(1)).toHaveFocus();
  await userEvent.keyboard("{Backspace}");
  expect(cell(0)).toHaveFocus();
  expect(cell(0).value).toBe("1"); // moving back does not erase
  await userEvent.keyboard("{Backspace}");
  expect(cell(0).value).toBe("");
});

it("ignores non-digits", async () => {
  const onChange = vi.fn();
  renderOtp({ onChange });
  await userEvent.click(cell(0));
  await userEvent.keyboard("a");
  expect(onChange).not.toHaveBeenCalled();
  expect(values()).toBe("");
  expect(cell(0)).toHaveFocus();
});

it("clears and refocuses the first cell when it turns invalid", () => {
  const { rerenderOtp } = renderOtp({ initial: "123456" });
  const group = screen.getByRole("group", { name: copy.login.codeGroup });
  expect(group).not.toHaveAttribute("data-invalid");
  rerenderOtp({ invalid: true });
  expect(values()).toBe("");
  expect(cell(0)).toHaveFocus();
  expect(group).toHaveAttribute("data-invalid");
  expect(group).toHaveAttribute("data-anim", "shake");
  for (const i of [0, 1, 2, 3, 4, 5]) expect(cell(i)).toHaveAttribute("aria-invalid", "true");
});

it("treats a multi-digit change event as a paste (one-time-code autofill, Playwright fill)", () => {
  const onComplete = vi.fn();
  renderOtp({ onComplete });
  fireEvent.change(cell(0), { target: { value: "246810" } });
  expect(values()).toBe("246810");
  expect(onComplete).toHaveBeenCalledWith("246810");
});

it("overwrites from the cell when a fragment arrives in a filled code", () => {
  renderOtp({ initial: "123456" });
  fireEvent.change(cell(1), { target: { value: "99" } }); // two digits not containing the old "2"
  expect(values()).toBe("199456");
});

it("types over a filled cell and completes on the last digit", async () => {
  const onComplete = vi.fn();
  renderOtp({ onComplete, initial: "12345" });
  await userEvent.click(cell(1));
  await userEvent.keyboard("9");
  expect(values()).toBe("19345");
  expect(cell(2)).toHaveFocus();
  await userEvent.click(cell(5));
  await userEvent.keyboard("7");
  expect(onComplete).toHaveBeenCalledWith("193457");
});

it("moves with the arrow keys and keeps a typed digit contiguous", async () => {
  renderOtp({ initial: "12" });
  await userEvent.click(cell(1));
  await userEvent.keyboard("{ArrowLeft}");
  expect(cell(0)).toHaveFocus();
  await userEvent.keyboard("{ArrowRight}{ArrowRight}");
  expect(cell(2)).toHaveFocus();
  await userEvent.click(cell(4)); // past the first empty cell: the digit lands in cell 2
  await userEvent.keyboard("3");
  expect(values()).toBe("123");
  expect(cell(3)).toHaveFocus();
});

it("labels the group and the cells, numeric keypad, one-time-code on the first cell only", () => {
  renderOtp({ disabled: true });
  expect(screen.getByRole("group", { name: copy.login.codeGroup })).toBeInTheDocument();
  expect(cell(0)).toHaveAttribute("autocomplete", "one-time-code");
  expect(cell(1)).toHaveAttribute("autocomplete", "off");
  for (const i of [0, 1, 2, 3, 4, 5]) {
    expect(cell(i)).toHaveAttribute("inputmode", "numeric");
    expect(cell(i)).toBeDisabled();
  }
});
