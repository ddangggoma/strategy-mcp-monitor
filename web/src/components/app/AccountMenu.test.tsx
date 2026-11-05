import { render, screen } from "@testing-library/react";
import { AccountMenu } from "./AccountMenu";

// WCAG 2.5.3 Label in Name (axe label-content-name-mismatch, found by the E2E axe run): the visible
// name must appear as whole words in the accessible name, best at its start, so "click <name>"
// works for speech-input users.
it("the account button's accessible name starts with the visible user name", () => {
  render(<AccountMenu user={{ id: 1, email: "kim@example.com", name: "김 관리", role: "admin" }} onLogout={async () => {}} />);
  const button = screen.getByRole("button");
  const visible = button.textContent?.trim() ?? "";
  expect(visible).toBe("김 관리");
  const name = button.getAttribute("aria-label") ?? "";
  expect(name.startsWith(`${visible} `)).toBe(true);
});
