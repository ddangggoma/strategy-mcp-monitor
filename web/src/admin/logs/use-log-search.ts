// The logs route's URL state (W34) and the one way the log screen changes it.
import { getRouteApi } from "@tanstack/react-router";
import { useCallback } from "react";
import type { LogSearch } from "./search";

const route = getRouteApi("/authed/admin/logs");

export const useLogSearch = route.useSearch;

/** Only the keys that hold a value: a dropped filter leaves the URL instead of lingering as `undefined`. */
function clean(s: LogSearch): LogSearch {
  return Object.fromEntries(
    Object.entries(s).filter(([, v]) => v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0)),
  ) as LogSearch;
}

export type LogSearchPatch = Partial<LogSearch> | ((s: LogSearch) => Partial<LogSearch>);

/**
 * Changes the URL search of the logs page. Search-only changes never run the router's view
 * transition (F16: no animation in the log area, and this happens hundreds of times a day);
 * `replace` keeps typed filters from piling up history entries.
 */
export function useLogNavigate() {
  const navigate = route.useNavigate();
  return useCallback(
    (patch: LogSearchPatch, opts: { replace?: boolean } = {}) =>
      void navigate({
        search: (s: LogSearch) => clean({ ...s, ...(typeof patch === "function" ? patch(s) : patch) }),
        viewTransition: false,
        replace: opts.replace,
      }),
    [navigate],
  );
}
