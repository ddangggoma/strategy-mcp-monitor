import { GlobeIcon, MonitorIcon, TriangleAlertIcon, type LucideIcon } from "lucide-react";
import { useId, type ReactNode } from "react";
import { InfoTip, type HelpContent } from "@/components/app/InfoTip";
import { copy } from "@/copy/ko";
import type { RdpSession } from "@/lib/api-types";
import { useClock } from "@/lib/clock";
import { formatKst, formatSeconds } from "@/lib/time";
import { cn } from "@/lib/utils";

const DASH = "—";
const f = copy.sessions.fields;

function Field({ label, tip, children, className }: { label: string; tip?: HelpContent; children: ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0", className)}>
      <dt className={cn("text-xs text-fg-muted", tip && "flex items-center gap-0.5")}>
        {label}
        {tip ? <InfoTip label={label} content={tip} /> : null}
      </dt>
      <dd className="truncate">{children}</dd>
    </div>
  );
}

const or = (v: string | null) => v ?? DASH;

const RESOLUTION = /^(\d+)x(\d+)(?:@(\d+))?$/;

/** `"1920x1080@32"` (or without `@bits`) in words; any other form is shown as it came. */
function formatResolution(value: string | null): string {
  if (value === null) return DASH;
  const m = RESOLUTION.exec(value);
  if (!m) return value;
  return copy.sessions.resolution(Number(m[1]), Number(m[2]), m[3] === undefined ? null : Number(m[3]));
}

/** Whole minutes from one minute; the server resends idle time only when the minute changes (V10). */
function formatIdle(sec: number | null): string {
  return sec === null || sec < 60 ? DASH : copy.sessions.idle(Math.floor(sec / 60));
}

/** A fact worth a second look (first time this IP / device was seen): icon + words, neutral ink. */
export function FactBadge({ icon: Icon, children }: { icon: LucideIcon; children: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-sm border border-border-strong px-1.5 text-xs font-medium leading-5">
      <Icon aria-hidden="true" className="size-3.5 shrink-0" />
      {children}
    </span>
  );
}

/** The one caution of a session row or card (amber = the suspect hue, the house warning colour): icon + words. */
export function Caution({ children }: { children: string }) {
  return (
    <span className="inline-flex items-center gap-1 font-medium text-state-suspect-fg">
      <TriangleAlertIcon aria-hidden="true" className="size-3.5 shrink-0 text-state-suspect" />
      {children}
    </span>
  );
}

function Notice({ ack }: { ack: boolean | null }) {
  if (ack === null) return <span className="text-fg-muted">{copy.sessions.noticeUnknown}</span>;
  if (ack) return <>{copy.sessions.noticeAcked}</>;
  return <Caution>{copy.sessions.noticePending}</Caution>; // not acknowledged yet
}

/**
 * One remote desktop session (§6.2): every field, the client IP in full (a machine value, mono),
 * "—" for anything not reported. Elapsed time counts on the shared 1 s clock; idle time is the
 * server's whole minutes. First-seen IP/device badges sit next to the user's name.
 */
export function SessionCard({ session, className }: { session: RdpSession; className?: string }) {
  const id = useId();
  const { wall } = useClock();
  const since = session.connected_at ?? session.logon_at;
  const elapsed = since === null ? null : (wall - Date.parse(since)) / 1000;
  const badges = session.first_seen_ip || session.first_seen_device;

  return (
    <article
      aria-labelledby={id}
      className={cn("@container rounded-md border border-border bg-surface p-4", className)}
    >
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm @md:grid-cols-3">
        <div className="col-span-full min-w-0">
          <dt className="text-xs text-fg-muted">{f.user}</dt>
          <dd className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            <span id={id} className="min-w-0 truncate text-lg font-semibold">
              {session.user}
            </span>
            {badges ? (
              <span className="flex flex-wrap gap-1.5">
                {session.first_seen_ip ? <FactBadge icon={GlobeIcon}>{copy.sessions.firstSeenIp}</FactBadge> : null}
                {session.first_seen_device ? <FactBadge icon={MonitorIcon}>{copy.sessions.firstSeenDevice}</FactBadge> : null}
              </span>
            ) : null}
          </dd>
        </div>
        <Field label={f.domain}>{or(session.domain)}</Field>
        <Field label={f.clientName}>{or(session.client_name)}</Field>
        <Field label={f.clientIp}>
          <span className="font-mono">{or(session.client_ip)}</span>
        </Field>
        <Field label={f.reverseDns} tip={copy.help.session.reverseDns}>
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
        <Field label={f.state} tip={copy.help.session.state}>{copy.sessions.state[session.state]}</Field>
        <Field label={f.idle} tip={copy.help.session.idle}>
          <span data-testid="session-idle" data-volatile="" data-numeric="">
            {formatIdle(session.idle_sec)}
          </span>
        </Field>
        <Field label={f.resolution}>
          <span data-testid="session-resolution">{formatResolution(session.resolution)}</span>
        </Field>
        <Field label={f.notice} tip={copy.help.session.notice}>
          <Notice ack={session.notice_acknowledged} />
        </Field>
      </dl>
    </article>
  );
}
