import type { ReactElement } from "react";
import type { Control } from "react-hook-form";
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  useFormField,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { copy } from "@/copy/ko";
import { SETTINGS_RANGES, type SettingsFormValues, type SettingsValues } from "./settings-schema";

export type SettingsControl = Control<SettingsFormValues, unknown, SettingsValues>;
type NumberKey = keyof typeof SETTINGS_RANGES;

/** One message drawn once for several fields (compress > retention), outside the fields. */
export interface SharedError {
  id: string;
  message: string;
}

/**
 * An integer setting: label, input, hint (the allowed range unless `hint` says otherwise) and its
 * error. When the field's error is the `shared` one, the field does not repeat it under itself but
 * still points its description at it.
 */
export function NumberField({
  control,
  name,
  readOnly,
  hint,
  shared,
}: {
  control: SettingsControl;
  name: NumberKey;
  readOnly: boolean;
  hint?: string;
  shared?: SharedError;
}) {
  const [min, max] = SETTINGS_RANGES[name];
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{copy.settings.fields[name]}</FormLabel>
          <FieldBody hint={hint ?? copy.mcp.rangeHint(min, max)} shared={shared}>
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
          </FieldBody>
        </FormItem>
      )}
    />
  );
}

/** The input (child), its hint and its own error; a shared error is pointed at, not repeated. */
function FieldBody({ hint, shared, children }: { hint: string; shared?: SharedError; children: ReactElement }) {
  const { error, formDescriptionId, formMessageId } = useFormField();
  const isShared = shared !== undefined && error?.message === shared.message;
  const describedBy = error ? `${formDescriptionId} ${isShared ? shared.id : formMessageId}` : formDescriptionId;

  return (
    <>
      <FormControl aria-describedby={describedBy}>{children}</FormControl>
      <FormDescription>{hint}</FormDescription>
      {isShared ? null : <FormMessage />}
    </>
  );
}
