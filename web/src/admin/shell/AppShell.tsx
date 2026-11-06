import { useQueryClient } from "@tanstack/react-query";
import { Outlet, useRouter } from "@tanstack/react-router";
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { TopBar } from "@/components/app/TopBar";
import { toast } from "sonner";
import { Toaster } from "@/components/ui/sonner";
import { copy } from "@/copy/ko";
import { ActionTracker } from "@/lib/action-tracker";
import { clearAllDrafts } from "@/lib/draft";
import { logout, mcpHistory } from "@/lib/endpoints";
import { clearSession, refreshSession, session, useSession } from "@/lib/session";
import { LiveProvider, useLive, useStreamStatus } from "../live";
import { sonnerActionToasts } from "../mcps/action-toasts";
import { Nav } from "./Nav";

const loadPalette = () => import("./CommandPalette");
const CommandPalette = lazy(() => loadPalette().then((m) => ({ default: m.CommandPalette })));

const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);

function isPaletteShortcut(e: KeyboardEvent): boolean {
  if (e.isComposing || e.altKey || e.shiftKey) return false;
  if (!(IS_MAC ? e.metaKey : e.ctrlKey)) return false;
  return e.code === "KeyK" || e.key.toLowerCase() === "k"; // code: Korean IME mode still reports KeyK
}

/** The focused element, or null when focus is nowhere in particular (<body>). */
function focusedElement(): Element | null {
  const el = document.activeElement;
  return el && el !== document.body ? el : null;
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
  const live = useLive();
  const { store, stream } = live;
  // one tracker per logged-in tab: toasts for the manual actions started here (U29)
  const [tracker] = useState(() => new ActionTracker({ toasts: sonnerActionToasts(), fetchHistory: (id) => mcpHistory(id, 1) }));
  const shellLive = useMemo(() => ({ ...live, tracker }), [live, tracker]);
  const status = useStreamStatus(store);
  const [palette, setPalette] = useState({ open: false, mounted: false });
  const leaving = useRef(false);

  // what had focus when the palette opened: Radix hands focus back to it on close, but a palette
  // opened by the shortcut with nothing focused would hand it to <body> (start of the page)
  const paletteOpener = useRef<Element | null>(null);
  const paletteOpen = useRef(false);
  useEffect(() => {
    paletteOpen.current = palette.open;
  }, [palette.open]);

  const openPalette = useCallback(() => {
    paletteOpener.current = focusedElement();
    setPalette({ open: true, mounted: true });
  }, []);
  const setPaletteOpen = useCallback((open: boolean) => setPalette((p) => ({ ...p, open })), []);
  const onPaletteCloseFocus = useCallback((e: Event) => {
    e.preventDefault();
    const opener = paletteOpener.current;
    // back to the opener; without one (or once a navigation removed it) to the page content
    if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    else document.getElementById("main")?.focus();
  }, []);

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
    // another tab put a different user in the shared cookie (session_changed): a user switch. The
    // previous user's edits leave the screen and storage, past any unsaved-changes blocker, so the
    // next save cannot store them as the new user's; the new user starts on the dashboard.
    const handler = () => {
      clearAllDrafts();
      stream.restart(); // the stream keeps the user it connected as
      toast.error(copy.errors.session_changed, { id: "session_changed" });
      // nothing read as the previous user stays: every query starts over, the open ones as the new user
      void router.navigate({ to: "/admin", ignoreBlocker: true }).finally(() => void qc.resetQueries());
    };
    session.onSessionChanged = handler;
    return () => {
      if (session.onSessionChanged === handler) session.onSessionChanged = null;
    };
  }, [qc, router, stream]);

  useEffect(() => {
    tracker.activate();
    const offAction = store.onAction(tracker.handle);
    const offReconnected = store.onReconnected(() => void tracker.reconcile()); // events may have been missed
    return () => {
      offAction();
      offReconnected();
      tracker.dispose();
      // Sonner keeps toasts globally and replays them to the next Toaster: a pending toast nobody
      // tracks any more would spin forever after logging in again
      toast.dismiss();
    };
  }, [store, tracker]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!isPaletteShortcut(e)) return;
      e.preventDefault();
      if (!paletteOpen.current) paletteOpener.current = focusedElement();
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
    clearAllDrafts(); // a deliberate logout: the next person on this tab must not find these edits
    stream.restart();
    try {
      // past any unsaved-changes blocker: logging out is the deliberate discard (drafts are gone),
      // and the shell unmounts with the session, so a blocker's dialog could never answer
      await router.navigate({ to: "/admin/login", ignoreBlocker: true });
    } finally {
      qc.clear(); // the next person to log in on this tab sees nothing of this one
    }
  }, [qc, router, stream]);

  if (!me?.user) return null; // between a 401 and the login page

  return (
    <LiveProvider value={shellLive}>
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
          <CommandPalette open={palette.open} onOpenChange={setPaletteOpen} onCloseAutoFocus={onPaletteCloseFocus} />
        </Suspense>
      ) : null}
      <Toaster position="bottom-right" />
    </LiveProvider>
  );
}
