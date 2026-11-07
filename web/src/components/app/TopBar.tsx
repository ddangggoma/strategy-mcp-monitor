import { Button } from "@/components/ui/button";
import { StreamIndicator } from "@/components/status/StreamIndicator";
import { copy } from "@/copy/ko";
import type { Me } from "@/lib/api-types";
import type { StreamStatus } from "@/lib/board-stream";
import { AccountMenu } from "./AccountMenu";
import { ChannelBadge } from "./ChannelBadge";
import { ThemeToggle } from "./ThemeToggle";

/** Login from the board comes back to the board (`/` is outside the admin router: F11, Task 9). */
export const LOGIN_HREF = "/admin/login?redirect=/";

/**
 * Sticky top bar shared by the board and the admin (§6.1): product, channel, live-stream health,
 * theme, and the account (login link, or the account menu). `me === null` = session not loaded
 * yet: the account area stays empty rather than flashing a login link.
 */
export function TopBar({ me, streamStatus, onLogout }: { me: Me | null; streamStatus: StreamStatus; onLogout(): Promise<void> }) {
  return (
    <header data-topbar="" className="flex h-(--size-topbar) items-center gap-3 bg-bg px-4 sm:px-6 2xl:px-8">
      <a href="/" className="shrink-0 rounded-sm text-base font-semibold text-fg">
        {copy.common.productName}
      </a>
      {me ? <ChannelBadge channel={me.channel} /> : null}
      <div className="ms-auto flex min-w-0 items-center gap-2">
        <StreamIndicator status={streamStatus} />
        <ThemeToggle />
        {me?.user ? <AccountMenu user={me.user} onLogout={onLogout} /> : null}
        {me && !me.user ? (
          <Button asChild variant="outline">
            <a href={LOGIN_HREF}>{copy.common.login}</a>
          </Button>
        ) : null}
      </div>
    </header>
  );
}
