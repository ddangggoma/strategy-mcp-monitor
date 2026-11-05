import { useQueryClient } from "@tanstack/react-query";
import { Outlet, useRouter } from "@tanstack/react-router";
import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { TopBar } from "@/components/app/TopBar";
import { Toaster } from "@/components/ui/sonner";
import { copy } from "@/copy/ko";
import { logout } from "@/lib/endpoints";
import { clearSession, refreshSession, session, useSession } from "@/lib/session";
import { useLive, useStreamStatus } from "../live";
import { Nav } from "./Nav";

const loadPalette = () => import("./CommandPalette");
const CommandPalette = lazy(() => loadPalette().then((m) => ({ default: m.CommandPalette })));

const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);

function isPaletteShortcut(e: KeyboardEvent): boolean {
  if (e.isComposing || e.altKey || e.shiftKey) return false;
  if (!(IS_MAC ? e.metaKey : e.ctrlKey)) return false;
  return e.code === "KeyK" || e.key.toLowerCase() === "k"; // code: Korean IME mode still reports KeyK
}

/**
 * Logged-in admin layout: the shared TopBar (same store and stream as the rest of the tab), the
 * navigation, the page, toasts and the command palette. Owns the session-expired path: a 401
 * anywhere sends the user to login with the current address, past any unsaved-changes blocker
 * (F12: editors keep their drafts themselves), and restarts the stream at the anonymous level.
 */
export function AppShell() {
  const me = useSession();
  const router = useRouter();
  const qc = useQueryClient();
  const { store, stream } = useLive();
  const status = useStreamStatus(store);
  const [palette, setPalette] = useState({ open: false, mounted: false });
  const leaving = useRef(false);

  const openPalette = useCallback(() => setPalette({ open: true, mounted: true }), []);
  const setPaletteOpen = useCallback((open: boolean) => setPalette((p) => ({ ...p, open })), []);

  useEffect(() => {
    const handler = () => {
      if (leaving.current) return; // several requests can fail at once
      leaving.current = true;
      const { href } = router.state.location;
      clearSession();
      stream.restart(); // the stream keeps the auth level it connected with
      void router.navigate({ to: "/admin/login", search: { redirect: href }, state: { flash: "expired" }, ignoreBlocker: true });
    };
    session.onUnauthorized = handler;
    return () => {
      if (session.onUnauthorized === handler) session.onUnauthorized = null;
    };
  }, [router, stream]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!isPaletteShortcut(e)) return;
      e.preventDefault();
      setPalette((p) => ({ open: !p.open, mounted: true }));
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const onLogout = useCallback(async () => {
    try {
      await logout();
    } catch {
      await refreshSession().catch(() => {}); // still logged in: show what the server says
      return;
    }
    leaving.current = true;
    clearSession();
    stream.restart();
    await router.navigate({ to: "/admin/login" });
    qc.clear(); // the next person to log in on this tab sees nothing of this one
  }, [qc, router, stream]);

  if (!me?.user) return null; // between a 401 and the login page

  return (
    <>
      <a
        href="#main"
        className="sr-only rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-fg focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-(--z-tooltip)"
      >
        {copy.common.skipToContent}
      </a>
      <TopBar me={me} streamStatus={status} onLogout={onLogout} />
      <div className="grid grid-cols-[var(--size-sidebar)_minmax(0,1fr)] max-lg:grid-cols-[var(--size-rail)_minmax(0,1fr)]">
        <Nav me={me} onOpenPalette={openPalette} onPreloadPalette={() => void loadPalette()} shortcut={copy.common.commandShortcut(IS_MAC)} />
        <main id="main" tabIndex={-1} className="flex min-w-0 flex-col gap-6 px-6 py-6 outline-none">
          <Outlet />
        </main>
      </div>
      {palette.mounted ? (
        <Suspense fallback={null}>
          <CommandPalette open={palette.open} onOpenChange={setPaletteOpen} />
        </Suspense>
      ) : null}
      <Toaster position="bottom-right" />
    </>
  );
}
