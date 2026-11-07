// The sessions screen's period (`?days=`): shared by the route's search validation and the page,
// kept out of both so the lazy page chunk does not import the router module.

export type SessionDays = 1 | 7 | 30 | 90;
export const SESSION_DAYS: readonly SessionDays[] = [1, 7, 30, 90];
/** The period when the URL has none (the server's default too). */
export const DEFAULT_DAYS: SessionDays = 7;

/** A `?days=` value from the URL (TanStack parses it to a number) as a known period, else undefined. */
export function parseDays(v: unknown): SessionDays | undefined {
  const n = typeof v === "number" ? v : typeof v === "string" ? Number(v) : NaN;
  return SESSION_DAYS.find((d) => d === n);
}
