//! Out-of-context WinEvent hooks for foreground, minimize/restore and title changes (Python
//! `mcp_agent.hooks`).
//!
//! The hooks live on their own thread with a `GetMessageW` loop (out-of-context callbacks are
//! delivered through that thread's message queue). The callback stays light: three cheap Win32
//! reads, a per-pid image cache and a hand-off to `on_event`; nothing (an error or a panic) ever
//! escapes it. `WINEVENT_SKIPOWNPROCESS`: the agent's own windows (the notice window) are not
//! reported — `notice_shown` / `notice_acknowledged` cover them (F11).

use super::coalesce::{Kind, RawWinEvent};
use super::time;
use std::cell::RefCell;
use std::collections::HashMap;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicUsize, Ordering};
use std::sync::mpsc::{self, Receiver};
use std::sync::{Arc, Condvar, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

pub const EVENT_SYSTEM_FOREGROUND: u32 = 0x0003;
pub const EVENT_SYSTEM_MINIMIZESTART: u32 = 0x0016;
pub const EVENT_SYSTEM_MINIMIZEEND: u32 = 0x0017;
pub const EVENT_OBJECT_NAMECHANGE: u32 = 0x800C;
pub const WINEVENT_OUTOFCONTEXT: u32 = 0;
pub const WINEVENT_SKIPOWNPROCESS: u32 = 2;
pub const OBJID_WINDOW: i32 = 0;
pub const CHILDID_SELF: i32 = 0;
pub const HOOK_RANGES: [(u32, u32); 3] = [
    (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND),
    (EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND),
    (EVENT_OBJECT_NAMECHANGE, EVENT_OBJECT_NAMECHANGE),
];
/// A pid can be reused; a cached image path is not trusted for long.
pub const IMAGE_CACHE_SEC: f64 = 30.0;
pub const IMAGE_CACHE_MAX: usize = 512;
/// `QueryFullProcessImageNameW` buffer, in UTF-16 units (Python: 32768, F29).
pub const IMAGE_PATH_MAX: usize = 32768;
/// How long `stop` waits for the hook thread (to be ready, then to end).
pub const STOP_WAIT: Duration = Duration::from_secs(2);

/// The Win32 reads the callback makes, behind a trait for the tests.
pub trait WinApi: Send + Sync {
    /// The foreground window, or 0 (none, e.g. while the desktop is locked or switching).
    fn foreground(&self) -> isize;
    fn text(&self, hwnd: isize) -> String;
    fn pid_of(&self, hwnd: isize) -> u32;
    /// Full image path of `pid`, or `None` when it cannot be opened.
    fn image(&self, pid: u32) -> Option<String>;
    fn monotonic(&self) -> f64;
    fn now_ms(&self) -> i64;
}

/// UTF-16 → `String`; a lone surrogate becomes `?` (Python `encode("utf-8", "replace")`), and the
/// text ends at the first NUL (ctypes `buf.value`).
pub fn utf16_lossy_q(units: &[u16]) -> String {
    let end = units.iter().position(|&u| u == 0).unwrap_or(units.len());
    char::decode_utf16(units[..end].iter().copied())
        .map(|c| c.unwrap_or('?'))
        .collect()
}

pub struct RealWin;

fn hwnd(h: isize) -> windows::Win32::Foundation::HWND {
    windows::Win32::Foundation::HWND(h as *mut core::ffi::c_void)
}

impl WinApi for RealWin {
    fn foreground(&self) -> isize {
        // SAFETY: plain call.
        unsafe { windows::Win32::UI::WindowsAndMessaging::GetForegroundWindow() }.0 as isize
    }

    fn text(&self, h: isize) -> String {
        use windows::Win32::UI::WindowsAndMessaging::{GetWindowTextLengthW, GetWindowTextW};
        // SAFETY: a stale or foreign handle only makes these calls fail (0).
        let n = unsafe { GetWindowTextLengthW(hwnd(h)) };
        if n <= 0 {
            return String::new();
        }
        let mut buf = vec![0u16; n as usize + 1];
        // SAFETY: the buffer is writable for its whole length, which the call is told.
        let got = unsafe { GetWindowTextW(hwnd(h), &mut buf) };
        utf16_lossy_q(&buf[..usize::try_from(got).unwrap_or(0).min(buf.len())])
    }

    fn pid_of(&self, h: isize) -> u32 {
        use windows::Win32::UI::WindowsAndMessaging::GetWindowThreadProcessId;
        let mut pid = 0u32;
        // SAFETY: the out pointer is valid for the call.
        unsafe { GetWindowThreadProcessId(hwnd(h), Some(&mut pid)) };
        pid
    }

    fn image(&self, pid: u32) -> Option<String> {
        use windows::Win32::Foundation::CloseHandle;
        use windows::Win32::System::Threading::{
            OpenProcess, PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION,
            QueryFullProcessImageNameW,
        };
        // SAFETY: plain call; the handle is closed below.
        let handle = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) }.ok()?;
        let mut buf = vec![0u16; IMAGE_PATH_MAX];
        let mut size = buf.len() as u32;
        // SAFETY: `buf` holds `size` units; `size` is updated to the length written.
        let ok = unsafe {
            QueryFullProcessImageNameW(
                handle,
                PROCESS_NAME_WIN32,
                windows::core::PWSTR(buf.as_mut_ptr()),
                &mut size,
            )
        };
        // SAFETY: our own handle, closed once.
        let _ = unsafe { CloseHandle(handle) };
        ok.ok()?;
        Some(utf16_lossy_q(&buf[..(size as usize).min(buf.len())]))
    }

    fn monotonic(&self) -> f64 {
        time::monotonic()
    }

    fn now_ms(&self) -> i64 {
        time::now_ms()
    }
}

