import { setupServer } from "msw/node";
import { handlers } from "./handlers";

export const server = setupServer(...handlers);

/** Starts recording requests; listeners are removed after each test (tests/setup.ts). */
export function trackRequests(): { paths(): string[]; urls(): string[] } {
  const seen: URL[] = [];
  server.events.on("request:start", ({ request }) => {
    seen.push(new URL(request.url));
  });
  return {
    /** Paths only, in request order. */
    paths: () => seen.map((u) => u.pathname),
    /** Path and query, in request order (array parameters repeat their key). */
    urls: () => seen.map((u) => u.pathname + u.search),
  };
}
