// The audit route's URL state (W34) and the one way the audit screen changes it (same rules as the
// log screen: undefined and empty values leave the URL, no view transition on search changes).
import { getRouteApi } from "@tanstack/react-router";
import { useCallback } from "react";
import type { AuditSearch } from "../logs/search";

const route = getRouteApi("/authed/admin/audit");

export const useAuditSearch = route.useSearch;

function clean(s: AuditSearch): AuditSearch {
  return Object.fromEntries(
    Object.entries(s).filter(([, v]) => v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0)),
  ) as AuditSearch;
}

export type AuditSearchPatch = Partial<AuditSearch> | ((s: AuditSearch) => Partial<AuditSearch>);

export function useAuditNavigate() {
  const navigate = route.useNavigate();
  return useCallback(
    (patch: AuditSearchPatch, opts: { replace?: boolean } = {}) =>
      void navigate({
        search: (s: AuditSearch) => clean({ ...s, ...(typeof patch === "function" ? patch(s) : patch) }),
        viewTransition: false,
        replace: opts.replace,
      }),
    [navigate],
  );
}