pub type OnEvent = Arc<dyn Fn(RawWinEvent) + Send + Sync>;

/// One WinEvent → at most one [`RawWinEvent`] (Python `WinEventHookThread.handle`).
pub struct HookHandler {
    on_event: OnEvent,
    win: Arc<dyn WinApi>,
    images: HashMap<u32, (Option<String>, f64)>,
    last_foreground: isize,
    errors: u64,
}

impl HookHandler {
    pub fn new(on_event: OnEvent, win: Arc<dyn WinApi>) -> HookHandler {
        HookHandler {
            on_event,
            win,
            images: HashMap::new(),
            last_foreground: 0,
            errors: 0,
        }
    }

    /// Callbacks that failed (swallowed).
    pub fn errors(&self) -> u64 {
        self.errors
    }

    /// Never panics: a failure (a panic in a Win32 read or in `on_event`) only counts in
    /// [`HookHandler::errors`].
    pub fn handle(&mut self, event: u32, hwnd: isize, id_object: i32, id_child: i32) {
        if catch_unwind(AssertUnwindSafe(|| {
            self.handle_inner(event, hwnd, id_object, id_child)
        }))
        .is_err()
        {
            self.errors += 1;
        }
    }

    fn handle_inner(&mut self, event: u32, hwnd: isize, id_object: i32, id_child: i32) {
        let kind = match event {
            EVENT_SYSTEM_FOREGROUND => Kind::Foreground,
            EVENT_SYSTEM_MINIMIZESTART => Kind::Minimize,
            EVENT_SYSTEM_MINIMIZEEND => Kind::Restore,
            EVENT_OBJECT_NAMECHANGE => Kind::Title,
            _ => return,
        };
        if hwnd == 0 {
            return;
        }
        match kind {
            Kind::Foreground => self.last_foreground = hwnd,
            Kind::Title => {
                if id_object != OBJID_WINDOW || id_child != CHILDID_SELF {
                    return;
                }
                // GetForegroundWindow can answer 0 (seen while the foreground event had just named
                // a window): then the last EVENT_SYSTEM_FOREGROUND window counts.
                let fg = match self.win.foreground() {
                    0 => self.last_foreground,
                    fg => fg,
                };
                if hwnd != fg {
                    return;
                }
            }
            Kind::Minimize | Kind::Restore => {}
        }
        let pid = self.win.pid_of(hwnd);
        let t = self.win.monotonic();
        let exe = self.image_of(pid, t);
        let title = self.win.text(hwnd);
        let at_ms = self.win.now_ms();
        (self.on_event)(RawWinEvent {
            t,
            kind,
            hwnd,
            pid,
            exe,
            title,
            at_ms,
        });
    }

