import { Link } from "@tanstack/react-router";
import {
  LayoutDashboardIcon,
  LockIcon,
  MegaphoneIcon,
  MonitorSmartphoneIcon,
  ScrollTextIcon,
  SearchIcon,
  ServerIcon,
  SettingsIcon,
  ShieldCheckIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";
import { useSyncExternalStore, type ReactNode } from "react";
import { WithReason } from "@/components/app/WithReason";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { copy, type DisabledReason } from "@/copy/ko";
import type { Me } from "@/lib/api-types";
import { denyReason, type Action } from "@/lib/permissions";
import { cn } from "@/lib/utils";

export type NavTo = "/admin" | "/admin/mcps" | "/admin/sessions" | "/admin/users" | "/admin/notice" | "/admin/settings";
export type PlannedReason = Extract<DisabledReason, `planned_${string}`>;

export interface NavItem {
  key: "dashboard" | "mcps" | "sessions" | "logs" | "audit" | "users" | "notice" | "settings";
  icon: LucideIcon;
  /** Destination; planned items have none. */
  to: NavTo | null;
  /** Policy action that must be allowed (null: any logged-in user). */
  gate: Action | null;
  planned: PlannedReason | null;
  /** Starts the Admin group (a divider above it). */
  groupStart?: boolean;
}

/** Order and gates of spec §6.4: monitoring first, then the Local Admin tools. */
export const NAV_ITEMS: readonly NavItem[] = [
  { key: "dashboard", icon: LayoutDashboardIcon, to: "/admin", gate: null, planned: null },
  { key: "mcps", icon: ServerIcon, to: "/admin/mcps", gate: null, planned: null },
  // both channels (V31); `planned_sessions` stays in DisabledReason but is no longer used
  { key: "sessions", icon: MonitorSmartphoneIcon, to: "/admin/sessions", gate: "view_session_history", planned: null },
  { key: "logs", icon: ScrollTextIcon, to: null, gate: null, planned: "planned_logs" },
  { key: "audit", icon: ShieldCheckIcon, to: null, gate: null, planned: "planned_audit" },
  { key: "users", icon: UsersIcon, to: "/admin/users", gate: "manage_users", planned: null, groupStart: true },
  { key: "notice", icon: MegaphoneIcon, to: "/admin/notice", gate: "edit_notice", planned: null },
  { key: "settings", icon: SettingsIcon, to: "/admin/settings", gate: "edit_global_settings", planned: null },
];

/** Why `me` cannot open the item (null: it can). */
export function navReason(me: Me | null, item: NavItem): DisabledReason | null {
  if (item.planned) return item.planned;
  return item.gate ? denyReason(me, item.gate) : null;
}

/** Below this width (Tailwind lg) the sidebar collapses to an icon rail. */
const RAIL_QUERY = "(width < 64rem)";

function subscribeRail(onChange: () => void): () => void {
  const mq = window.matchMedia(RAIL_QUERY);
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

/** True while the window is narrow enough for the icon rail (labels then live in tooltips). */
function useRail(): boolean {
  return useSyncExternalStore(subscribeRail, () => window.matchMedia(RAIL_QUERY).matches);
}

const ITEM =
  "flex h-(--size-control) shrink-0 items-center gap-2.5 rounded-md px-2.5 text-sm font-medium whitespace-nowrap transition-[background-color,color] duration-(--motion-fast) ease-hover max-lg:justify-center max-lg:px-0";

function ItemBody({ item, trailing }: { item: NavItem; trailing?: ReactNode }) {
  const Icon = item.icon;
  return (
    <>
      <Icon aria-hidden="true" className="size-4 shrink-0" />
      <span className="max-lg:sr-only">{copy.nav[item.key]}</span>
      {trailing}
    </>
  );
}

function NavEntry({ item, me, rail }: { item: NavItem; me: Me; rail: boolean }) {
  const reason = navReason(me, item);
  const label = copy.nav[item.key];
  if (reason !== null || item.to === null) {
    // a link that does not go anywhere (U26): focusable, explained by tooltip and description
    const trailing = item.planned ? (
      <span aria-hidden="true" className="ms-auto text-xs font-normal text-fg-muted max-lg:hidden">
        {copy.nav.planned}
      </span>
    ) : (
      <LockIcon aria-hidden="true" className="ms-auto size-3.5 shrink-0 max-lg:hidden" />
    );
    return (
      <WithReason reason={reason} side="right" label={rail ? label : undefined}>
        <span role="link" tabIndex={0} className={cn(ITEM, "cursor-not-allowed text-fg-muted [&>svg:first-child]:opacity-60")}>
          <ItemBody item={item} trailing={trailing} />
        </span>
      </WithReason>
    );
  }
  const link = (
    <Link
      to={item.to}
      activeOptions={{ exact: item.to === "/admin", includeSearch: false }}
      className={cn(ITEM, "text-fg-muted hover:bg-hover hover:text-fg aria-[current=page]:bg-selected aria-[current=page]:text-fg")}
    >
      <ItemBody item={item} />
    </Link>
  );
  if (!rail) return link;
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>{link}</TooltipTrigger>
        <TooltipContent side="right">{label}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/**
 * Admin navigation. Nothing is hidden: planned and forbidden items stay as disabled links with
 * the reason (§4.4). A sticky sidebar with the quick-jump button on top and the signed-in user at
 * the bottom; in a window narrower than 1024px it collapses to an icon rail (labels stay as the
 * accessible names and appear as tooltips).
 */
export function Nav({ me, onOpenPalette, onPreloadPalette, shortcut }: {
  me: Me;
  onOpenPalette(): void;
  onPreloadPalette(): void;
  shortcut: string;
}) {
  const user = me.user;
  const rail = useRail();
  return (
    <nav
      aria-label={copy.nav.label}
      data-rail={rail ? "" : undefined}
      className="sticky top-(--size-topbar) flex h-[calc(100dvh-var(--size-topbar))] flex-col gap-1 overflow-y-auto border-e bg-surface p-3 max-lg:px-2"
    >
      <Button
        variant="outline"
        className="mb-2 justify-start text-fg-muted max-lg:justify-center max-lg:px-0"
        onClick={onOpenPalette}
        onPointerEnter={onPreloadPalette}
        onFocus={onPreloadPalette}
      >
        <SearchIcon aria-hidden="true" />
        <span className="max-lg:sr-only">{copy.common.commandTitle}</span>
        <kbd className="ms-auto rounded-xs border px-1 font-sans text-xs text-fg-muted max-lg:hidden">{shortcut}</kbd>
      </Button>
      <ul className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => (
          <li key={item.key} className={cn(item.groupStart && "mt-3 border-t pt-3")}>
            <NavEntry item={item} me={me} rail={rail} />
          </li>
        ))}
      </ul>
      {user ? (
        // the rail has no room for it; the account menu in the top bar shows the same
        <div className="mt-auto flex flex-col gap-1 border-t px-2.5 pt-3 max-lg:sr-only">
          <span className="truncate text-sm font-medium text-fg">{user.name}</span>
          <Badge variant="secondary">{copy.roles[user.role]}</Badge>
        </div>
      ) : null}
    </nav>
  );
}
