import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { copy } from "@/copy/ko";
import { formatKst } from "@/lib/time";
import { item, NOW, rdpSession } from "../../../tests/msw/fixtures";
import { WithReason } from "../app/WithReason";
import { ConnectionBanner } from "./ConnectionBanner";
import { CountdownBar } from "./CountdownBar";
import { McpCard } from "./McpCard";
import { RollingNumber } from "./RollingNumber";
import { SessionCard } from "./SessionCard";
import { Sparkline } from "./Sparkline";
import { StatusBadge } from "./StatusBadge";
import { StreamIndicator } from "./StreamIndicator";
import { UptimeMeter } from "./UptimeMeter";

afterEach(() => {
  vi.useRealTimers();
});

describe("CountdownBar", () => {
  it("subtracts elapsed time since receipt (no clock skew)", () => {
    vi.useFakeTimers();
    const t0 = performance.now();
    render(<CountdownBar inSec={20} totalSec={30} receivedAt={t0} />);
    act(() => vi.advanceTimersByTime(5000));
    expect(screen.getByRole("timer")).toHaveTextContent("15");
    expect(screen.getByTestId("gauge").style.getPropertyValue("--gauge-from")).toBe(String(20 / 30));
  });

  it("animates over the remaining seconds, is not announced every second, and stops at 0", () => {
    vi.useFakeTimers();
    const t0 = performance.now();
    render(<CountdownBar inSec={3} totalSec={null} receivedAt={t0 - 1000} />);
    const gauge = screen.getByTestId("gauge");
    // totalSec null → inSec is the full length; one second already passed before mount
    expect(gauge.style.getPropertyValue("--gauge-from")).toBe(String(2 / 3));
    expect(gauge.style.animationDuration).toBe("2000ms");
    expect(gauge).toHaveAttribute("data-anim");
    expect(screen.getByRole("timer")).toHaveAttribute("aria-live", "off");
    expect(screen.getByRole("timer")).toHaveTextContent(copy.board.actionIn(2));
    act(() => vi.advanceTimersByTime(10_000));
    expect(screen.getByRole("timer")).toHaveTextContent(copy.board.actionIn(0));
  });
});

describe("StatusBadge", () => {
  it("has text and icon, not color alone", () => {
    const { container } = render(<StatusBadge state="FAILED" />);
    expect(screen.getByText("실패")).toBeInTheDocument();
    const badge = container.querySelector("[data-state]");
    expect(badge).toHaveAttribute("data-state", "FAILED");
    expect(badge?.querySelector("svg[aria-hidden='true']")).not.toBeNull();
  });

  it("shows the issue next to the state when given", () => {
    render(<StatusBadge state="SUSPECT" issue="UNRESPONSIVE" size="lg" />);
    expect(screen.getByText("이상 감지")).toBeInTheDocument();
    expect(screen.getByText("응답 없음")).toBeInTheDocument();
  });

  it("keeps HEALTHY quiet (no fill) and fills every problem state", () => {
    const { rerender } = render(<StatusBadge state="HEALTHY" />);
    const healthy = screen.getByText("정상");
    expect(healthy.className).not.toMatch(/\bbg-/);
    expect(healthy.querySelector("svg")).not.toBeNull(); // still icon + word (WCAG 1.4.1)
    for (const [state, word] of [["FAILED", "실패"], ["SUSPECT", "이상 감지"], ["ACTION", "조치 중"], ["RECOVERING", "복구 중"]] as const) {
      rerender(<StatusBadge state={state} />);
      expect(screen.getByText(word).className).toContain(`bg-state-${state.toLowerCase()}-soft`);
    }
  });

  it("crossfades to the new state", async () => {
    const { rerender } = render(<StatusBadge state="HEALTHY" />);
    rerender(<StatusBadge state="FAILED" />);
    expect(await screen.findByText("실패")).toBeInTheDocument();
    // the old badge fades out and leaves the DOM (exits do not pile up)
    await waitFor(() => expect(screen.queryByText("정상")).toBeNull());
  });
});

