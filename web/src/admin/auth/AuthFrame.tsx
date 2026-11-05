import type { ReactNode } from "react";
import { ChannelBadge } from "@/components/app/ChannelBadge";
import { ThemeToggle } from "@/components/app/ThemeToggle";
import { copy } from "@/copy/ko";
import { useSession } from "@/lib/session";

/**
 * Frame for the anonymous admin pages (login, first-run setup): product (a link back to the
 * board), the channel this tab came in through, the theme, and one narrow left-aligned column.
 */
export function AuthFrame({ children }: { children: ReactNode }) {
  const me = useSession();
  return (
    <>
      <header data-topbar="" className="flex h-(--size-topbar) items-center gap-3 bg-bg px-6">
        <a href="/" className="shrink-0 rounded-sm text-base font-semibold text-fg">
          {copy.common.productName}
        </a>
        {me ? <ChannelBadge channel={me.channel} /> : null}
        <div className="ms-auto">
          <ThemeToggle />
        </div>
      </header>
      <main id="main" className="mx-auto flex w-full max-w-[24rem] flex-col gap-6 py-20">
        {children}
      </main>
    </>
  );
}
