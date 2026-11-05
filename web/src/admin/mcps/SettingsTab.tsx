import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo, type ReactNode } from "react";
import { useForm, type Control, type FieldPath } from "react-hook-form";
import { toast } from "sonner";
import { WithReason } from "@/components/app/WithReason";
import { Button } from "@/components/ui/button";
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { copy, messageForError } from "@/copy/ko";
import { ApiError } from "@/lib/api";
import type { McpConfig, McpDetail } from "@/lib/api-types";
import { denyReason } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { useUpdateMcp } from "../queries";
import { RANGES, dirtyPatch, mcpConfigSchema, type McpFormValues } from "./mcp-schema";

type NumberKey = keyof typeof RANGES;
type SwitchKey = "auto_recovery" | "autostart_on_boot" | "maintenance";

const PROBES = ["mcp_ping", "tcp", "icmp"] as const;

/** The server's config as form values (an absent process name is an empty input). */
function toValues(m: McpDetail): McpFormValues {
  return {
    name: m.name,
    host: m.host,
    port: m.port,
    path: m.path,
    probe: m.probe,
    expected_process_name: m.expected_process_name ?? "",
    action_delay_sec: m.action_delay_sec,
    startup_grace_sec: m.startup_grace_sec,
    max_auto_actions: m.max_auto_actions,
    window_sec: m.window_sec,
    auto_recovery: m.auto_recovery,
    autostart_on_boot: m.autostart_on_boot,
    maintenance: m.maintenance,
    script_timeout_sec: m.script_timeout_sec,
  };
}

/**
 * The MCP's settings as one form (U27). Defaults are the server's values; when the server's values
 * change (an SSE `mcp` event, another person's save) only the fields this person has not touched
 * take the new value. Save sends only the dirty fields. Without `edit_mcp_settings` every input is
 * read-only and the save button says why.
 */
