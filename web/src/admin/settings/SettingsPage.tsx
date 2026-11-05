import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel } from "@/components/ui/form";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { copy, messageForError } from "@/copy/ko";
import { ApiError } from "@/lib/api";
import type { Settings } from "@/lib/api-types";
import { retentionPreview, updateSettings } from "@/lib/endpoints";
import { denyReason } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { dirtyPatch } from "../mcps/mcp-schema";
import { useSettings } from "../queries";
import { qk } from "../query-keys";
import { LeaveGuard } from "../shell/LeaveGuard";
import { LocalOnlyPage } from "../shell/LocalOnlyPage";
import { PlannedFeature } from "../shell/PlannedFeature";
import { NumberField } from "./NumberField";
import { RetentionConfirm, RetentionSection, type RetentionChange } from "./RetentionSection";
import {
  RETENTION_KEYS, START_TYPES, settingsSchema, type SettingsFormValues, type SettingsValues,
} from "./settings-schema";

/** Global settings (Local, Admin): nothing renders and nothing is requested without permission. */
export function SettingsPage() {
  return (
    <LocalOnlyPage action="edit_global_settings" title={copy.settings.title}>
      <h1 className="text-xl font-semibold text-fg">{copy.settings.title}</h1>
      <SettingsContent />
    </LocalOnlyPage>
  );
}

function SettingsContent() {
  const { data, isPending, isError } = useSettings();
  if (isPending) {
    return (
      <div role="status" className="flex max-w-(--size-prose) flex-col gap-3">
        <span className="sr-only">{copy.common.loading}</span>
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    );
  }
  if (isError) {
    return (
      <p role="alert" className="text-sm text-fg">
        {copy.settings.loadError}
      </p>
    );
  }
  return <SettingsForm settings={data} />;
}

function toValues(s: Settings): SettingsFormValues {
  return {
    ping_interval_sec: s.ping_interval_sec,
    issue_check_interval_sec: s.issue_check_interval_sec,
    confirm_interval_sec: s.confirm_interval_sec,
    log_retention_days: s.log_retention_days,
    log_compress_after_days: s.log_compress_after_days,
    service_start_type: s.service_start_type,
  };
}

/**
 * One form, one save (U27: only the changed fields go out; the two retention values always travel
 * together). Lowering retention first asks the server what the new value deletes and saves only
 * after the person confirms it.
 */
