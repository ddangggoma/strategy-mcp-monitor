import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { copy } from "@/copy/ko";
import { NoticeDialog } from "./NoticeDialog";

const content = { title: "안내", body: "본문", button_text: "확인" };

it("standalone ignores Escape and acknowledges only with the button", async () => {
  const onAck = vi.fn();
  render(<NoticeDialog content={content} mode="standalone" onAcknowledge={onAck} />);
  const closed = vi.fn();
  screen.getByRole("dialog").addEventListener("close", closed);
  await userEvent.keyboard("{Escape}");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(closed).not.toHaveBeenCalled(); // refused, not closed and reopened
  expect(onAck).not.toHaveBeenCalled();
  // a cancel request that reaches the dialog some other way is refused too
  const cancel = new Event("cancel", { cancelable: true });
  screen.getByRole("dialog").dispatchEvent(cancel);
  expect(cancel.defaultPrevented).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "확인" }));
  expect(onAck).toHaveBeenCalledTimes(1);
});

it("standalone is a modal dialog named by its title and described by its body", () => {
  render(<NoticeDialog content={{ ...content, body: "**기록** 안내" }} mode="standalone" />);
  const dialog = screen.getByRole("dialog", { name: "안내" });
  expect(dialog.tagName).toBe("DIALOG");
  expect(dialog).toHaveAttribute("open");
  expect(dialog).toHaveAccessibleDescription("기록 안내");
  expect(within(dialog).getByRole("heading", { level: 1, name: "안내" })).toBeInTheDocument();
  // the button gets the focus a modal dialog gives its first control
  expect(within(dialog).getByRole("button", { name: "확인" })).toHaveFocus();
});

it("standalone opens again if something closes it before the button is pressed", () => {
  render(<NoticeDialog content={content} mode="standalone" />);
  const dialog = screen.getByRole("dialog") as HTMLDialogElement;
  // a close request the cancel handler could not stop (Chromium lets a repeated Escape through)
  fireEvent(dialog, new Event("cancel", { cancelable: false }));
  dialog.close();
  expect(dialog).toHaveAttribute("open");
});

it("preview renders the same markup without a modal", () => {
  render(<NoticeDialog content={{ title: "안내", body: "**굵게** 본문\n\n- 항목", button_text: "확인" }} mode="preview" />);
  expect(screen.queryByRole("dialog")).toBeNull();
  const group = screen.getByRole("group", { name: copy.notice.previewLabel });
  expect(within(group).getByRole("heading", { level: 2, name: "안내" })).toBeInTheDocument();
  expect(group.querySelector("strong")).toHaveTextContent("굵게");
  expect(within(group).getByRole("listitem")).toHaveTextContent("항목");
  // the same classes as the real dialog: one stylesheet draws both
  expect(group.querySelector(".notice-panel")).not.toBeNull();
  expect(group.querySelector(".notice-body")).not.toBeNull();
  expect(within(group).getByRole("button", { name: "확인" })).toHaveClass("notice-button");
});

it("the preview button does nothing", async () => {
  const onAck = vi.fn();
  render(<NoticeDialog content={content} mode="preview" onAcknowledge={onAck} />);
  const button = screen.getByRole("button", { name: "확인" });
  expect(button).toHaveAttribute("aria-disabled", "true");
  expect(button).toHaveAttribute("tabindex", "-1");
  await userEvent.click(button);
  expect(onAck).not.toHaveBeenCalled();
});

it("renders script-like text as text", () => {
  const body = "<img src=x onerror=alert(1)>\n\n<script>alert(1)</script>";
  const { container } = render(<NoticeDialog content={{ title: "<b>제목</b>", body, button_text: "<i>확인</i>" }} mode="standalone" />);
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("b")).toBeNull();
  expect(container.querySelector("i")).toBeNull();
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "<b>제목</b>" })).toBeInTheDocument();
});
