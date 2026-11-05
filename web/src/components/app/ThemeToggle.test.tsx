import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { copy } from "@/copy/ko";
import { ThemeToggle } from "./ThemeToggle";

const root = document.documentElement;

afterEach(() => {
  localStorage.clear();
  delete root.dataset.theme;
});

it("pins a theme from the menu and labels the trigger with the current choice", async () => {
  const user = userEvent.setup();
  render(<ThemeToggle />);
  const trigger = screen.getByRole("button", { name: copy.common.theme.triggerLabel(copy.common.theme.system) });

  await user.click(trigger);
  const light = await screen.findByRole("menuitemradio", { name: copy.common.theme.light });
  expect(screen.getByRole("menuitemradio", { name: copy.common.theme.system })).toHaveAttribute("aria-checked", "true");
  await user.click(light);

  expect(root.dataset.theme).toBe("light");
  expect(localStorage.getItem("mcpmon.theme")).toBe("light");
  expect(screen.getByRole("button", { name: copy.common.theme.triggerLabel(copy.common.theme.light) })).toBeInTheDocument();
});

it("starts from the stored preference and can return to the system setting", async () => {
  localStorage.setItem("mcpmon.theme", "dark");
  const user = userEvent.setup();
  render(<ThemeToggle />);

  await user.click(screen.getByRole("button", { name: copy.common.theme.triggerLabel(copy.common.theme.dark) }));
  await user.click(await screen.findByRole("menuitemradio", { name: copy.common.theme.system }));

  expect(root.dataset.theme).toBeUndefined();
  expect(localStorage.getItem("mcpmon.theme")).toBeNull();
});
