import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { McpCard } from "@/components/status/McpCard";
import { copy } from "@/copy/ko";
import { CURATED_EMOJI, isMcpEmoji } from "@/lib/mcp-emoji";
import { item, mcpDetailFixture, meFixture } from "../../../tests/msw/fixtures";
import { server } from "../../../tests/msw/server";
import { renderWithProviders } from "../../../tests/render";
import { SettingsTab } from "./SettingsTab";

const ALL = Object.values(CURATED_EMOJI).flat();
const group = () => screen.getByRole("radiogroup", { name: copy.mcp.icon.choiceLabel });
const option = (name: string) => within(group()).getByRole("radio", { name });
const preview = () => within(screen.getByTestId("mcp-icon-preview")).getByTestId("mcp-icon");
const pasteBox = () => screen.getByLabelText(copy.mcp.icon.pasteLabel);
const saveButton = () => screen.getByRole("button", { name: copy.common.save });

function renderSettings(p: Parameters<typeof mcpDetailFixture>[0] = {}, me = meFixture("admin", "local")) {
  return renderWithProviders(<SettingsTab mcp={mcpDetailFixture({ id: 1, name: "calc", ...p })} />, { me });
}

function capturePut(answer: Parameters<typeof mcpDetailFixture>[0]): () => unknown {
  let body: unknown;
  server.use(
    http.put("/api/mcps/1", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json(mcpDetailFixture({ id: 1, name: "calc", ...answer }));
    }),
  );
  return () => body;
}

it("offers about 60 ready-made emoji in named groups, each a valid icon with its own Korean name", () => {
  expect(ALL.length).toBeGreaterThanOrEqual(55);
  expect(new Set(ALL).size).toBe(ALL.length);
  for (const e of ALL) {
    expect(isMcpEmoji(e), e).toBe(true);
    expect(copy.mcp.icon.names[e], e).toMatch(/\S/);
  }
  expect(Object.keys(copy.mcp.icon.names).sort()).toEqual([...ALL].sort());
  const names = [...Object.values(copy.mcp.icon.names), copy.mcp.icon.defaultIcon];
  expect(new Set(names).size).toBe(names.length); // options are found by name: no two alike
  expect(Object.keys(copy.mcp.icon.groups)).toEqual(Object.keys(CURATED_EMOJI));
});

it("is one keyboard radio group: one Tab stop, arrows select, Home/End jump; groups are labelled", async () => {
  renderSettings();
  const radios = within(group()).getAllByRole("radio");
  expect(radios).toHaveLength(ALL.length + 1);
  const def = option(copy.mcp.icon.defaultIcon);
  expect(def).toHaveAttribute("aria-checked", "true");
  expect(radios.filter((r) => r.tabIndex === 0)).toEqual([def]);
  expect(preview()).toHaveAttribute("data-icon", "default");
  for (const g of Object.values(copy.mcp.icon.groups)) expect(within(group()).getByRole("group", { name: g })).toBeInTheDocument();

  def.focus();
  await userEvent.keyboard("{ArrowRight}");
  const first = option(copy.mcp.icon.names[ALL[0]!]!);
  expect(first).toHaveFocus();
  expect(first).toHaveAttribute("aria-checked", "true");
  expect(preview()).toHaveAttribute("data-icon", ALL[0]);
  expect(preview()).toHaveTextContent(ALL[0]!);

  await userEvent.keyboard("{End}");
  expect(option(copy.mcp.icon.names[ALL.at(-1)!]!)).toHaveFocus();
  await userEvent.keyboard("{ArrowDown}"); // wraps to the start
  expect(def).toHaveFocus();
  expect(def).toHaveAttribute("aria-checked", "true");
  await userEvent.keyboard("{ArrowUp}{Home}");
  expect(def).toHaveAttribute("aria-checked", "true");
  expect(saveButton()).toHaveAttribute("aria-disabled", "true"); // back to the server's value

  await userEvent.tab(); // leaves the group in one step (roving tabindex)
  expect(group()).not.toContainElement(document.activeElement as HTMLElement);
});

