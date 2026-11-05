import { setupServer } from "msw/node";
import { handlers } from "./handlers";

export const server = setupServer(...handlers);

/** Starts recording request paths; listeners are removed after each test (tests/setup.ts). */
export function trackRequests(): { paths(): string[] } {
  const seen: string[] = [];
  server.events.on("request:start", ({ request }) => {
    seen.push(new URL(request.url).pathname);
  });
  return { paths: () => [...seen] };
}
