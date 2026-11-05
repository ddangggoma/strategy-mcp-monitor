import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Trash2Icon } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";
import { WithReason } from "@/components/app/WithReason";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { copy, messageForError } from "@/copy/ko";
import { ApiError } from "@/lib/api";
import type { McpDetail } from "@/lib/api-types";
import { deleteMcp } from "@/lib/endpoints";
import { denyReason } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { qk } from "../query-keys";

/**
 * "삭제" button and its confirmation (Local; a developer only for an MCP they own). The delete
 * button stays inactive until the MCP's name is typed again; the dialog says the stop script is
 * not run. 204 → the list; 409 action_in_progress stays in the dialog.
 */
export function DeleteMcpDialog({ mcp }: { mcp: McpDetail }) {
  const me = useSession();
  const reason = denyReason(me, "delete_mcp", mcp.owner?.id ?? null);
  const [open, setOpen] = useState(false);
  const [round, setRound] = useState(0);

  const trigger = (
    <Button variant="ghost">
      <Trash2Icon aria-hidden="true" />
      {copy.common.delete}
    </Button>
  );
  if (reason !== null) return <WithReason reason={reason}>{trigger}</WithReason>;

  return (
    <AlertDialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o) setRound((r) => r + 1);
      }}
    >
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <DeleteForm key={round} mcp={mcp} />
    </AlertDialog>
  );
}

function DeleteForm({ mcp }: { mcp: McpDetail }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputId = useId();
  const ready = typed === mcp.name && !busy;

  const submit = async () => {
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      await deleteMcp(mcp.id);
    } catch (err) {
      setError(messageForError(err instanceof ApiError ? err.code : "internal"));
      setBusy(false);
      return;
    }
    qc.setQueryData<McpDetail[]>(qk.mcps, (list) => list?.filter((m) => m.id !== mcp.id));
    toast.success(copy.mcp.deleted(mcp.name));
    // leave the page first: removing its query while it is still mounted would refetch a 404
    await navigate({ to: "/admin/mcps", ignoreBlocker: true }); // the MCP is gone: unsaved settings with it
    qc.removeQueries({ queryKey: qk.mcp(mcp.id) });
  };

  return (
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>{copy.mcp.deleteTitle(mcp.name)}</AlertDialogTitle>
        <AlertDialogDescription>{copy.mcp.deleteConfirm}</AlertDialogDescription>
      </AlertDialogHeader>
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="flex flex-col gap-2">
          <Label htmlFor={inputId}>{copy.mcp.deleteNameLabel}</Label>
          <Input
            id={inputId}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            placeholder={mcp.name}
            readOnly={busy}
          />
        </div>
        {error ? (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel>{copy.common.cancel}</AlertDialogCancel>
          <Button type="submit" variant="destructive" aria-disabled={ready ? undefined : true} aria-busy={busy || undefined}>
            {busy ? copy.mcp.deleting : copy.mcp.deleteAction}
          </Button>
        </AlertDialogFooter>
      </form>
    </AlertDialogContent>
  );
}
