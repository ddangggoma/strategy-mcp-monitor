import { useId, type ReactNode } from "react";
import { copy } from "@/copy/ko";
import type { RdpSession } from "@/lib/api-types";
import { useClock } from "@/lib/clock";
import { formatKst, formatSeconds } from "@/lib/time";
import { cn } from "@/lib/utils";

const DASH = "—";
const f = copy.board.session.fields;

function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0", className)}>
      <dt className="text-xs text-fg-muted">{label}</dt>
      <dd className="truncate">{children}</dd>
    </div>
  );
}

const or = (v: string | null) => v ?? DASH;

function noticeText(ack: boolean | null): string {
  if (ack === null) return DASH;
  return ack ? copy.board.session.noticeYes : copy.board.session.noticeNo;
}

/**
 * One remote desktop session (§6.2): every field, the client IP in full (a machine value, mono),
 * "—" for anything not reported. Elapsed time counts on the shared 1 s clock.
 */
export function SessionCard({ session, className }: { session: RdpSession; className?: string }) {
  const id = useId();
  const { wall } = useClock();
  const since = session.connected_at ?? session.logon_at;
  const elapsed = since === null ? null : (wall - Date.parse(since)) / 1000;

  return (
    <article
      aria-labelledby={id}
      className={cn("@container rounded-md border border-border bg-surface p-4", className)}
    >
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm @md:grid-cols-3">
        <Field label={f.user} className="col-span-full">
          <span id={id} className="text-lg font-semibold">
            {session.user}
          </span>
        </Field>
        <Field label={f.domain}>{or(session.domain)}</Field>
        <Field label={f.clientName}>{or(session.client_name)}</Field>
        <Field label={f.clientIp}>
          <span className="font-mono">{or(session.client_ip)}</span>
        </Field>
        <Field label={f.reverseDns}>
          <span className={session.reverse_dns ? "font-mono" : undefined}>{or(session.reverse_dns)}</span>
        </Field>
        <Field label={f.connectedAt}>
          {since === null ? DASH : <time dateTime={since}>{formatKst(since)}</time>}
        </Field>
        <Field label={f.elapsed}>
          <span data-testid="session-elapsed" data-volatile="" data-numeric="">
            {formatSeconds(elapsed)}
          </span>
        </Field>
        <Field label={f.state}>{session.state}</Field>
        <Field label={f.idle}>
          <span data-volatile="" data-numeric="">
            {formatSeconds(session.idle_sec)}
          </span>
        </Field>
        <Field label={f.resolution}>{or(session.resolution)}</Field>
        <Field label={f.notice}>{noticeText(session.notice_acknowledged)}</Field>
      </dl>
    </article>
  );
}
