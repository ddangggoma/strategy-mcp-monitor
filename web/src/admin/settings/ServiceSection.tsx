import { TriangleAlertIcon } from "lucide-react";
import { copy } from "@/copy/ko";
import type { ServiceStatus } from "@/lib/api-types";
import { useServiceStatus } from "../queries";

function statusLines(st: ServiceStatus): { text: string; warn?: boolean }[] {
  const s = copy.settings.service;
  if (!st.installed || st.start_type === null) {
    // a bundle (or the service itself) can be installed; a development run never is (F20)
    return [{ text: st.bundle || st.running_as_service ? s.notInstalled : s.devMode }];
  }
  if (st.start_type === "disabled") {
    // an admin's decision in the SCM: the server leaves it alone (plan review minor 17)
    return [{ text: s.current(st.start_type) }, { text: s.disabled, warn: true }];
  }
  return [{ text: s.current(st.start_type) }, ...(st.in_sync ? [] : [{ text: s.mismatch, warn: true }])];
}

/**
 * What the Windows service's start type is now, next to the setting (GET /api/service, Local and
 * edit_global_settings only: the settings page never renders on the external channel). Replaces
 * Plan 3's "only stored for now" note.
 */
export function ServiceSection() {
  const { data, isPending, isError } = useServiceStatus();
  let body;
  if (isPending) body = <p role="status">{copy.common.loading}</p>;
  else if (isError) body = <p role="alert">{copy.settings.service.loadError}</p>;
  else {
    body = statusLines(data).map((l) =>
      l.warn ? (
        <p key={l.text} className="flex items-start gap-1.5 text-fg">
          <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-state-suspect" />
          {l.text}
        </p>
      ) : (
        <p key={l.text}>{l.text}</p>
      ),
    );
  }
  return (
    <dl className="flex flex-col gap-1 text-sm text-fg-muted @lg:col-span-2">
      <dt className="font-medium text-fg">{copy.settings.service.title}</dt>
      <dd className="flex flex-col gap-1">{body}</dd>
    </dl>
  );
}
