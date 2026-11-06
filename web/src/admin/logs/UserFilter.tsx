import { CheckIcon, ChevronDownIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { copy } from "@/copy/ko";
import type { LogQuery } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { useLogUsers } from "../queries";

/**
 * Pick users from the ones seen in the current range, with their line counts. The counts ignore
 * the user filter itself (server), so the query leaves it out and picking does not refetch. The
 * list is read only while the popover is open.
 */
export function UserFilter({ query, selected, onToggle }: { query: LogQuery; selected: readonly string[]; onToggle(user: string): void }) {
  const [open, setOpen] = useState(false);
  const facetQuery = useMemo(() => ({ ...query, users: undefined }), [query]);
  const { data, isPending, isError } = useLogUsers(facetQuery, { enabled: open });

  // picked users first (even ones the range no longer has), then the rest by count
  const items = useMemo(() => {
    const counts = new Map((data ?? []).map((u) => [u.user, u.count]));
    const picked = selected.map((user) => ({ user, count: counts.get(user) ?? 0, on: true }));
    const on = new Set(selected);
    const rest = (data ?? []).filter((u) => !on.has(u.user)).map((u) => ({ ...u, on: false }));
    return [...picked, ...rest];
  }, [data, selected]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline">
          {copy.logs.users}
          {selected.length > 0 ? (
            <>
              {" "}
              <Badge>{copy.logs.usersCount(selected.length)}</Badge>
            </>
          ) : null}
          <ChevronDownIcon aria-hidden="true" className="size-3.5 text-fg-muted" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(22rem,calc(100vw-2rem))] p-0">
        <Command>
          <CommandInput placeholder={copy.logs.usersSearch} aria-label={copy.logs.usersSearch} />
          <CommandList>
            {isPending && open ? (
              <p role="status" className="py-6 text-center text-sm text-fg-muted">
                {copy.common.loading}
              </p>
            ) : isError && !data ? (
              <p role="alert" className="py-6 text-center text-sm text-fg">
                {copy.logs.loadError}
              </p>
            ) : (
              <CommandEmpty>{copy.logs.usersEmpty}</CommandEmpty>
            )}
            {items.map((u) => (
              <CommandItem key={u.user} value={u.user} onSelect={() => onToggle(u.user)} className="gap-2">
                <CheckIcon aria-hidden="true" className={cn("size-4", u.on ? "text-fg" : "invisible")} />
                {u.on ? <span className="sr-only">{copy.logs.picked}</span> : null}
                <span className="min-w-0 flex-1 truncate">{u.user}</span>
                <span className="text-xs text-fg-muted tabular-nums">{u.count.toLocaleString("ko-KR")}</span>
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
