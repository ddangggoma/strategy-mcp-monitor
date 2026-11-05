import type { ReactNode } from "react";
import type { Control, FieldPath } from "react-hook-form";
import { FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { copy } from "@/copy/ko";
import type { McpConfig } from "@/lib/api-types";
import { RANGES, type McpFormValues } from "./mcp-schema";

type NumberKey = keyof typeof RANGES;
type SwitchKey = "auto_recovery" | "autostart_on_boot" | "maintenance";

const PROBES = ["mcp_ping", "tcp", "icmp"] as const;

/**
 * Every McpConfig field in three fieldsets (connection and checks / auto recovery / operation),
 * shared by the settings tab and the registration page. The form, its schema and its submit
 * belong to the caller.
 */
export function McpConfigFields({
  control,
  readOnly,
  nameError,
}: {
  control: Control<McpFormValues, unknown, McpConfig>;
  readOnly: boolean;
  /** The name field shows its error instead of the naming rule. */
  nameError: boolean;
}) {
  return (
    <>
      <Group legend={copy.mcp.groups.connection}>
        <TextField control={control} name="name" label={copy.mcp.fields.name} readOnly={readOnly}
          hint={nameError ? undefined : copy.mcp.nameRule} />
        <TextField control={control} name="host" label={copy.mcp.fields.host} readOnly={readOnly} mono />
        <NumberField control={control} name="port" readOnly={readOnly} />
        <TextField control={control} name="path" label={copy.mcp.fields.path} readOnly={readOnly} mono />
        <FormField
          control={control}
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
        <TextField control={control} name="expected_process_name" label={copy.mcp.fields.expected_process_name}
          readOnly={readOnly} mono hint={copy.mcp.processNameHint} />
      </Group>

      <Group legend={copy.mcp.groups.recovery}>
        <SwitchField control={control} name="auto_recovery" readOnly={readOnly} className="@lg:col-span-2" />
        <NumberField control={control} name="action_delay_sec" readOnly={readOnly} />
        <NumberField control={control} name="startup_grace_sec" readOnly={readOnly} />
        <NumberField control={control} name="max_auto_actions" readOnly={readOnly} hint={copy.mcp.hints.max_auto_actions} />
        <NumberField control={control} name="window_sec" readOnly={readOnly} />
        <NumberField control={control} name="script_timeout_sec" readOnly={readOnly} />
      </Group>

      <Group legend={copy.mcp.groups.operation}>
        <SwitchField control={control} name="maintenance" readOnly={readOnly} className="@lg:col-span-2" />
        <SwitchField control={control} name="autostart_on_boot" readOnly={readOnly} className="@lg:col-span-2" />
      </Group>
    </>
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
