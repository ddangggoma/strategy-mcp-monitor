import { useQueryClient } from "@tanstack/react-query";
import { UserRoundCogIcon } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";
import { WithReason } from "@/components/app/WithReason";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { copy, messageForError } from "@/copy/ko";
import { ApiError } from "@/lib/api";
import type { McpDetail } from "@/lib/api-types";
import { transferOwner } from "@/lib/endpoints";
import { can, denyReason } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { storeMcp, useUsers } from "../queries";
import { qk } from "../query-keys";

/**
 * "소유권 이전" button and its dialog (Local, Admin). The user list is fetched only while the dialog
 * is open; only active users are offered and the current owner is shown but not selectable.
 * Without permission the button stays visible, disabled with its reason (U26).
 */
export function OwnerTransferDialog({ mcp }: { mcp: McpDetail }) {
  const me = useSession();
  const reason = denyReason(me, "transfer_ownership");
  const [open, setOpen] = useState(false);
  const [round, setRound] = useState(0);

  const trigger = (
    <Button variant="ghost">
      <UserRoundCogIcon aria-hidden="true" />
      {copy.mcp.transferOwner}
    </Button>
  );
  if (reason !== null) return <WithReason reason={reason}>{trigger}</WithReason>;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o) setRound((r) => r + 1);
      }}
    >
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      {/* a new key per opening: no stale choice or error from last time (the exit animation still plays) */}
      <TransferForm key={round} mcp={mcp} open={open} onDone={() => setOpen(false)} />
    </Dialog>
  );
}

function TransferForm({ mcp, open, onDone }: { mcp: McpDetail; open: boolean; onDone: () => void }) {
  const me = useSession();
  const qc = useQueryClient();
  const users = useUsers({ enabled: open && can(me, "transfer_ownership") });
  const [choice, setChoice] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectId = useId();

  const active = users.data?.filter((u) => u.active) ?? [];
  const ready = choice !== "" && !busy;

  const submit = async () => {
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      const detail = await transferOwner(mcp.id, Number(choice));
      storeMcp(qc, detail);
      void qc.invalidateQueries({ queryKey: qk.users }); // owned_mcps counts changed
      toast.success(copy.mcp.transferred(mcp.name, detail.owner?.name ?? ""));
      onDone();
    } catch (err) {
      setError(messageForError(err instanceof ApiError ? err.code : "internal"));
      setBusy(false);
    }
  };

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{copy.mcp.transferOwner}</DialogTitle>
        <DialogDescription>{copy.mcp.transferOwnerLead}</DialogDescription>
      </DialogHeader>
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="flex flex-col gap-2">
          <Label htmlFor={selectId}>{copy.mcp.newOwner}</Label>
          <Select value={choice} onValueChange={setChoice} disabled={busy}>
            <SelectTrigger id={selectId} className="w-full">
              <SelectValue placeholder={users.isPending ? copy.common.loading : copy.mcp.chooseOwner} />
            </SelectTrigger>
            <SelectContent position="popper">
              {active.map((u) => {
                const current = u.id === mcp.owner?.id;
                return (
                  <SelectItem key={u.id} value={String(u.id)} disabled={current}>
                    {u.name}
                    <span className="text-fg-muted">
                      {current ? `${u.email} (${copy.mcp.currentOwner})` : u.email}
                    </span>
                  </SelectItem>
                );
              })}
            </SelectContent>
          </Select>
          {users.isError ? (
            <p role="alert" className="text-sm text-danger">
              {copy.mcp.usersError}
            </p>
          ) : null}
        </div>
        {error ? (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={onDone}>
            {copy.common.cancel}
          </Button>
          <Button type="submit" aria-disabled={ready ? undefined : true} aria-busy={busy || undefined}>
            {busy ? copy.mcp.transferring : copy.mcp.transferSubmit}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}
