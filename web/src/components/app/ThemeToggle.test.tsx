import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { copy } from "@/copy/ko";
import { ThemeToggle } from "./ThemeToggle";

const root = document.documentElement;

afterEach(() => {
  localStorage.clear();
  delete root.dataset.theme;
});

it("starts in light, pins dark from the menu and labels the trigger with the current choice", async () => {
  const user = userEvent.setup();
  render(<ThemeToggle />);
  const trigger = screen.getByRole("button", { name: copy.common.theme.triggerLabel(copy.common.theme.light) });

  await user.click(trigger);
  const dark = await screen.findByRole("menuitemradio", { name: copy.common.theme.dark });
  expect(screen.getByRole("menuitemradio", { name: copy.common.theme.light })).toHaveAttribute("aria-checked", "true");
  await user.click(dark);

  expect(root.dataset.theme).toBe("dark");
  expect(localStorage.getItem("mcpmon.theme")).toBe("dark");
  expect(screen.getByRole("button", { name: copy.common.theme.triggerLabel(copy.common.theme.dark) })).toBeInTheDocument();
});

it("starts from the stored preference and can follow the system setting or go back to light", async () => {
  localStorage.setItem("mcpmon.theme", "dark");
  const user = userEvent.setup();
  render(<ThemeToggle />);

  await user.click(screen.getByRole("button", { name: copy.common.theme.triggerLabel(copy.common.theme.dark) }));
  await user.click(await screen.findByRole("menuitemradio", { name: copy.common.theme.system }));
  expect(root.dataset.theme).toBe("system");
  expect(localStorage.getItem("mcpmon.theme")).toBe("system");

  await user.click(screen.getByRole("button", { name: copy.common.theme.triggerLabel(copy.common.theme.system) }));
  await user.click(await screen.findByRole("menuitemradio", { name: copy.common.theme.light }));
  expect(root.dataset.theme).toBe("light");
  expect(localStorage.getItem("mcpmon.theme")).toBeNull(); // the default is not stored
});
