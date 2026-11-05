import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { WithReason } from "@/components/app/WithReason";
import { Button } from "@/components/ui/button";
import { Form } from "@/components/ui/form";
import { copy, messageForError } from "@/copy/ko";
import { ApiError } from "@/lib/api";
import type { McpConfig, McpDetail } from "@/lib/api-types";
import { denyReason } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { useUpdateMcp } from "../queries";
import { McpConfigFields } from "./McpConfigFields";
import { dirtyPatch, mcpConfigSchema, type McpFormValues } from "./mcp-schema";

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

        <McpConfigFields control={form.control} readOnly={readOnly} nameError={errors.name !== undefined} />

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
