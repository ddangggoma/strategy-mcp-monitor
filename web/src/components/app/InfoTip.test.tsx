import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { copy } from "@/copy/ko";
import { InfoTip, helpText } from "./InfoTip";

const TEXT = "조치 대기 시간이 끝나면 자동 조치를 해요.";
const name = copy.help.label("조치 대기 시간");

function renderTip(content: Parameters<typeof InfoTip>[0]["content"] = TEXT) {
  return render(
    <>
      <InfoTip label="조치 대기 시간" content={content} />
      <button type="button">다음</button>
    </>,
  );
}

/** The element an id list attribute points at (the first id). */
function target(el: HTMLElement, attr: string): HTMLElement | null {
  const id = el.getAttribute(attr)?.split(" ")[0];
  return id ? document.getElementById(id) : null;
}

it("is a button named after its label and described by the help while closed", () => {
  renderTip();
  const button = screen.getByRole("button", { name });
  expect(button).toHaveAttribute("type", "button");
  expect(button).toHaveAttribute("aria-expanded", "false");
  expect(button).not.toHaveAttribute("aria-controls");
  expect(button).toHaveAccessibleDescription(TEXT);
  expect(screen.queryByRole("tooltip")).toBeNull();
});

it("opens on keyboard focus, points at the open tip, and closes on Escape", async () => {
  renderTip();
  const button = screen.getByRole("button", { name });
  await userEvent.tab();
  expect(button).toHaveFocus();
  const tip = await screen.findByRole("tooltip");
  expect(tip).toHaveTextContent(TEXT);
  expect(button).toHaveAttribute("aria-expanded", "true");
  expect(target(button, "aria-controls")).toBe(tip);
  expect(target(button, "aria-describedby")).toBe(tip);
  expect(button).toHaveAccessibleDescription(TEXT);

  await userEvent.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
  expect(button).toHaveAttribute("aria-expanded", "false");
  expect(button).toHaveFocus(); // focus never moves into or away from the tip
});

it("closes when focus moves on", async () => {
  renderTip();
  await userEvent.tab();
  expect(await screen.findByRole("tooltip")).toBeInTheDocument();
  await userEvent.tab();
  expect(screen.getByRole("button", { name: "다음" })).toHaveFocus();
  await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
});

it("opens when the mouse rests on it and closes when it leaves", async () => {
  renderTip();
  const button = screen.getByRole("button", { name });
  await userEvent.hover(button);
  expect(await screen.findByRole("tooltip")).toHaveTextContent(TEXT);
  expect(button).not.toHaveFocus(); // hovering does not take the focus
  await userEvent.unhover(button);
  await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
});

it("stays open after a click (WebView2, touch) until clicked again", async () => {
  renderTip();
  const button = screen.getByRole("button", { name });
  await userEvent.click(button);
  expect(await screen.findByRole("tooltip")).toBeInTheDocument();
  expect(button).toHaveAttribute("aria-expanded", "true");
  await userEvent.unhover(button);
  await new Promise((r) => setTimeout(r, 300));
  expect(screen.getByRole("tooltip")).toBeInTheDocument(); // pinned
  await userEvent.click(button);
  await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
});

it("toggles with Enter after a keyboard focus", async () => {
  renderTip();
  await userEvent.tab();
  expect(await screen.findByRole("tooltip")).toBeInTheDocument();
  await userEvent.keyboard("{Enter}"); // pins the tip the focus opened
  expect(screen.getByRole("tooltip")).toBeInTheDocument();
  await userEvent.keyboard("{Enter}");
  await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
});

it("closes on a click elsewhere", async () => {
  renderTip();
  await userEvent.click(screen.getByRole("button", { name }));
  expect(await screen.findByRole("tooltip")).toBeInTheDocument();
  await userEvent.click(document.body);
  await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
});

it("never submits the form it sits in", async () => {
  const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
  render(
    <form onSubmit={onSubmit}>
      <label htmlFor="f">조치 대기 시간</label>
      <InfoTip label="조치 대기 시간" content={TEXT} />
      <input id="f" />
    </form>,
  );
  await userEvent.click(screen.getByRole("button", { name }));
  expect(onSubmit).not.toHaveBeenCalled();
  // beside the label, not inside it: the field keeps the label alone as its name
  expect(screen.getByRole("textbox")).toHaveAccessibleName("조치 대기 시간");
});

it("shows a lead and a list of terms, and reads them as one description", async () => {
  const content = { lead: "상태예요.", items: [["정상", "문제가 없어요."], ["실패", "멈췄어요."]] } as const;
  renderTip(content);
  const button = screen.getByRole("button", { name });
  expect(button).toHaveAccessibleDescription("상태예요. 정상: 문제가 없어요. 실패: 멈췄어요.");
  await userEvent.click(button);
  const tip = await screen.findByRole("tooltip");
  expect(tip.querySelectorAll("dt")).toHaveLength(2);
  expect(tip).toHaveTextContent("정상");
  expect(tip).toHaveTextContent("멈췄어요.");
});

it("flattens help to text", () => {
  expect(helpText("한 문장.")).toBe("한 문장.");
  expect(helpText({ items: [["가", "나."]] })).toBe("가: 나.");
});

it("keeps the help out of the text of what it sits in", () => {
  render(
    <table>
      <thead>
        <tr>
          <th aria-label="지연">
            지연
            <InfoTip label="지연" content={TEXT} />
          </th>
        </tr>
      </thead>
    </table>,
  );
  expect(screen.getByRole("columnheader")).toHaveTextContent(/^지연$/);
  expect(screen.getByRole("columnheader", { name: "지연" })).toBeInTheDocument();
});
