import { useNavigate } from "@tanstack/react-router";
import { ServerIcon } from "lucide-react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { copy } from "@/copy/ko";
import { useSession } from "@/lib/session";
import { useMcps } from "../queries";
import { NAV_ITEMS, navReason } from "./Nav";

/**
 * Quick jump (Ctrl+K / ⌘K): every screen of the navigation — blocked ones listed but disabled,
 * with the reason — and every MCP by name (the `qk.mcps` cache, fetched on first open).
 * Loaded as its own chunk the first time it opens (cmdk stays out of the shell).
 */
export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange(open: boolean): void }) {
  const me = useSession();
  const navigate = useNavigate();
  const { data: mcps } = useMcps({ enabled: open });

  const close = () => onOpenChange(false);

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder={copy.common.commandHint} />
      <CommandList>
        <CommandEmpty>{copy.common.noResults}</CommandEmpty>
        <CommandGroup heading={copy.common.commandScreens}>
          {NAV_ITEMS.map((item) => {
            const reason = navReason(me, item);
            const Icon = item.icon;
            const to = item.to;
            return (
              <CommandItem
                key={item.key}
                value={`nav:${item.key} ${copy.nav[item.key]}`}
                disabled={reason !== null || to === null}
                onSelect={() => {
                  if (reason !== null || to === null) return;
                  close();
                  void navigate({ to });
                }}
              >
                <Icon aria-hidden="true" />
                <span>{copy.nav[item.key]}</span>
                {reason ? <span className="ms-auto max-w-[60%] truncate text-xs text-fg-muted">{copy.deny[reason]}</span> : null}
              </CommandItem>
            );
          })}
        </CommandGroup>
        {mcps && mcps.length > 0 ? (
          <CommandGroup heading={copy.common.commandMcps}>
            {mcps.map((m) => (
              <CommandItem
                key={m.id}
                value={`mcp:${m.id} ${m.name}`}
                onSelect={() => {
                  close();
                  void navigate({ to: "/admin/mcps/$mcpId", params: { mcpId: String(m.id) } });
                }}
              >
                <ServerIcon aria-hidden="true" />
                <span className="truncate">{m.name}</span>
                <span className="ms-auto font-mono text-xs text-fg-muted">
                  {m.host}:{m.port}
                </span>
              </CommandItem>
            ))}
          </CommandGroup>
        ) : null}
      </CommandList>
    </CommandDialog>
  );
}
