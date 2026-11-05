import { LayoutDashboardIcon, LogOutIcon, UserRoundIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { copy } from "@/copy/ko";
import type { SessionUser } from "@/lib/api-types";

/** Logged-in account: who (name, email, role), a way into the admin, and logout. */
export function AccountMenu({ user, onLogout }: { user: SessionUser; onLogout(): Promise<void> }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" aria-label={copy.common.accountMenu(user.name)}>
          <UserRoundIcon aria-hidden="true" />
          <span className="max-w-32 truncate max-sm:sr-only">{user.name}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-56">
        <DropdownMenuLabel className="flex flex-col gap-1 font-normal">
          <span className="truncate font-semibold text-fg">{user.name}</span>
          <span className="truncate text-xs text-fg-muted">{user.email}</span>
          <Badge variant="secondary" className="mt-1">
            {copy.roles[user.role]}
          </Badge>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <a href="/admin">
            <LayoutDashboardIcon aria-hidden="true" />
            {copy.common.adminHome}
          </a>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void onLogout()}>
          <LogOutIcon aria-hidden="true" />
          {copy.common.logout}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