it("PUT sends just the picked emoji, and the preview shows it beside the name", async () => {
  const body = capturePut({ icon: "🧮" });
  renderSettings();
  await userEvent.click(option(copy.mcp.icon.names["🧮"]!));
  expect(preview()).toHaveAttribute("data-icon", "🧮");
  expect(within(screen.getByTestId("mcp-icon-preview")).getByText("calc")).toBeInTheDocument();
  await userEvent.click(saveButton());
  await waitFor(() => expect(body()).toEqual({ icon: "🧮" }));
});

it("a pasted emoji is checked as it is typed and only a valid one is taken", async () => {
  const body = capturePut({ icon: "🦄" });
  renderSettings();
  await userEvent.type(pasteBox(), "ab");
  expect(screen.getByText(copy.mcp.icon.invalid)).toBeInTheDocument();
  expect(pasteBox()).toHaveAttribute("aria-invalid", "true");
  expect(preview()).toHaveAttribute("data-icon", "default");
  expect(saveButton()).toHaveAttribute("aria-disabled", "true");

  await userEvent.clear(pasteBox());
  await userEvent.click(pasteBox());
  await userEvent.paste("🦄");
  expect(screen.queryByText(copy.mcp.icon.invalid)).toBeNull();
  expect(preview()).toHaveAttribute("data-icon", "🦄");
  // the pasted emoji joins the group, checked
  expect(option(copy.mcp.icon.custom("🦄"))).toHaveAttribute("aria-checked", "true");
  await userEvent.click(saveButton());
  await waitFor(() => expect(body()).toEqual({ icon: "🦄" }));
});

it("a ZWJ sequence with a skin tone pastes as one emoji; two emoji do not", async () => {
  renderSettings();
  await userEvent.click(pasteBox());
  await userEvent.paste("🤖🤖");
  expect(screen.getByText(copy.mcp.icon.invalid)).toBeInTheDocument();
  await userEvent.clear(pasteBox());
  await userEvent.paste("🧑🏽‍💻");
  expect(screen.queryByText(copy.mcp.icon.invalid)).toBeNull();
  expect(preview()).toHaveAttribute("data-icon", "🧑🏽‍💻");
});

it("choosing the default icon again sends null", async () => {
  const body = capturePut({ icon: null });
  renderSettings({ icon: "⏰" });
  expect(option(copy.mcp.icon.names["⏰"]!)).toHaveAttribute("aria-checked", "true");
  expect(preview()).toHaveAttribute("data-icon", "⏰");
  await userEvent.click(option(copy.mcp.icon.defaultIcon));
  await userEvent.click(saveButton());
  await waitFor(() => expect(body()).toEqual({ icon: null }));
});

it("read-only without permission: the choice cannot change", async () => {
  renderSettings({}, meFixture(null, "local"));
  expect(group()).toHaveAttribute("aria-readonly", "true");
  expect(pasteBox()).toHaveAttribute("readonly");
  await userEvent.click(option(copy.mcp.icon.names["🤖"]!));
  expect(option(copy.mcp.icon.defaultIcon)).toHaveAttribute("aria-checked", "true");
});

describe("the board card's icon", () => {
  it("shows the emoji, hidden from assistive tech; the name stays the label", () => {
    render(<McpCard item={{ ...item(1, "HEALTHY", "calc"), icon: "🧮" }} receivedAt={0} />);
    const card = screen.getByTestId("mcp-card");
    const icon = within(card).getByTestId("mcp-icon");
    expect(icon).toHaveAttribute("data-icon", "🧮");
    expect(icon).toHaveTextContent("🧮");
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(card).toHaveAccessibleName("calc");
  });

  it("falls back to the default MCP icon for no icon or a value that is not one emoji", () => {
    const { rerender } = render(<McpCard item={item(1, "HEALTHY", "calc")} receivedAt={0} />);
    expect(screen.getByTestId("mcp-icon")).toHaveAttribute("data-icon", "default");
    expect(screen.getByTestId("mcp-icon").querySelector("svg")).not.toBeNull();
    rerender(<McpCard item={{ ...item(1, "HEALTHY", "calc"), icon: "<img src=x>" }} receivedAt={0} />);
    expect(screen.getByTestId("mcp-icon")).toHaveAttribute("data-icon", "default");
    expect(screen.getByTestId("mcp-icon")).not.toHaveTextContent("<img");
  });
});