describe("Sparkline", () => {
  it("breaks the line at null points", () => {
    const { container } = render(<Sparkline points={[1, 2, null, 3]} label="calc" />);
    const line = container.querySelector("path[data-part='line']");
    expect(line?.getAttribute("d")?.match(/M/g)).toHaveLength(2);
    // the missing stretch is marked on the floor so a gap never reads as "fine"
    const gaps = container.querySelector("path[data-part='gap']");
    expect(gaps?.getAttribute("d")?.match(/M/g)).toHaveLength(1);
  });

  it("summarizes the recent average and maximum for screen readers", () => {
    render(<Sparkline points={[10, null, 20, 30]} label="calc 최근 지연 추이" />);
    expect(screen.getByRole("img")).toHaveAccessibleName("calc 최근 지연 추이: 평균 20ms, 최대 30ms");
  });

  it("says when there is no value at all", () => {
    render(<Sparkline points={[null, null]} label="calc" />);
    expect(screen.getByRole("img")).toHaveAccessibleName(`calc: ${copy.board.noData}`);
  });
});

describe("RollingNumber", () => {
  it("exposes the real value to screen readers", () => {
    render(<RollingNumber value={42} unit="ms" />);
    expect(screen.getByText("42 ms")).toHaveClass("sr-only");
  });

  it("rounds, rolls one column per digit and hides the columns from assistive tech", () => {
    const { container, rerender } = render(<RollingNumber value={41.6} unit="ms" />);
    expect(screen.getByText("42 ms")).toHaveClass("sr-only");
    const columns = container.querySelectorAll("[data-digit]");
    expect([...columns].map((c) => c.getAttribute("data-digit"))).toEqual(["4", "2"]);
    expect(columns[0]?.closest("[aria-hidden='true']")).not.toBeNull();
    expect((columns[1] as HTMLElement).style.transform).toBe("translateY(-20%)");
    rerender(<RollingNumber value={107} unit="ms" />);
    expect(screen.getByText("107 ms")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-digit]")).toHaveLength(3);
  });

  it("shows a dash for no value", () => {
    render(<RollingNumber value={null} unit="ms" />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText(copy.board.noData)).toHaveClass("sr-only");
  });
});

describe("UptimeMeter", () => {
  it("shows the 24 h ratio as a percent with one decimal", () => {
    const { rerender } = render(<UptimeMeter value={0.925} />);
    expect(screen.getByText("92.5%")).toBeInTheDocument();
    rerender(<UptimeMeter value={1} />);
    expect(screen.getByText("100.0%")).toBeInTheDocument();
    // the ratio moves with every check: masked in the visual baselines (F32)
    expect(screen.getByText("100.0%")).toHaveAttribute("data-volatile");
  });

  it("says 기록 없음 without checks", () => {
    render(<UptimeMeter value={null} />);
    expect(screen.getByText("기록 없음")).toBeInTheDocument();
  });
});

describe("WithReason", () => {
  it("keeps focus and explains", async () => {
    render(
      <WithReason reason="local_only">
        <button>편집</button>
      </WithReason>,
    );
    const b = screen.getByRole("button", { name: "편집" });
    expect(b).toHaveAttribute("aria-disabled", "true");
    await userEvent.tab();
    expect(b).toHaveFocus();
    expect(await screen.findByRole("tooltip")).toHaveTextContent("127.0.0.1:8700");
  });

  it("ignores clicks and Enter, and describes the reason without the tooltip open", async () => {
    const onClick = vi.fn();
    render(
      <WithReason reason="admin_only">
        <button onClick={onClick}>삭제</button>
      </WithReason>,
    );
    const b = screen.getByRole("button", { name: "삭제" });
    expect(b).toHaveAccessibleDescription(copy.deny.admin_only);
    await userEvent.click(b);
    b.focus();
    await userEvent.keyboard("{Enter} ");
    expect(onClick).not.toHaveBeenCalled();
  });

  it("passes the child through untouched without a reason", async () => {
    const onClick = vi.fn();
    render(
      <WithReason reason={null}>
        <button onClick={onClick}>저장</button>
      </WithReason>,
    );
    const b = screen.getByRole("button", { name: "저장" });
    expect(b).not.toHaveAttribute("aria-disabled");
    expect(b).not.toHaveAttribute("aria-describedby");
    await userEvent.click(b);
    expect(onClick).toHaveBeenCalledTimes(1);
    b.focus();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole("tooltip")).toBeNull(); // nothing to explain, no label: no tooltip
  });

  it("keeps the same focused control when a reason comes and goes (no remount, focus not dropped)", async () => {
    const { rerender } = render(
      <WithReason reason={null}>
        <button>저장</button>
      </WithReason>,
    );
    const b = screen.getByRole("button", { name: "저장" });
    b.focus();
    rerender(
      <WithReason reason="unchanged">
        <button>저장</button>
      </WithReason>,
    );
    expect(screen.getByRole("button", { name: "저장" })).toBe(b);
    expect(b).toHaveFocus();
    // read once, even with the tooltip open (focus opened it): the open tooltip adds nothing
    expect(b).toHaveAccessibleDescription(new RegExp(`^${copy.deny.unchanged}\\s*$`));
    rerender(
      <WithReason reason={null}>
        <button>저장</button>
      </WithReason>,
    );
    expect(screen.getByRole("button", { name: "저장" })).toBe(b);
    expect(b).toHaveFocus();
    expect(b).not.toHaveAttribute("aria-disabled");
  });

  it("names an icon-only control in its tooltip without a reason", async () => {
    render(
      <WithReason reason={null} label="시작">
        <button aria-label="시작">▶</button>
      </WithReason>,
    );
    await userEvent.tab();
    expect(await screen.findByRole("tooltip")).toHaveTextContent("시작");
    expect(screen.getByRole("button", { name: "시작" })).toHaveAccessibleDescription(""); // the name is not read again
  });
});

