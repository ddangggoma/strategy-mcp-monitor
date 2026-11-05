import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useRouterState, useSearch } from "@tanstack/react-router";
import { FlaskConicalIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { copy, messageForError } from "@/copy/ko";
import { ApiError } from "@/lib/api";
import { otpRequest, otpVerify } from "@/lib/endpoints";
import { documentNav, isAdminPath, safeRedirect } from "@/lib/redirect";
import { setSessionFromLogin, useSession } from "@/lib/session";
import { useLive } from "../live";
import type { LoginFlash } from "../router";
import { AuthFrame } from "./AuthFrame";
import { OTP_LENGTH, OtpInput } from "./OtpInput";
import { ResendRing } from "./ResendRing";

/** Wait before another code may be requested (server: 60 s per-email cooldown). */
export const RESEND_SECONDS = 60;
/** Wrong entries after which the server voids a code. */
export const MAX_CODE_FAILURES = 5;

type Step = "email" | "code";

/** Why the user is on this page (history state, set by setup and by the shell on a 401). */
const FLASH_TEXT: Record<LoginFlash, string> = {
  setup_done: copy.setup.done,
  bootstrap_done: copy.errors.bootstrap_done,
  expired: copy.errors.login_required,
};

interface Ring {
  seconds: number;
  startedAt: number;
}

/** Message for a 429: a long Retry-After is a lock (email lock and IP limit read the same, U7). */
function rateLimitMessage(e: ApiError): string {
  if (e.retryAfterSec !== null && e.retryAfterSec > RESEND_SECONDS) return copy.login.lockedFor(Math.ceil(e.retryAfterSec / 60));
  return messageForError("rate_limited");
}

/**
 * Two steps: email → 6-digit code (spec §6.3, docs/design/screens/auth-shell.md). The code step
 * shows the per-code failure count and the 10-per-hour rule from the first failure; after 5 the
 * code is void and only a new one helps. Success restarts the live stream (it keeps the auth level
 * it connected with) and returns to `redirect`.
 */
export function LoginPage() {
  const search = useSearch({ from: "/admin/login" });
  const flash = useRouterState({ select: (s) => s.location.state.flash });
  const router = useRouter();
  const qc = useQueryClient();
  const { stream } = useLive();
  const me = useSession();
  const ids = { email: useId(), emailError: useId(), ring: useId(), sent: useId() };

  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState(search.email ?? "");
  const [sentTo, setSentTo] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [alert, setAlert] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [ring, setRing] = useState<Ring | null>(null);
  const [code, setCode] = useState("");
  const [invalid, setInvalid] = useState(false);
  const [failures, setFailures] = useState(0);
  const [verifying, setVerifying] = useState(false);
  const emailInput = useRef<HTMLInputElement>(null);
  const resendButton = useRef<HTMLButtonElement>(null);
  const cameBack = useRef(false);

  const dev = me?.otp_provider === "dummy";
  const exhausted = failures >= MAX_CODE_FAILURES;

  useEffect(() => {
    if (step === "email" && cameBack.current) emailInput.current?.focus();
  }, [step]);

  // a void code disables the cells: keep focus on the way out (a new code), not on <body>
  useEffect(() => {
    if (exhausted) resendButton.current?.focus();
  }, [exhausted]);

  const startCodeStep = (address: string, seconds: number) => {
    setSentTo(address);
    setStep("code");
    setRing({ seconds, startedAt: performance.now() });
    setCode("");
    setInvalid(false);
    setFailures(0);
  };

  const requestCode = async (address: string) => {
    if (sending) return;
    if (address === "") {
      setEmailError(copy.errors.invalid_email);
      emailInput.current?.focus(); // the error is the field's description: read on focus
      return;
    }
    setSending(true);
    setAlert(null);
    setEmailError(null);
    try {
      await otpRequest(address);
      startCodeStep(address, RESEND_SECONDS);
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, "network");
      if (err.status === 429 && err.retryAfterSec !== null && err.retryAfterSec <= RESEND_SECONDS) {
        startCodeStep(address, err.retryAfterSec); // a code was sent moments ago (F05)
      } else if (err.status === 429) {
        setAlert(rateLimitMessage(err));
      } else if (err.status === 422 && step === "email") {
        setEmailError(messageForError(err.code));
        emailInput.current?.focus();
      } else {
        setAlert(messageForError(err.code));
      }
    } finally {
      setSending(false);
    }
  };

  const goTo = (target: string) => {
    if (isAdminPath(target)) void router.navigate({ href: target, replace: true });
    else documentNav.assign(target); // the board and /notice are other HTML entries (F11)
  };

  const verify = async (value: string) => {
    if (verifying || exhausted || value.length !== OTP_LENGTH) return;
    setVerifying(true);
    setAlert(null);
    try {
      const r = await otpVerify(sentTo, value);
      setSessionFromLogin(r.user, r.csrf_token);
      qc.clear(); // nothing cached for whoever used this tab before
      stream.restart();
      goTo(safeRedirect(search.redirect));
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, "network");
      if (err.status === 401) {
        setFailures((n) => n + 1);
        setInvalid(true);
      } else if (err.status === 429) {
        setAlert(rateLimitMessage(err));
      } else {
        setAlert(messageForError(err.code));
      }
    } finally {
      setVerifying(false);
    }
  };

  const onEmailSubmit = (e: FormEvent) => {
    e.preventDefault();
    void requestCode(email.trim());
  };

  const onCodeSubmit = (e: FormEvent) => {
    e.preventDefault();
    void verify(code);
  };

  const changeEmail = () => {
    cameBack.current = true;
    setStep("email");
    setAlert(null);
    setRing(null);
  };

  return (
    <AuthFrame>
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h1 className="text-xl font-semibold text-fg">{copy.login.title}</h1>
          {dev ? (
            <Badge variant="outline">
              <FlaskConicalIcon aria-hidden="true" />
              {copy.login.devBadge}
            </Badge>
          ) : null}
        </div>
        <p className="text-sm text-fg-muted">{copy.login.lead}</p>
      </div>

      {alert ? (
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-fg">
          {alert}
        </p>
      ) : null}

      {step === "email" ? (
        <form noValidate onSubmit={onEmailSubmit} className="flex flex-col gap-4">
          {flash ? (
            <p role="status" className="text-sm text-fg">
              {FLASH_TEXT[flash]}
            </p>
          ) : null}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={ids.email}>{copy.login.email}</Label>
            <Input
              ref={emailInput}
              id={ids.email}
              type="email"
              autoComplete="username"
              spellCheck={false}
              maxLength={320}
              placeholder={copy.login.emailPlaceholder}
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setEmailError(null);
              }}
              aria-invalid={emailError ? true : undefined}
              aria-describedby={emailError ? ids.emailError : undefined}
            />
            {emailError ? (
              <p id={ids.emailError} className="text-sm text-danger">
                {emailError}
              </p>
            ) : null}
          </div>
          <Button type="submit" aria-busy={sending || undefined}>
            {sending ? copy.login.sendingCode : copy.login.sendCode}
          </Button>
          <p className="text-xs text-fg-muted">{copy.login.unknownEmailNote}</p>
        </form>
      ) : (
        <form noValidate onSubmit={onCodeSubmit} className="flex flex-col gap-4">
          <p id={ids.sent} role="status" className="text-sm text-fg">
            {copy.login.codeSent(sentTo)}
          </p>
          <OtpInput
            value={code}
            onChange={(v) => {
              setCode(v);
              if (v !== "") setInvalid(false);
            }}
            onComplete={(v) => void verify(v)}
            invalid={invalid}
            disabled={verifying || exhausted}
            describedBy={ids.sent}
          />
          {failures > 0 ? (
            <div role="alert" className="flex flex-col gap-1 text-sm">
              {exhausted ? (
                <p className="font-medium text-danger">{copy.login.codeExhausted}</p>
              ) : (
                <>
                  <p className="font-medium text-danger">{copy.login.wrongCode}</p>
                  <p className="text-fg">{copy.login.failedCount(failures)}</p>
                </>
              )}
              <p className="text-fg-muted">{copy.login.failureHint}</p>
            </div>
          ) : null}
          <Button type="submit" disabled={verifying || exhausted} aria-busy={verifying || undefined}>
            {verifying ? copy.login.verifying : copy.login.verify}
          </Button>
          <div className="flex flex-wrap items-center justify-between gap-3">
            {ring ? <ResendRing id={ids.ring} seconds={ring.seconds} startedAt={ring.startedAt} onDone={() => setRing(null)} /> : null}
            <Button
              ref={resendButton}
              variant="outline"
              className="ms-auto"
              aria-disabled={ring ? true : undefined}
              aria-describedby={ring ? ids.ring : undefined}
              aria-busy={sending || undefined}
              onClick={() => {
                if (!ring) void requestCode(sentTo);
              }}
            >
              {copy.login.resend}
            </Button>
          </div>
          <Button variant="link" className="self-start px-0" onClick={changeEmail}>
            {copy.login.changeEmail}
          </Button>
          {dev ? <p className="text-xs text-fg-muted">{copy.login.devHint}</p> : null}
        </form>
      )}
    </AuthFrame>
  );
}