function SettingsForm({ settings }: { settings: Settings }) {
  const me = useSession();
  const qc = useQueryClient();
  const retentionReason = denyReason(me, "edit_retention");

  // a refetch hands out a new object with the same values: reset only when a value changed
  const serverKey = JSON.stringify(toValues(settings));
  const serverValues = useMemo(() => JSON.parse(serverKey) as SettingsFormValues, [serverKey]);

  const form = useForm<SettingsFormValues, unknown, SettingsValues>({
    resolver: zodResolver(settingsSchema),
    defaultValues: serverValues,
  });
  const { isDirty, isSubmitting, dirtyFields, errors } = form.formState;

  useEffect(() => {
    form.reset(serverValues, { keepDirtyValues: true });
  }, [form, serverValues]);

  const [saving, setSaving] = useState(false);
  const [change, setChange] = useState<{ patch: Partial<SettingsValues>; retention: RetentionChange } | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const saveButton = useRef<HTMLButtonElement>(null);

  const busy = isSubmitting || saving;
  const canSave = isDirty && !busy;

  const save = async (patch: Partial<SettingsValues>) => {
    setSaving(true);
    try {
      const saved = await updateSettings(patch);
      qc.setQueryData(qk.settings, saved);
      form.reset(toValues(saved));
      // the usage line is measured against the saved value
      void qc.invalidateQueries({ queryKey: ["retention-preview"] });
      toast.success(copy.common.saved);
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "internal";
      if (code !== "login_required") form.setError("root.server", { type: "server", message: messageForError(code) });
    } finally {
      setSaving(false);
    }
  };

  const onValid = async (values: SettingsValues) => {
    const patch = dirtyPatch(values, dirtyFields);
    if (RETENTION_KEYS.some((k) => k in patch)) {
      for (const k of RETENTION_KEYS) patch[k] = values[k];
    }
    if (Object.keys(patch).length === 0) return;

    const from = settings.log_retention_days;
    const to = patch.log_retention_days;
    if (to === undefined || to >= from) {
      await save(patch);
      return;
    }
    try {
      // always ask again: files may have been written or removed since the last look
      const preview = await qc.fetchQuery({ queryKey: qk.retention(to), queryFn: () => retentionPreview(to), staleTime: 0 });
      setChange({ patch, retention: { from, to, preview } });
      setConfirmOpen(true);
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "internal";
      if (code !== "login_required") form.setError("root.server", { type: "server", message: copy.settings.previewError });
    }
  };

  const submit = form.handleSubmit(onValid);
  const serverError = errors.root?.server?.message;
  const s = copy.settings;

  return (
    <Form {...form}>
      <form
        noValidate
        onSubmit={(e) => {
          if (!canSave) {
            e.preventDefault();
            return;
          }
          void submit(e);
        }}
        className="flex max-w-(--size-prose) flex-col gap-6"
        aria-busy={busy || undefined}
      >
        <Group legend={s.monitoring}>
          <NumberField control={form.control} name="ping_interval_sec" readOnly={busy} />
          <NumberField control={form.control} name="issue_check_interval_sec" readOnly={busy} />
          <NumberField control={form.control} name="confirm_interval_sec" readOnly={busy} />
        </Group>

        <Group legend={s.retention}>
          <RetentionSection control={form.control} readOnly={busy || retentionReason !== null} savedDays={settings.log_retention_days} />
        </Group>

        <Group legend={s.startType}>
          <FormField
            control={form.control}
            name="service_start_type"
            render={({ field }) => (
              <FormItem className="@lg:col-span-2">
                <FormLabel className="sr-only">{s.fields.service_start_type}</FormLabel>
                <Select value={field.value} onValueChange={field.onChange} disabled={busy}>
                  <FormControl>
                    <SelectTrigger className="w-full @lg:w-72" onBlur={field.onBlur}>
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {START_TYPES.map((t) => (
                      <SelectItem key={t} value={t}>
                        {s.startTypes[t]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormDescription>{s.startTypeNote}</FormDescription>
              </FormItem>
            )}
          />
        </Group>

        <Group legend={s.otp}>
          <p className="text-sm text-fg @lg:col-span-2">{s.otpDummy}</p>
        </Group>

        <Group legend={s.alerts}>
          <div className="@lg:col-span-2">
            <PlannedFeature reason="planned_alerts" />
          </div>
        </Group>

        {serverError ? (
          <p role="alert" className="text-sm text-danger">
            {serverError}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <Button ref={saveButton} type="submit" aria-disabled={canSave ? undefined : true}>
            {isSubmitting && !saving ? s.checking : busy ? copy.common.saving : copy.common.save}
          </Button>
          <Button
            variant="outline"
            aria-disabled={isDirty && !busy ? undefined : true}
            onClick={() => {
              if (isDirty && !busy) form.reset(serverValues);
            }}
          >
            {s.discard}
          </Button>
        </div>
      </form>

      <RetentionConfirm
        change={change?.retention ?? null}
        open={confirmOpen}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false);
          if (change) void save(change.patch);
        }}
        returnFocus={() => saveButton.current?.focus()}
      />
      <LeaveGuard when={isDirty && !saving} />
    </Form>
  );
}

function Group({ legend, children }: { legend: string; children: ReactNode }) {
  return (
    <fieldset className="@container flex flex-col gap-3 border-t border-border pt-4">
      <legend className="pr-2 text-sm font-semibold text-fg">{legend}</legend>
      <div className="grid gap-4 @lg:grid-cols-2">{children}</div>
    </fieldset>
  );
}