    fn image_of(&mut self, pid: u32, t: f64) -> Option<String> {
        if let Some((image, at)) = self.images.get(&pid)
            && t - at < IMAGE_CACHE_SEC
        {
            return image.clone();
        }
        if self.images.len() >= IMAGE_CACHE_MAX {
            self.images.clear();
        }
        let image = self.win.image(pid);
        self.images.insert(pid, (image.clone(), t));
        image
    }
}

thread_local! {
    /// The handler of the hook thread this callback runs on.
    static HANDLER: RefCell<Option<HookHandler>> = const { RefCell::new(None) };
}

unsafe extern "system" fn win_event_proc(
    _hook: windows::Win32::UI::Accessibility::HWINEVENTHOOK,
    event: u32,
    hwnd: windows::Win32::Foundation::HWND,
    id_object: i32,
    id_child: i32,
    _thread: u32,
    _ms: u32,
) {
    // A re-entered callback (the handler is busy further up this thread's stack) is skipped.
    let _ = HANDLER.try_with(|h| {
        if let Ok(mut h) = h.try_borrow_mut()
            && let Some(h) = h.as_mut()
        {
            h.handle(event, hwnd.0 as isize, id_object, id_child);
        }
    });
}

#[derive(Default)]
struct Shared {
    ready: Mutex<bool>,
    ready_cv: Condvar,
    tid: AtomicU32,
    hooks: AtomicUsize,
    stopping: AtomicBool,
}

/// The hook thread (Python `WinEventHookThread`).
pub struct HookThread {
    shared: Arc<Shared>,
    thread: Mutex<Option<(JoinHandle<()>, Receiver<()>)>>,
}

impl HookThread {
    /// A thread that never ran (`stop` is harmless, `wait_ready` false, no hooks).
    pub fn not_started() -> HookThread {
        HookThread {
            shared: Arc::new(Shared::default()),
            thread: Mutex::new(None),
        }
    }

    /// Starts the thread: message queue (`PeekMessageW(PM_NOREMOVE)`), the three hook ranges
    /// (`WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS`), then a `GetMessageW` loop.
    pub fn start(handler: HookHandler) -> HookThread {
        let t = HookThread::not_started();
        let shared = t.shared.clone();
        let (done_tx, done_rx) = mpsc::channel();
        let spawned = std::thread::Builder::new()
            .name("agent-winevent-hooks".into())
            .spawn(move || {
                hook_thread(handler, &shared);
                let _ = done_tx.send(());
            });
        if let Ok(handle) = spawned {
            *t.thread.lock().unwrap_or_else(|e| e.into_inner()) = Some((handle, done_rx));
        }
        t
    }

    /// Hooks installed successfully.
    pub fn hook_count(&self) -> usize {
        self.shared.hooks.load(Ordering::SeqCst)
    }

    /// True once the hooks are installed (or the thread gave up).
    pub fn wait_ready(&self, timeout: Duration) -> bool {
        let ready = self.shared.ready.lock().unwrap_or_else(|e| e.into_inner());
        let (ready, _) = self
            .shared
            .ready_cv
            .wait_timeout_while(ready, timeout, |r| !*r)
            .unwrap_or_else(|e| e.into_inner());
        *ready
    }

    /// Ends the message loop (`WM_QUIT`), which removes the hooks, and waits up to 2 s for the
    /// thread. Safe before start and when called twice.
    pub fn stop(&self) {
        use windows::Win32::Foundation::{LPARAM, WPARAM};
        use windows::Win32::UI::WindowsAndMessaging::{PostThreadMessageW, WM_QUIT};
        self.shared.stopping.store(true, Ordering::SeqCst);
        let Some((handle, done)) = self.thread.lock().unwrap_or_else(|e| e.into_inner()).take()
        else {
            return;
        };
        self.wait_ready(STOP_WAIT);
        let tid = self.shared.tid.load(Ordering::SeqCst);
        if tid != 0 {
            // SAFETY: plain call; the thread's queue exists since before it was ready.
            let _ = unsafe { PostThreadMessageW(tid, WM_QUIT, WPARAM(0), LPARAM(0)) };
        }
        if done.recv_timeout(STOP_WAIT).is_ok() {
            let _ = handle.join();
        }
    }
}