export function SettingsTab({ mcp, onDirtyChange }: { mcp: McpDetail; onDirtyChange?: (dirty: boolean) => void }) {
  const me = useSession();
  const reason = denyReason(me, "edit_mcp_settings");
  const update = useUpdateMcp(mcp.id);

  // the detail object changes with every live board event; the config only when a setting does
  const serverKey = JSON.stringify(toValues(mcp));
  const serverValues = useMemo(() => JSON.parse(serverKey) as McpFormValues, [serverKey]);

  const form = useForm<McpFormValues, unknown, McpConfig>({
    resolver: zodResolver(mcpConfigSchema),
    defaultValues: serverValues,
  });
  const { isDirty, isSubmitting, dirtyFields, errors } = form.formState;

  useEffect(() => {
    form.reset(serverValues, { keepDirtyValues: true });
  }, [form, serverValues]);

  // an unmonitored MCP (saved config fails validation): point at the bad fields right away
  const configError = mcp.config_error;
  useEffect(() => {
    if (configError) void form.trigger();
  }, [form, configError]);

  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [onDirtyChange, isDirty]);

  const readOnly = reason !== null || isSubmitting;
  const canSave = reason === null && isDirty && !isSubmitting;

  const onValid = async (values: McpConfig) => {
    const patch = dirtyPatch(values, dirtyFields);
    if (Object.keys(patch).length === 0) return;
    try {
      const saved = await update.mutateAsync(patch);
      form.reset(toValues(saved));
      toast.success(copy.common.saved);
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "internal";
      if (code === "name_taken" || code === "endpoint_taken") {
        const field = code === "name_taken" ? "name" : "port";
        form.setError(field, { type: "server", message: copy.errors[code] }, { shouldFocus: true });
      } else {
        form.setError("root.server", { type: "server", message: messageForError(code) });
      }
    }
  };

  const submit = form.handleSubmit(onValid);
  const serverError = errors.root?.server?.message;

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
        aria-busy={isSubmitting || undefined}
      >
        <p className="text-sm text-fg-muted">{copy.mcp.liveNote}</p>

        <Group legend={copy.mcp.groups.connection}>
          <TextField control={form.control} name="name" label={copy.mcp.fields.name} readOnly={readOnly}
            hint={errors.name ? undefined : copy.mcp.nameRule} />
          <TextField control={form.control} name="host" label={copy.mcp.fields.host} readOnly={readOnly} mono />
          <NumberField control={form.control} name="port" readOnly={readOnly} />
          <TextField control={form.control} name="path" label={copy.mcp.fields.path} readOnly={readOnly} mono />
          <FormField
            control={form.control}
            name="probe"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{copy.mcp.fields.probe}</FormLabel>
                <Select value={field.value} onValueChange={field.onChange} disabled={readOnly}>
                  <FormControl>
                    <SelectTrigger className="w-full" onBlur={field.onBlur}>
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {PROBES.map((p) => (
                      <SelectItem key={p} value={p}>
                        {copy.mcp.probes[p]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
          <TextField control={form.control} name="expected_process_name" label={copy.mcp.fields.expected_process_name}
            readOnly={readOnly} mono hint={copy.mcp.processNameHint} />
        </Group>

        <Group legend={copy.mcp.groups.recovery}>
          <SwitchField control={form.control} name="auto_recovery" readOnly={readOnly} className="@lg:col-span-2" />
          <NumberField control={form.control} name="action_delay_sec" readOnly={readOnly} />
          <NumberField control={form.control} name="startup_grace_sec" readOnly={readOnly} />
          <NumberField control={form.control} name="max_auto_actions" readOnly={readOnly} hint={copy.mcp.hints.max_auto_actions} />
          <NumberField control={form.control} name="window_sec" readOnly={readOnly} />
          <NumberField control={form.control} name="script_timeout_sec" readOnly={readOnly} />
        </Group>

        <Group legend={copy.mcp.groups.operation}>
          <SwitchField control={form.control} name="maintenance" readOnly={readOnly} className="@lg:col-span-2" />
          <SwitchField control={form.control} name="autostart_on_boot" readOnly={readOnly} className="@lg:col-span-2" />
        </Group>

        {serverError ? (
          <p role="alert" className="text-sm text-danger">
            {serverError}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <WithReason reason={reason}>
            <Button type="submit" aria-disabled={canSave ? undefined : true}>
              {isSubmitting ? copy.common.saving : copy.common.save}
            </Button>
          </WithReason>
          <Button
            variant="outline"
            aria-disabled={isDirty && !isSubmitting ? undefined : true}
            onClick={() => {
              if (isDirty && !isSubmitting) form.reset(serverValues);
            }}
          >
            {copy.mcp.discard}
          </Button>
        </div>
      </form>
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

interface FieldProps<K extends FieldPath<McpFormValues>> {
  control: Control<McpFormValues, unknown, McpConfig>;
  name: K;
  readOnly: boolean;
  hint?: string;
  className?: string;
}

function TextField({ control, name, label, readOnly, hint, mono }: FieldProps<"name" | "host" | "path" | "expected_process_name"> & {
  label: string;
  mono?: boolean;
}) {
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <FormControl>
            <Input
              {...field}
              value={field.value ?? ""}
              readOnly={readOnly}
              autoComplete="off"
              spellCheck={false}
              className={mono ? "font-mono" : undefined}
            />
          </FormControl>
          {hint ? <FormDescription>{hint}</FormDescription> : null}
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

/** An integer input: the form keeps a number, or "" for an empty box (the schema reports it). */
function NumberField({ control, name, readOnly, hint }: FieldProps<NumberKey>) {
  const [min, max] = RANGES[name];
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{copy.mcp.fields[name]}</FormLabel>
          <FormControl>
            <Input
              type="number"
              inputMode="numeric"
              min={min}
              max={max}
              step={1}
              name={field.name}
              ref={field.ref}
              onBlur={field.onBlur}
              value={field.value}
              onChange={(e) => field.onChange(e.target.value === "" ? "" : Number(e.target.value))}
              readOnly={readOnly}
              className="tabular-nums"
            />
          </FormControl>
          <FormDescription>{hint ? `${hint} ${copy.mcp.rangeHint(min, max)}` : copy.mcp.rangeHint(min, max)}</FormDescription>
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

function SwitchField({ control, name, readOnly, className }: FieldProps<SwitchKey>) {
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem className={className}>
          <div className="flex items-center gap-3">
            <FormControl>
              <Switch
                checked={field.value}
                onCheckedChange={(on) => {
                  if (!readOnly) field.onChange(on);
                }}
                onBlur={field.onBlur}
                ref={field.ref}
                aria-disabled={readOnly || undefined}
              />
            </FormControl>
            <FormLabel>{copy.mcp.fields[name]}</FormLabel>
          </div>
          {name in copy.mcp.hints ? <FormDescription>{copy.mcp.hints[name as keyof typeof copy.mcp.hints]}</FormDescription> : null}
        </FormItem>
      )}
    />
  );
}
