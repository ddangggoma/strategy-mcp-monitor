import { ActivityIcon, LayoutDashboardIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StreamIndicator } from "@/components/status/StreamIndicator";
import { copy } from "@/copy/ko";
import type { Me } from "@/lib/api-types";
import type { StreamStatus } from "@/lib/board-stream";
import { cn } from "@/lib/utils";
import { AccountMenu } from "./AccountMenu";
import { ChannelBadge } from "./ChannelBadge";
import { ThemeToggle } from "./ThemeToggle";

/** Login from the board comes back to the board (`/` is outside the admin router: F11, Task 9). */
export const LOGIN_HREF = "/admin/login?redirect=/";
/** The board's "관리 화면" while signed out: log in, then the admin screen. */
export const ADMIN_LOGIN_HREF = "/admin/login?redirect=/admin";

/** Which screen the bar sits on: the board, or the admin shell. */
export type TopBarPlace = "board" | "admin";

/**
 * The one-click way between the two screens: on the Local board (the app window's home) “관리 화면”,
 * in the admin shell “상태 보드”. The External board keeps only its login link (the admin screen
 * is reached from there after logging in, through the account menu).
 */
function SwitchScreen({ me, place }: { me: Me; place: TopBarPlace }) {
  if (place === "admin") {
    return (
      <Button asChild variant="ghost">
        <a href="/">
          <ActivityIcon aria-hidden="true" />
          <span className="max-sm:sr-only">{copy.common.boardHome}</span>
        </a>
      </Button>
    );
  }
  if (me.channel !== "local") return null;
  return (
    <Button asChild variant="outline">
      <a href={me.user ? "/admin" : ADMIN_LOGIN_HREF}>
        <LayoutDashboardIcon aria-hidden="true" />
        <span className="max-sm:sr-only">{copy.common.adminHome}</span>
      </a>
    </Button>
  );
}

/**
 * Sticky top bar shared by the board and the admin (§6.1): product, channel, live-stream health,
 * theme, the way to the other screen, and the account (login link, or the account menu).
 * `me === null` = session not loaded yet: the account area stays empty rather than flashing a
 * login link.
 */
export function TopBar({
  me,
  streamStatus,
  onLogout,
  place = "board",
}: {
  me: Me | null;
  streamStatus: StreamStatus;
  onLogout(): Promise<void>;
  place?: TopBarPlace;
}) {
  return (
    <header data-topbar="" className="flex h-(--size-topbar) items-center gap-3 bg-bg px-4 max-sm:gap-2 sm:px-6 2xl:px-8">
      <a href="/" className="shrink-0 rounded-sm text-base font-semibold text-fg">
        {copy.common.productName}
      </a>
      {me ? <ChannelBadge channel={me.channel} /> : null}
      <div className="ms-auto flex min-w-0 items-center gap-2 max-sm:gap-1">
        <StreamIndicator status={streamStatus} />
        <ThemeToggle />
        {me ? <SwitchScreen me={me} place={place} /> : null}
        {me?.user ? <AccountMenu user={me.user} onLogout={onLogout} /> : null}
        {me && !me.user ? (
          // narrower than the 640 px window (400% zoom) the Local board keeps only 관리 화면,
          // which logs in too: both would need a sideways scroll
          <Button asChild variant="outline" className={cn(place === "board" && me.channel === "local" && "max-sm:hidden")}>
            <a href={LOGIN_HREF}>{copy.common.login}</a>
          </Button>
        ) : null}
      </div>
    </header>
  );
}