describe("ConnectionBanner", () => {
  it("is neutral without a sessions field", () => {
    const { container } = render(<ConnectionBanner sessions={undefined} />);
    expect(screen.getByText(copy.board.sessionsNotReady)).toBeInTheDocument();
    expect(container.querySelector("[data-anim]")).toBeNull();
  });

  it("shows 접속자 없음 for an empty list, without a pulse", () => {
    const { container } = render(<ConnectionBanner sessions={[]} />);
    expect(screen.getByText(copy.board.noSession)).toBeInTheDocument();
    expect(container.querySelector("[data-anim]")).toBeNull();
  });

  it("pulses while someone is connected", () => {
    const { container } = render(<ConnectionBanner sessions={[rdpSession()]} />);
    expect(screen.getByText(copy.board.connected)).toBeInTheDocument();
    expect(container.querySelector("[data-anim='pulse']")).not.toBeNull();
  });
});

describe("SessionCard", () => {
  it("shows every §6.2 field, the full IP and a dash for missing values", () => {
    render(<SessionCard session={rdpSession({ client_ip: "10.0.3.21", reverse_dns: null, idle_sec: 125, notice_acknowledged: false })} />);
    const card = screen.getByRole("article", { name: "hong" });
    expect(within(card).getByText("hong")).toBeInTheDocument();
    expect(within(card).getByText("CORP")).toBeInTheDocument();
    expect(within(card).getByText("HONG-PC")).toBeInTheDocument();
    expect(within(card).getByText("10.0.3.21")).toBeInTheDocument();
    expect(within(card).getByText(copy.sessions.state.active)).toBeInTheDocument();
    expect(within(card).getByText(copy.sessions.resolution(1920, 1080, 32))).toBeInTheDocument();
    expect(within(card).getByText(copy.sessions.idle(2))).toBeInTheDocument();
    expect(within(card).getByText(copy.sessions.noticePending)).toBeInTheDocument();
    expect(within(card).getByText(formatKst(NOW))).toBeInTheDocument();
    const labels = Object.values(copy.sessions.fields);
    for (const label of labels) expect(within(card).getByText(label)).toBeInTheDocument();
    // reverse DNS is null
    expect(within(card).getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });

  it("SessionCard shows first-seen badges, lock state, idle minutes and a pending notice", () => {
    render(<SessionCard session={rdpSession({ first_seen_ip: true, first_seen_device: false, state: "locked", notice_acknowledged: false, idle_sec: 125, resolution: "1920x1080@32" })} />);
    expect(screen.getByText(copy.sessions.firstSeenIp)).toBeInTheDocument();
    expect(screen.queryByText(copy.sessions.firstSeenDevice)).toBeNull();
    expect(screen.getByText(copy.sessions.state.locked)).toBeInTheDocument();
    expect(screen.getByText(copy.sessions.idle(2))).toBeInTheDocument();
    expect(screen.getByText(copy.sessions.noticePending)).toBeInTheDocument();
    expect(screen.getByText(copy.sessions.resolution(1920, 1080, 32))).toBeInTheDocument();
  });

  it.each([[true, "noticeAcked"], [null, "noticeUnknown"]] as const)("SessionCard notice state %s", (value, key) => {
    render(<SessionCard session={rdpSession({ notice_acknowledged: value })} />);
    expect(screen.getByText(copy.sessions[key])).toBeInTheDocument();
  });

  it("marks badges and the pending notice with an icon as well as words", () => {
    render(<SessionCard session={rdpSession({ first_seen_ip: true, first_seen_device: true, notice_acknowledged: false })} />);
    for (const word of [copy.sessions.firstSeenIp, copy.sessions.firstSeenDevice, copy.sessions.noticePending]) {
      const el = screen.getByText(word);
      expect(el.querySelector("svg[aria-hidden='true']"), word).not.toBeNull();
    }
    expect(screen.getByText(copy.sessions.noticePending)).toHaveClass("text-state-suspect-fg");
    // the badges belong to the card's name area, readable in order after the user
    const card = screen.getByRole("article", { name: "hong" });
    expect(card.textContent?.indexOf(copy.sessions.firstSeenIp)).toBeGreaterThan(card.textContent?.indexOf("hong") ?? -1);
  });

  it("shows idle time in whole minutes from one minute, a dash below that", () => {
    const idleOf = (idle_sec: number | null) => {
      const { unmount } = render(<SessionCard session={rdpSession({ idle_sec })} />);
      const text = screen.getByTestId("session-idle").textContent;
      unmount();
      return text;
    };
    expect(idleOf(null)).toBe("—");
    expect(idleOf(0)).toBe("—");
    expect(idleOf(59)).toBe("—");
    expect(idleOf(60)).toBe(copy.sessions.idle(1));
    expect(idleOf(119)).toBe(copy.sessions.idle(1));
    expect(idleOf(3_725)).toBe(copy.sessions.idle(62));
    expect(copy.sessions.idle(62)).toBe("1시간 2분");
    expect(copy.sessions.idle(120)).toBe("2시간");
  });

  it("does not count idle time on the client (the server sends it when the minute changes, V10)", () => {
    vi.useFakeTimers({ now: new Date(NOW).getTime() });
    render(<SessionCard session={rdpSession({ idle_sec: 125 })} />);
    act(() => vi.advanceTimersByTime(120_000));
    expect(screen.getByTestId("session-idle")).toHaveTextContent(copy.sessions.idle(2));
  });

  it("reads the resolution with or without the colour depth, and keeps an unknown form as it is", () => {
    const resOf = (resolution: string | null) => {
      const { unmount } = render(<SessionCard session={rdpSession({ resolution })} />);
      const text = screen.getByTestId("session-resolution").textContent;
      unmount();
      return text;
    };
    expect(resOf("1920x1080@32")).toBe(copy.sessions.resolution(1920, 1080, 32));
    expect(resOf("1280x720")).toBe(copy.sessions.resolution(1280, 720, null));
    expect(resOf("odd")).toBe("odd");
    expect(resOf(null)).toBe("—");
    expect(copy.sessions.resolution(1920, 1080, 32)).toBe("1920×1080, 32비트");
    expect(copy.sessions.resolution(1280, 720, null)).toBe("1280×720");
  });

  it.each(["active", "locked"] as const)("names the %s state in words", (state) => {
    render(<SessionCard session={rdpSession({ state })} />);
    expect(screen.getByText(copy.sessions.state[state])).toBeInTheDocument();
  });

  it("counts the connected time every second", () => {
    vi.useFakeTimers({ now: new Date(NOW).getTime() + 65_000 });
    render(<SessionCard session={rdpSession()} />);
    const elapsed = screen.getByTestId("session-elapsed");
    expect(elapsed).toHaveTextContent("1분 5초");
    act(() => vi.advanceTimersByTime(2000));
    expect(elapsed).toHaveTextContent("1분 7초");
  });
});

describe("StreamIndicator", () => {
  it("says nothing for a short reconnect, then explains after 3 s", () => {
    vi.useFakeTimers();
    const { rerender } = render(<StreamIndicator status="reconnecting" />);
    act(() => vi.advanceTimersByTime(2900));
    expect(screen.queryByText(copy.stream.reconnecting)).toBeNull();
    act(() => vi.advanceTimersByTime(200));
    expect(screen.getByText(copy.stream.reconnecting)).toBeInTheDocument();
    rerender(<StreamIndicator status="open" />);
    expect(screen.queryByText(copy.stream.reconnecting)).toBeNull();
  });

  it("stays quiet while connecting or open", () => {
    vi.useFakeTimers();
    const { rerender } = render(<StreamIndicator status="connecting" />);
    act(() => vi.advanceTimersByTime(10_000));
    rerender(<StreamIndicator status="open" />);
    act(() => vi.advanceTimersByTime(10_000));
    expect(screen.queryByRole("status")).toBeEmptyDOMElement();
  });
});

describe("McpCard", () => {
  const at = () => performance.now();

  it("shows name, badge, issue, latency, uptime and the last check in KST", () => {
    render(<McpCard item={{ ...item(2, "FAILED", "seoul-weather"), uptime_24h: 0.912 }} receivedAt={at()} />);
    const card = screen.getByTestId("mcp-card");
    expect(card).toHaveAttribute("data-id", "2");
    expect(within(card).getByRole("heading", { name: "seoul-weather" })).toBeInTheDocument();
    expect(within(card).getByText("실패")).toBeInTheDocument();
    expect(within(card).getByText("프로세스 중지")).toBeInTheDocument();
    expect(within(card).getByText("91.2%")).toBeInTheDocument();
    expect(within(card).getByTitle(formatKst(NOW))).toBeInTheDocument();
    expect(within(card).getByRole("img", { name: /seoul-weather/ })).toBeInTheDocument();
  });

  it("draws the countdown only when the server sends one (F23)", () => {
    const { rerender } = render(<McpCard item={item(1, "ACTION")} receivedAt={at()} />);
    expect(screen.queryByRole("timer")).toBeNull();
    rerender(<McpCard item={item(1, "SUSPECT")} receivedAt={at()} />); // alert-only SUSPECT
    expect(screen.queryByRole("timer")).toBeNull();
    rerender(
      <McpCard item={{ ...item(1, "SUSPECT"), action_in_sec: 12, action_delay_sec: 30, action_due_at: NOW }} receivedAt={at()} />,
    );
    expect(screen.getByRole("timer")).toHaveTextContent(copy.board.actionIn(12));
  });

  it("shows a running script, maintenance, and spins the border while recovering", () => {
    const { rerender } = render(<McpCard item={item(1, "ACTION")} receivedAt={at()} />);
    expect(screen.getByText(copy.board.running("restart"))).toBeInTheDocument();
    rerender(<McpCard item={item(1, "MAINTENANCE")} receivedAt={at()} />);
    expect(screen.getByText(copy.board.maintenanceOn)).toBeInTheDocument();
    expect(screen.getByTestId("mcp-card")).not.toHaveAttribute("data-anim");
    rerender(<McpCard item={item(1, "RECOVERING")} receivedAt={at()} />);
    expect(screen.getByTestId("mcp-card")).toHaveAttribute("data-anim", "spin");
  });

  it("glows on a new reading only, and draws a turned state's band without the entrance delay", () => {
    const { container, rerender } = render(<McpCard item={item(1, "HEALTHY")} receivedAt={100} />);
    expect(container.querySelector("[data-anim='flash']")).toBeNull(); // the first reading: the rise is enough
    expect(container.querySelector("[data-anim='band']")).toHaveAttribute("data-entrance");
    rerender(<McpCard item={item(1, "HEALTHY")} receivedAt={200} />);
    const flash = container.querySelector("[data-anim='flash']");
    expect(flash).toHaveAttribute("aria-hidden", "true");
    rerender(<McpCard item={item(1, "HEALTHY")} receivedAt={300} />);
    expect(container.querySelector("[data-anim='flash']")).not.toBe(flash); // remounted: the glow plays again
    rerender(<McpCard item={item(1, "FAILED")} receivedAt={300} />);
    expect(container.querySelector("[data-anim='band']")).not.toHaveAttribute("data-entrance");
  });

  it("uses dashes when nothing was measured yet", () => {
    render(
      <McpCard
        item={{ ...item(1, "HEALTHY"), latency_ms: null, sparkline: [], uptime_24h: null, last_check_at: null }}
        receivedAt={at()}
      />,
    );
    expect(screen.getByText("기록 없음")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });
});