fn hook_thread(handler: HookHandler, shared: &Shared) {
    use windows::Win32::System::Threading::GetCurrentThreadId;
    use windows::Win32::UI::Accessibility::{SetWinEventHook, UnhookWinEvent};
    use windows::Win32::UI::WindowsAndMessaging::{
        DispatchMessageW, GetMessageW, MSG, PM_NOREMOVE, PeekMessageW, TranslateMessage,
    };
    HANDLER.with(|h| *h.borrow_mut() = Some(handler));
    let mut msg = MSG::default();
    // SAFETY: plain calls on this thread; `msg` is valid for each call.
    unsafe {
        shared.tid.store(GetCurrentThreadId(), Ordering::SeqCst);
        // Creates the queue, so a WM_QUIT posted from now on is not lost.
        let _ = PeekMessageW(&mut msg, None, 0, 0, PM_NOREMOVE);
    }
    let mut hooks = Vec::new();
    for (low, high) in HOOK_RANGES {
        // SAFETY: the callback is a plain function that lives as long as the process.
        let hook = unsafe {
            SetWinEventHook(
                low,
                high,
                None,
                Some(win_event_proc),
                0,
                0,
                WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
            )
        };
        if !hook.is_invalid() {
            hooks.push(hook);
        }
    }
    shared.hooks.store(hooks.len(), Ordering::SeqCst);
    {
        *shared.ready.lock().unwrap_or_else(|e| e.into_inner()) = true;
        shared.ready_cv.notify_all();
    }
    while !shared.stopping.load(Ordering::SeqCst) {
        // SAFETY: `msg` is valid for each call.
        let got = unsafe { GetMessageW(&mut msg, None, 0, 0) }.0;
        if got == 0 || got == -1 {
            break; // WM_QUIT or an error
        }
        // SAFETY: a message GetMessageW just filled in.
        unsafe {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
    for hook in hooks {
        // SAFETY: hooks this thread installed, removed once.
        let _ = unsafe { UnhookWinEvent(hook) };
    }
    HANDLER.with(|h| *h.borrow_mut() = None);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::coalesce::Kind;
    use std::sync::{
        Arc, Mutex,
        atomic::{AtomicU32, Ordering::SeqCst},
    };

    struct FakeWin {
        fg: Mutex<isize>,
        images: AtomicU32,
        fail: bool,
    }
    impl WinApi for FakeWin {
        fn foreground(&self) -> isize {
            *self.fg.lock().unwrap()
        }
        fn text(&self, hwnd: isize) -> String {
            if self.fail {
                panic!("boom")
            }
            format!("w{hwnd}")
        }
        fn pid_of(&self, hwnd: isize) -> u32 {
            hwnd as u32 + 100
        }
        fn image(&self, pid: u32) -> Option<String> {
            self.images.fetch_add(1, SeqCst);
            Some(format!(r"C:\p{pid}.exe"))
        }
        fn monotonic(&self) -> f64 {
            1.0
        }
        fn now_ms(&self) -> i64 {
            1_793_768_397_000
        }
    }
    type Got = Arc<Mutex<Vec<RawWinEvent>>>;
    fn handler(fg: isize, fail: bool) -> (HookHandler, Got, Arc<FakeWin>) {
        let got = Arc::new(Mutex::new(Vec::new()));
        let g = got.clone();
        let win = Arc::new(FakeWin {
            fg: Mutex::new(fg),
            images: AtomicU32::new(0),
            fail,
        });
        (
            HookHandler::new(Arc::new(move |e| g.lock().unwrap().push(e)), win.clone()),
            got,
            win,
        )
    }

    #[test]
    fn foreground_and_minimize_events_become_raw_events() {
        let (mut h, got, _) = handler(5, false);
        h.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0);
        h.handle(EVENT_SYSTEM_MINIMIZESTART, 5, 0, 0);
        h.handle(EVENT_SYSTEM_MINIMIZEEND, 5, 0, 0);
        h.handle(0x1234, 5, 0, 0);
        h.handle(EVENT_SYSTEM_FOREGROUND, 0, 0, 0);
        let g = got.lock().unwrap();
        assert_eq!(
            g.iter().map(|e| e.kind).collect::<Vec<_>>(),
            [Kind::Foreground, Kind::Minimize, Kind::Restore]
        );
        assert_eq!(
            (g[0].pid, g[0].exe.as_deref(), g[0].title.as_str()),
            (105, Some(r"C:\p105.exe"), "w5")
        );
        assert_eq!((g[0].t, g[0].at_ms, g[0].hwnd), (1.0, 1_793_768_397_000, 5));
    }

    #[test]
    fn name_changes_count_only_for_the_foreground_window_itself() {
        let (mut h, got, _) = handler(5, false);
        h.handle(EVENT_OBJECT_NAMECHANGE, 5, 0, 0);
        h.handle(EVENT_OBJECT_NAMECHANGE, 6, 0, 0);
        h.handle(EVENT_OBJECT_NAMECHANGE, 5, -4, 0);
        h.handle(EVENT_OBJECT_NAMECHANGE, 5, 0, 3);
        assert_eq!(got.lock().unwrap().len(), 1);
    }

    #[test]
    fn without_a_foreground_window_the_last_foreground_event_counts() {
        let (mut h, got, _) = handler(0, false);
        h.handle(EVENT_SYSTEM_FOREGROUND, 7, 0, 0);
        h.handle(EVENT_OBJECT_NAMECHANGE, 7, 0, 0);
        assert_eq!(
            got.lock()
                .unwrap()
                .iter()
                .map(|e| e.kind)
                .collect::<Vec<_>>(),
            [Kind::Foreground, Kind::Title]
        );
    }

    #[test]
    fn process_image_is_cached_per_pid() {
        let (mut h, _, win) = handler(5, false);
        for _ in 0..3 {
            h.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0);
        }
        assert_eq!(win.images.load(SeqCst), 1);
    }

    #[test]
    fn the_callback_never_lets_a_failure_escape() {
        let (mut h, got, _) = handler(5, true);
        h.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0);
        assert!(got.lock().unwrap().is_empty());
        assert_eq!(h.errors(), 1);
    }

    #[test]
    fn lone_surrogates_become_question_marks() {
        let units: Vec<u16> = vec![0x61, 0xD800, 0x62, 0xD55C];
        assert_eq!(utf16_lossy_q(&units), "a?b한");
    }

    #[test]
    fn the_hook_thread_installs_three_hooks_and_stops() {
        let (h, _, _) = handler(0, false);
        let t = HookThread::start(h);
        assert!(t.wait_ready(std::time::Duration::from_secs(5)));
        assert_eq!(t.hook_count(), 3);
        t.stop();
        HookThread::not_started().stop(); // stopping something never started is harmless
    }

    // --- beyond the plan: the rest of the Python hook tests --------------------------------

    /// A [`WinApi`] whose answers the test changes.
    struct Scripted {
        fg: Mutex<isize>,
        clock: Mutex<f64>,
        image_calls: Mutex<Vec<u32>>,
    }
    impl WinApi for Scripted {
        fn foreground(&self) -> isize {
            *self.fg.lock().unwrap()
        }
        fn text(&self, hwnd: isize) -> String {
            match hwnd {
                5 => "doc".into(),
                _ => "other".into(),
            }
        }
        fn pid_of(&self, hwnd: isize) -> u32 {
            hwnd as u32 * 10
        }
        fn image(&self, pid: u32) -> Option<String> {
            self.image_calls.lock().unwrap().push(pid);
            (pid == 50).then(|| r"C:\a.exe".to_string())
        }
        fn monotonic(&self) -> f64 {
            *self.clock.lock().unwrap()
        }
        fn now_ms(&self) -> i64 {
            1_793_768_397_000
        }
    }
    fn scripted(fg: isize) -> (HookHandler, Got, Arc<Scripted>) {
        let got = Arc::new(Mutex::new(Vec::new()));
        let g = got.clone();
        let win = Arc::new(Scripted {
            fg: Mutex::new(fg),
            clock: Mutex::new(1.0),
            image_calls: Mutex::new(Vec::new()),
        });
        (
            HookHandler::new(Arc::new(move |e| g.lock().unwrap().push(e)), win.clone()),
            got,
            win,
        )
    }

    #[test]
    fn a_process_that_cannot_be_opened_has_no_exe() {
        let (mut h, got, _) = scripted(5);
        h.handle(EVENT_SYSTEM_MINIMIZESTART, 6, 0, 0);
        let g = got.lock().unwrap();
        assert_eq!(
            (g[0].kind, g[0].pid, g[0].exe.clone(), g[0].title.as_str()),
            (Kind::Minimize, 60, None, "other")
        );
    }

    #[test]
    fn a_real_foreground_answer_wins_over_the_remembered_window() {
        let (mut h, got, win) = scripted(0);
        h.handle(EVENT_OBJECT_NAMECHANGE, 5, 0, 0); // nothing known yet
        h.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0);
        h.handle(EVENT_OBJECT_NAMECHANGE, 6, 0, 0);
        h.handle(EVENT_OBJECT_NAMECHANGE, 5, 0, 0);
        *win.fg.lock().unwrap() = 6;
        h.handle(EVENT_OBJECT_NAMECHANGE, 5, 0, 0);
        h.handle(EVENT_OBJECT_NAMECHANGE, 6, 0, 0);
        assert_eq!(
            got.lock()
                .unwrap()
                .iter()
                .map(|e| (e.kind, e.hwnd))
                .collect::<Vec<_>>(),
            [(Kind::Foreground, 5), (Kind::Title, 5), (Kind::Title, 6)]
        );
    }

    #[test]
    fn a_cached_image_expires_after_30_s() {
        let (mut h, _, win) = scripted(5);
        h.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0);
        h.handle(EVENT_OBJECT_NAMECHANGE, 5, 0, 0);
        *win.clock.lock().unwrap() = 30.9;
        h.handle(EVENT_OBJECT_NAMECHANGE, 5, 0, 0);
        assert_eq!(*win.image_calls.lock().unwrap(), [50]);
        *win.clock.lock().unwrap() = 31.0;
        h.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0);
        assert_eq!(*win.image_calls.lock().unwrap(), [50, 50]);
    }

    #[test]
    fn the_image_cache_is_cleared_when_full() {
        let (mut h, _, win) = scripted(0);
        for w in 1..=IMAGE_CACHE_MAX as isize {
            h.handle(EVENT_SYSTEM_MINIMIZESTART, w, 0, 0);
        }
        h.handle(EVENT_SYSTEM_MINIMIZESTART, 1, 0, 0); // still cached
        assert_eq!(win.image_calls.lock().unwrap().len(), IMAGE_CACHE_MAX);
        h.handle(EVENT_SYSTEM_MINIMIZESTART, 9999, 0, 0); // full: cleared, then cached anew
        h.handle(EVENT_SYSTEM_MINIMIZESTART, 1, 0, 0);
        assert_eq!(win.image_calls.lock().unwrap().len(), IMAGE_CACHE_MAX + 2);
    }

    #[test]
    fn a_failing_consumer_is_counted_too() {
        let win = Arc::new(Scripted {
            fg: Mutex::new(5),
            clock: Mutex::new(1.0),
            image_calls: Mutex::new(Vec::new()),
        });
        let mut h = HookHandler::new(Arc::new(|_| panic!("consumer failed")), win);
        h.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0);
        h.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0);
        assert_eq!(h.errors(), 2);
    }

    #[test]
    fn text_ends_at_the_first_nul_and_keeps_pairs() {
        assert_eq!(utf16_lossy_q(&[0x41, 0, 0x42]), "A");
        assert_eq!(utf16_lossy_q(&[0xD83D, 0xDE00, 0xDC00]), "😀?");
        assert_eq!(utf16_lossy_q(&[]), "");
    }

    #[test]
    fn stopping_twice_is_harmless() {
        let (h, _, _) = handler(0, false);
        let t = HookThread::start(h);
        assert!(t.wait_ready(Duration::from_secs(5)));
        t.stop();
        t.stop();
        let n = HookThread::not_started();
        assert!(!n.wait_ready(Duration::from_millis(10)) && n.hook_count() == 0);
    }

    #[test]
    fn real_win_reads_this_process() {
        let image = RealWin
            .image(std::process::id())
            .expect("own process image");
        assert!(
            image.to_ascii_lowercase().ends_with(".exe")
                && std::path::Path::new(&image).is_absolute(),
            "{image}"
        );
        assert_eq!(RealWin.image(0), None); // the idle process cannot be opened
        let fg = RealWin.foreground();
        if fg != 0 {
            // a locked or disconnected desktop has no foreground window
            assert!(RealWin.pid_of(fg) > 0);
            let _ = RealWin.text(fg);
        }
        assert_eq!(RealWin.text(0), "");
    }
}
