import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

describe("the uploaded image (the MCP's logo)", () => {
  const PNG_BYTES = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3]);
  const URL_1 = "/api/mcps/1/icon-image?v=0123456789ab";
  const fileInput = () => screen.getByTestId("mcp-icon-file") as HTMLInputElement;
  const uploadButton = (name: string = copy.mcp.icon.imageUpload) => screen.getByRole("button", { name });

  function capturePutImage(answer: { status?: number; error?: string } = {}) {
    const seen: { type: string | null; csrf: string | null; bytes: number[] }[] = [];
    server.use(
      http.put("/api/mcps/1/icon-image", async ({ request }) => {
        seen.push({
          type: request.headers.get("Content-Type"),
          csrf: request.headers.get("X-CSRF-Token"),
          bytes: [...new Uint8Array(await request.arrayBuffer())],
        });
        if (answer.error) return HttpResponse.json({ error: answer.error }, { status: answer.status ?? 422 });
        return HttpResponse.json(mcpDetailFixture({ id: 1, name: "calc", icon: "🧮", icon_image: URL_1 }));
      }),
    );
    return seen;
  }

  it("uploads at once with its type and the CSRF token; the preview and the header then show the image", async () => {
    const seen = capturePutImage();
    server.use(http.get("/api/mcps/1", () => HttpResponse.json(mcpDetailFixture({ id: 1, name: "calc", icon: "🧮" }))));
    renderWithProviders(null, { route: "/admin/mcps/1", me: meFixture("admin", "local") });
    await screen.findByTestId("mcp-icon-preview", {}, { timeout: 5000 });
    expect(preview()).toHaveAttribute("data-icon", "🧮");
    expect(screen.queryByRole("button", { name: copy.mcp.icon.imageRemove })).toBeNull();

    await userEvent.upload(fileInput(), new File([PNG_BYTES], "logo.png", { type: "image/png" }));
    expect((await screen.findAllByText(copy.common.saved)).length).toBeGreaterThan(0);
    expect(seen).toHaveLength(1);
    expect(seen[0]!.type).toBe("image/png");
    expect(seen[0]!.csrf).toBe("csrf-1");
    expect(seen[0]!.bytes).toEqual([...PNG_BYTES]);
    // the stored detail now carries the image: it takes precedence over the emoji
    await waitFor(() => expect(preview()).toHaveAttribute("data-icon", "image"));
    const img = preview().querySelector("img")!;
    expect(img).toHaveAttribute("src", URL_1);
    expect(img).toHaveAttribute("alt", "");
    const drawn = screen.getAllByTestId("mcp-icon").filter((i) => i.dataset.icon === "image");
    expect(drawn.length).toBeGreaterThanOrEqual(2); // the detail header too
    expect(uploadButton()).toBeInTheDocument();
    // the settings form is untouched: nothing to save
    expect(saveButton()).toHaveAttribute("aria-disabled", "true");
  });

  it("removes the image at once", async () => {
    let deleted = 0;
    server.use(
      http.delete("/api/mcps/1/icon-image", () => {
        deleted += 1;
        return HttpResponse.json(mcpDetailFixture({ id: 1, name: "calc", icon: "🧮" }));
      }),
    );
    renderSettings({ icon: "🧮", icon_image: URL_1 });
    expect(preview()).toHaveAttribute("data-icon", "image");
    await userEvent.click(screen.getByRole("button", { name: copy.mcp.icon.imageRemove }));
    await waitFor(() => expect(deleted).toBe(1));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("checks the type and the size before sending anything", async () => {
    const seen = capturePutImage();
    const user = userEvent.setup({ applyAccept: false });
    renderSettings();
    await user.upload(fileInput(), new File(["hello"], "notes.txt", { type: "text/plain" }));
    expect(screen.getByRole("alert")).toHaveTextContent(copy.mcp.icon.imageWrongType);
    await user.upload(fileInput(), new File([new Uint8Array(256 * 1024 + 1)], "big.png", { type: "image/png" }));
    expect(screen.getByRole("alert")).toHaveTextContent(copy.mcp.icon.imageTooLarge);
    expect(uploadButton()).toHaveAccessibleDescription(`${copy.mcp.icon.imageHint} ${copy.mcp.icon.imageTooLarge}`);
    expect(seen).toHaveLength(0);
    // exactly 256 KiB passes
    await user.upload(fileInput(), new File([new Uint8Array(256 * 1024)], "ok.png", { type: "image/png" }));
    await waitFor(() => expect(seen).toHaveLength(1));
    expect(screen.queryByText(copy.mcp.icon.imageTooLarge)).toBeNull();
  });

  it("a file the browser gives no type is typed by its extension; a known alias is normalized", async () => {
    const seen = capturePutImage();
    renderSettings();
    await userEvent.upload(fileInput(), new File([new Uint8Array([0, 0, 1, 0])], "favicon.ico", { type: "" }));
    await waitFor(() => expect(seen).toHaveLength(1));
    expect(seen[0]!.type).toBe("image/x-icon");
    await userEvent.upload(fileInput(), new File([new Uint8Array([0, 0, 1, 0])], "app.ico", { type: "image/vnd.microsoft.icon" }));
    await waitFor(() => expect(seen).toHaveLength(2));
    expect(seen[1]!.type).toBe("image/x-icon");
  });

  it("says why the server refused it (422 / 413)", async () => {
    capturePutImage({ error: "validation" });
    renderSettings();
    await userEvent.upload(fileInput(), new File([PNG_BYTES], "logo.png", { type: "image/png" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.mcp.icon.imageRejected);
    capturePutImage({ status: 413, error: "body_too_large" });
    await userEvent.upload(fileInput(), new File([PNG_BYTES], "logo.png", { type: "image/png" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(copy.mcp.icon.imageTooLarge));
  });

  it("keyboard: the file buttons are their own Tab stops beside the emoji group, which keeps its radios", async () => {
    renderSettings({ icon_image: URL_1 });
    const upload = uploadButton();
    expect(screen.getByRole("group", { name: copy.mcp.icon.image })).toContainElement(upload);
    expect(within(group()).getAllByRole("radio")).toHaveLength(ALL.length + 1);
    expect(fileInput()).toHaveAttribute("tabindex", "-1");
    upload.focus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: copy.mcp.icon.imageRemove })).toHaveFocus();
  });

  it("without permission the buttons stay focusable, say why and do nothing", async () => {
    const seen = capturePutImage();
    renderSettings({ icon_image: URL_1 }, meFixture(null, "local"));
    const upload = uploadButton();
    const remove = screen.getByRole("button", { name: copy.mcp.icon.imageRemove });
    for (const b of [upload, remove]) {
      expect(b).toHaveAttribute("aria-disabled", "true");
      expect(b).toHaveAccessibleDescription(expect.stringContaining(copy.deny.login));
    }
    const click = vi.spyOn(fileInput(), "click");
    await userEvent.click(upload);
    await userEvent.click(remove);
    expect(click).not.toHaveBeenCalled();
    expect(seen).toHaveLength(0);
  });
});

describe("McpIcon: image, then emoji, then the default icon", () => {
  it("draws the image (decorative, empty alt) and falls back when it fails to load", () => {
    const at = (p: Partial<ReturnType<typeof item>>) => ({ ...item(1, "HEALTHY", "calc"), ...p });
    const { rerender } = render(<McpCard item={at({ icon: "🧮", icon_image: "/api/mcps/1/icon-image?v=aaaaaaaaaaaa" })} receivedAt={0} />);
    const icon = screen.getByTestId("mcp-icon");
    expect(icon).toHaveAttribute("data-icon", "image");
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(icon.querySelector("img")).toHaveAttribute("alt", "");
    expect(screen.getByTestId("mcp-card")).toHaveAccessibleName("calc");
    fireEvent.error(icon.querySelector("img")!);
    expect(screen.getByTestId("mcp-icon")).toHaveAttribute("data-icon", "🧮");
    // a new version is tried again
    rerender(<McpCard item={at({ icon: "🧮", icon_image: "/api/mcps/1/icon-image?v=bbbbbbbbbbbb" })} receivedAt={0} />);
    expect(screen.getByTestId("mcp-icon")).toHaveAttribute("data-icon", "image");
    // a failed image without an emoji: the default icon
    rerender(<McpCard item={at({ icon_image: "/x.png" })} receivedAt={0} />);
    fireEvent.error(screen.getByTestId("mcp-icon").querySelector("img")!);
    expect(screen.getByTestId("mcp-icon")).toHaveAttribute("data-icon", "default");
  });
});
