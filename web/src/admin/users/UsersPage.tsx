import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { PencilIcon, PlusIcon, ShieldIcon } from "lucide-react";
import { useId, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
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
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { copy, messageForError } from "@/copy/ko";
import { ApiError } from "@/lib/api";
import type { AdminUser, Role, UserPatch } from "@/lib/api-types";
import { createUser, updateUser } from "@/lib/endpoints";
import { useSession } from "@/lib/session";
import { formatKst } from "@/lib/time";
import { cn } from "@/lib/utils";
import { useUsers } from "../queries";
import { qk } from "../query-keys";
import { LocalOnlyPage } from "../shell/LocalOnlyPage";

const ROLES: readonly Role[] = ["developer", "admin"];

const codeOf = (err: unknown) => (err instanceof ApiError ? err.code : "internal");

/** Who may use the console (Local, Admin): nothing renders and nothing is requested without permission. */
export function UsersPage() {
  return (
    <LocalOnlyPage action="manage_users" title={copy.users.title}>
      <UsersContent />
    </LocalOnlyPage>
  );
}

function UsersContent() {
  const { data, isPending, isError } = useUsers();

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-fg">{copy.users.title}</h1>
        <AddUserDialog />
      </div>
      {isPending ? (
        <div role="status" className="flex flex-col gap-2">
          <span className="sr-only">{copy.common.loading}</span>
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : isError ? (
        <p role="alert" className="text-sm text-fg">
          {copy.users.loadError}
        </p>
      ) : data.length === 0 ? (
        <p className="text-sm text-fg-muted">{copy.users.empty}</p>
      ) : (
        <UsersTable users={data} />
      )}
    </>
  );
}

/**
 * Every user in server order (no sorting: a row that moved after a change would put the next click
 * on someone else). No row animation (tables never move: direction.md §6).
 */
function UsersTable({ users }: { users: AdminUser[] }) {
  const me = useSession();
  const activeAdmins = users.filter((u) => u.role === "admin" && u.active).length;

  return (
    <div className="rounded-md border bg-surface">
      <Table aria-label={copy.users.listLabel}>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead scope="col">{copy.users.name}</TableHead>
            <TableHead scope="col">{copy.users.email}</TableHead>
            <TableHead scope="col">{copy.users.role}</TableHead>
            <TableHead scope="col">{copy.users.active}</TableHead>
            <TableHead scope="col">{copy.users.lastLogin}</TableHead>
            <TableHead scope="col" className="text-right">
              {copy.users.ownedMcps}
            </TableHead>
            <TableHead scope="col">
              <span className="sr-only">{copy.users.actions}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {users.map((u) => (
            <UserRow
              key={u.id}
              user={u}
              isMe={me?.user?.id === u.id}
              lastAdmin={u.role === "admin" && u.active && activeAdmins <= 1}
            />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** PATCH /api/users/{id}: the reply goes into the list, then the list is fetched again (a revoked
 * own session surfaces there as a 401 and the shell's onUnauthorized flow takes over, Task 9). */
function usePatchUser(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: UserPatch) => updateUser(id, patch),
    onSuccess: (saved) => {
      qc.setQueryData<AdminUser[]>(qk.users, (list) => list?.map((u) => (u.id === saved.id ? saved : u)));
      void qc.invalidateQueries({ queryKey: qk.users });
    },
  });
}

type Pending = { kind: "role"; role: Role } | { kind: "deactivate" };

function UserRow({ user, isMe, lastAdmin }: { user: AdminUser; isMe: boolean; lastAdmin: boolean }) {
  const patch = usePatchUser(user.id);
  const nameId = useId();
  const noteId = useId();
  const [selectOpen, setSelectOpen] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const roleTrigger = useRef<HTMLButtonElement>(null);
  const activeSwitch = useRef<HTMLButtonElement>(null);

  const busy = patch.isPending;
  const locked = lastAdmin || busy;
  const describedBy = lastAdmin ? `${nameId} ${noteId}` : nameId;
  const muted = !user.active;

  const run = async (body: UserPatch, done: string) => {
    try {
      await patch.mutateAsync(body);
      toast.success(done);
    } catch (err) {
      const code = codeOf(err);
      if (code !== "login_required") toast.error(messageForError(code));
    }
  };

  const ask = (p: Pending) => {
    setPending(p);
    setConfirmOpen(true);
  };

  return (
    <TableRow data-id={user.id} className={cn(muted && "text-fg-muted")} aria-busy={busy || undefined}>
      <th scope="row" className="px-3 py-2 text-left align-middle font-normal">
        {/* only the name (and its state) is the row header: it is read before every cell */}
        <div className="flex items-center gap-1.5 whitespace-nowrap">
          <span id={nameId} className={cn("font-semibold", muted ? "text-fg-muted" : "text-fg")}>
            {user.name}
          </span>
          {muted ? <Badge variant="secondary">{copy.users.inactive}</Badge> : null}
        </div>
      </th>
      <TableCell className="whitespace-nowrap">{user.email}</TableCell>
      <TableCell>
        <Select
          value={user.role}
          open={selectOpen}
          onOpenChange={(o) => setSelectOpen(o && !locked)}
          onValueChange={(r) => {
            if (!locked && r !== user.role) ask({ kind: "role", role: r as Role });
          }}
        >
          <SelectTrigger
            ref={roleTrigger}
            size="sm"
            className="w-36 aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
            aria-label={copy.users.role}
            aria-describedby={describedBy}
            aria-disabled={lastAdmin || undefined}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ROLES.map((r) => (
              <SelectItem key={r} value={r}>
                {copy.roles[r]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {lastAdmin ? (
          // seen next to the two locked controls, and their description
          <p id={noteId} className="mt-1.5 flex max-w-64 items-start gap-1.5 text-xs whitespace-normal text-fg-muted">
            <ShieldIcon aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
            {copy.users.lastAdmin}
          </p>
        ) : null}
      </TableCell>
      <TableCell>
        <Switch
          ref={activeSwitch}
          checked={user.active}
          aria-label={copy.users.active}
          aria-describedby={describedBy}
          aria-disabled={lastAdmin || undefined}
          onCheckedChange={(on) => {
            if (locked) return;
            if (on) void run({ active: true }, copy.users.activated(user.name));
            else ask({ kind: "deactivate" });
          }}
        />
      </TableCell>
      <TableCell className="whitespace-nowrap tabular-nums">
        {user.last_login_at ? (
          <span data-volatile="">{formatKst(user.last_login_at)}</span>
        ) : (
          <span className="text-fg-muted">{copy.users.neverLoggedIn}</span>
        )}
      </TableCell>
      <TableCell className="text-right tabular-nums">{user.owned_mcps}</TableCell>
      <TableCell className="text-right">
        <EditNameDialog user={user} />
      </TableCell>

      <ChangeConfirm
        user={user}
        isMe={isMe}
        pending={pending}
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        returnFocus={() => (pending?.kind === "role" ? roleTrigger : activeSwitch).current?.focus()}
        onConfirm={(p) => {
          if (p.kind === "role") void run({ role: p.role }, copy.users.roleChanged(user.name, copy.roles[p.role]));
          else void run({ active: false }, copy.users.deactivated(user.name));
        }}
      />
    </TableRow>
  );
}

/**
 * Role changes and deactivation sign the person out at once (the server revokes their sessions),
 * so both are confirmed; the title states the result. `pending` stays set while the dialog closes.
 */
function ChangeConfirm({
  user,
  isMe,
  pending,
  open,
  onOpenChange,
  onConfirm,
  returnFocus,
}: {
  user: AdminUser;
  isMe: boolean;
  pending: Pending | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (p: Pending) => void;
  /** Opened by state, not a Radix trigger: hand focus back to the control that asked. */
  returnFocus: () => void;
}) {
  if (!pending) return null;
  const role = pending.kind === "role";
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent
        onCloseAutoFocus={(e) => {
          e.preventDefault();
          returnFocus();
        }}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>
            {role ? copy.users.roleTitle(user.name, copy.roles[pending.role]) : copy.users.deactivateTitle(user.name)}
          </AlertDialogTitle>
          <AlertDialogDescription>{copy.users.revokeNotice}</AlertDialogDescription>
          {isMe ? <p className="text-sm font-semibold text-fg">{copy.users.revokeSelf}</p> : null}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{copy.common.cancel}</AlertDialogCancel>
          <AlertDialogAction variant={role ? "default" : "destructive"} onClick={() => onConfirm(pending)}>
            {role ? copy.users.roleConfirm : copy.users.deactivateConfirm}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

// ---- name ----------------------------------------------------------------------------

const nameField = z
  .string()
  .transform((v) => v.trim())
  .pipe(z.string().min(1, copy.users.nameRequired).max(100, copy.users.nameTooLong));

const nameSchema = z.object({ name: nameField });

function EditNameDialog({ user }: { user: AdminUser }) {
  const [open, setOpen] = useState(false);
  const [round, setRound] = useState(0);
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o) setRound((r) => r + 1);
      }}
    >
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" aria-label={copy.users.editName(user.name)}>
          <PencilIcon aria-hidden="true" />
          {copy.users.editNameShort}
        </Button>
      </DialogTrigger>
      {/* a new form per opening: no stale value or error from last time */}
      <EditNameForm key={round} user={user} onDone={() => setOpen(false)} />
    </Dialog>
  );
}

function EditNameForm({ user, onDone }: { user: AdminUser; onDone: () => void }) {
  const patch = usePatchUser(user.id);
  const form = useForm<z.input<typeof nameSchema>, unknown, z.output<typeof nameSchema>>({
    resolver: zodResolver(nameSchema),
    defaultValues: { name: user.name },
  });
  const serverError = form.formState.errors.root?.server?.message;

  const onValid = async ({ name }: { name: string }) => {
    if (name === user.name) {
      onDone();
      return;
    }
    try {
      await patch.mutateAsync({ name });
      toast.success(copy.users.nameSaved);
      onDone();
    } catch (err) {
      const code = codeOf(err);
      if (code !== "login_required") form.setError("root.server", { type: "server", message: messageForError(code) });
    }
  };

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{copy.users.editNameTitle}</DialogTitle>
        <DialogDescription>{user.email}</DialogDescription>
      </DialogHeader>
      <Form {...form}>
        <form noValidate onSubmit={form.handleSubmit(onValid)} className="flex flex-col gap-4">
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{copy.users.name}</FormLabel>
                <FormControl>
                  <Input {...field} autoComplete="off" maxLength={100} readOnly={patch.isPending} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          {serverError ? (
            <p role="alert" className="text-sm text-danger">
              {serverError}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="submit" aria-busy={patch.isPending || undefined}>
              {patch.isPending ? copy.common.saving : copy.common.save}
            </Button>
          </DialogFooter>
        </form>
      </Form>
    </DialogContent>
  );
}

// ---- add -----------------------------------------------------------------------------

const addSchema = z.object({
  email: z
    .string()
    .transform((v) => v.trim())
    .pipe(z.string().min(1, copy.users.emailRequired).max(320, copy.errors.invalid_email)),
  name: nameField,
  role: z.enum(["developer", "admin"]),
});

function AddUserDialog() {
  const [open, setOpen] = useState(false);
  const [round, setRound] = useState(0);
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o) setRound((r) => r + 1);
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <PlusIcon aria-hidden="true" />
          {copy.users.add}
        </Button>
      </DialogTrigger>
      <AddUserForm key={round} onDone={() => setOpen(false)} />
    </Dialog>
  );
}

/** The server decides what a valid email is; its answers land on the email field. */
function AddUserForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const form = useForm<z.input<typeof addSchema>, unknown, z.output<typeof addSchema>>({
    resolver: zodResolver(addSchema),
    defaultValues: { email: "", name: "", role: "developer" },
  });
  const { isSubmitting, errors } = form.formState;
  const serverError = errors.root?.server?.message;

  const onValid = async (body: z.output<typeof addSchema>) => {
    try {
      const created = await createUser(body);
      await qc.invalidateQueries({ queryKey: qk.users });
      toast.success(copy.users.added(created.name));
      onDone();
    } catch (err) {
      const code = codeOf(err);
      if (code === "user_exists" || code === "invalid_email") {
        form.setError("email", { type: "server", message: copy.errors[code] }, { shouldFocus: true });
      } else if (code !== "login_required") {
        form.setError("root.server", { type: "server", message: messageForError(code) });
      }
    }
  };

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{copy.users.addTitle}</DialogTitle>
        <DialogDescription>{copy.users.addLead}</DialogDescription>
      </DialogHeader>
      <Form {...form}>
        <form noValidate onSubmit={form.handleSubmit(onValid)} className="flex flex-col gap-4">
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{copy.users.email}</FormLabel>
                <FormControl>
                  <Input {...field} type="email" autoComplete="off" spellCheck={false} maxLength={320} readOnly={isSubmitting} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{copy.users.name}</FormLabel>
                <FormControl>
                  <Input {...field} autoComplete="off" maxLength={100} readOnly={isSubmitting} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="role"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{copy.users.role}</FormLabel>
                <Select value={field.value} onValueChange={field.onChange} disabled={isSubmitting}>
                  <FormControl>
                    <SelectTrigger className="w-full" onBlur={field.onBlur}>
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {ROLES.map((r) => (
                      <SelectItem key={r} value={r}>
                        {copy.roles[r]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
          {serverError ? (
            <p role="alert" className="text-sm text-danger">
              {serverError}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="submit" aria-busy={isSubmitting || undefined}>
              {isSubmitting ? copy.users.adding : copy.users.addSubmit}
            </Button>
          </DialogFooter>
        </form>
      </Form>
    </DialogContent>
  );
}
