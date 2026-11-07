import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useId, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { copy, messageForError } from "@/copy/ko";
import { ApiError } from "@/lib/api";
import { bootstrap } from "@/lib/endpoints";
import { qk } from "../query-keys";
import { AuthFrame } from "./AuthFrame";

interface FieldErrors {
  email?: string;
  name?: string;
}

/**
 * First run on the local channel (the route only opens while `GET /api/bootstrap` says `needed`):
 * the first Admin's email and name, then login with that email filled in.
 */
export function SetupPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const ids = { email: useId(), emailError: useId(), name: useId(), nameError: useId() };
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [alert, setAlert] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const body = { email: email.trim(), name: name.trim() };
    const missing: FieldErrors = {
      email: body.email === "" ? copy.errors.invalid_email : undefined,
      name: body.name === "" ? copy.setup.nameRequired : undefined,
    };
    if (missing.email || missing.name) {
      setErrors(missing);
      return;
    }
    setBusy(true);
    setAlert(null);
    try {
      await bootstrap(body);
      qc.setQueryData(qk.bootstrap, { needed: false });
      await navigate({ to: "/admin/login", search: { email: body.email }, state: { flash: "setup_done" } });
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "network";
      if (code === "bootstrap_done") {
        // another tab (or person) created the first Admin a moment ago
        qc.setQueryData(qk.bootstrap, { needed: false });
        await navigate({ to: "/admin/login", state: { flash: "bootstrap_done" } });
      } else if (code === "invalid_email") {
        setErrors({ email: copy.errors.invalid_email });
      } else {
        setAlert(messageForError(code));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame>
      <div className="flex flex-col gap-2">
        <h1 className="text-xl font-semibold text-fg">{copy.setup.title}</h1>
        <p className="text-sm text-fg-muted">{copy.setup.lead}</p>
      </div>
      {alert ? (
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-fg">
          {alert}
        </p>
      ) : null}
      <form noValidate onSubmit={(e) => void onSubmit(e)} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={ids.email}>{copy.setup.email}</Label>
          <Input
            id={ids.email}
            type="email"
            autoComplete="email"
            spellCheck={false}
            maxLength={320}
            placeholder={copy.login.emailPlaceholder}
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setErrors((x) => ({ ...x, email: undefined }));
            }}
            aria-invalid={errors.email ? true : undefined}
            aria-describedby={errors.email ? ids.emailError : undefined}
          />
          {errors.email ? (
            <p id={ids.emailError} className="text-sm text-danger">
              {errors.email}
            </p>
          ) : null}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={ids.name}>{copy.setup.name}</Label>
          <Input
            id={ids.name}
            autoComplete="name"
            maxLength={100}
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setErrors((x) => ({ ...x, name: undefined }));
            }}
            aria-invalid={errors.name ? true : undefined}
            aria-describedby={errors.name ? ids.nameError : undefined}
          />
          {errors.name ? (
            <p id={ids.nameError} className="text-sm text-danger">
              {errors.name}
            </p>
          ) : null}
        </div>
        <Button type="submit" aria-busy={busy || undefined}>
          {busy ? copy.setup.submitting : copy.setup.submit}
        </Button>
      </form>
    </AuthFrame>
  );
}
