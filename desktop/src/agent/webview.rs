//! `agent --dialog webview` (the default): the notice is a top-most modal WebView2 window of this
//! process (D3=A, Y10). It stays above other windows (re-asserted every 2 s without taking the
//! focus), has no close button, no taskbar button, no minimise/maximise/resize, refuses `WM_CLOSE`
//! (Alt+F4) and Escape does nothing to it; it navigates only to the server's own `/notice` page,
//! opens no other window, has no context menu, devtools or browser accelerator keys, and uses an
//! InPrivate profile under `%LOCALAPPDATA%\mcp-monitor\notice-webview` (removed by uninstall's
//! `remove_webview_profiles`). If it goes away anyway (destroyed from outside, or a WebView2
//! browser/renderer process died: `ProcessFailed`, `BrowserProcessExited`, or the browser process
//! found gone when the runner polls), the runner reports a user close, the dead window is closed,
//! and the server shows the notice again in a fresh window.
//! Windows cannot block input to other apps; "modal" means the above (K01).
//!
//! The Tauri event loop owns the main thread; the runner (with the window activity, F09) runs on
//! its own thread and drives the window through `run_on_main_thread`.

use super::activity::WindowActivity;
use super::client::{ServerClient, UreqTransport};
use super::config::AgentConfig;
use super::runner::{AgentRunner, EXIT_OK, Log, NoticeWindow, log_stderr};
use super::{current_session_id, run_with_activity};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicI32, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, mpsc};
use std::time::Duration;
use tauri::webview::NewWindowResponse;
use tauri::{AppHandle, RunEvent, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

pub const NOTICE_TITLE: &str = "MCP Monitor 고지";
/// How often the window is put back on top (without activating it).
pub const TOPMOST_EVERY: Duration = Duration::from_secs(2);

#[derive(Debug, PartialEq)]
pub struct NoticeSpec {
    pub title: &'static str,
    pub width: f64,
    pub height: f64,
    pub always_on_top: bool,
    pub closable: bool,
    pub minimizable: bool,
    pub maximizable: bool,
    pub resizable: bool,
    pub skip_taskbar: bool,
    pub incognito: bool,
    pub focused: bool,
    pub decorations: bool,
    pub context_menu: bool,
    pub devtools: bool,
    pub accelerator_keys: bool,
}

/// 640×600 (logical px), shrunk to the work area less 16 px on each side, never below 320×300 (Y30).
pub fn notice_size(w: f64, h: f64) -> (f64, f64) {
    (
        (640.0f64).min(w - 32.0).max(320.0),
        (600.0f64).min(h - 32.0).max(300.0),
    )
}

/// The notice window for a work area of `work_w`×`work_h` logical px. The title bar stays (so the
/// window can be moved); only its close button is disabled.
pub fn notice_spec(work_w: f64, work_h: f64) -> NoticeSpec {
    let (width, height) = notice_size(work_w, work_h);
    NoticeSpec {
        title: NOTICE_TITLE,
        width,
        height,
        always_on_top: true,
        closable: false,
        minimizable: false,
        maximizable: false,
        resizable: false,
        skip_taskbar: true,
        incognito: true,
        focused: true,
        decorations: true,
        context_menu: false,
        devtools: false,
        accelerator_keys: false,
    }
}

/// Only the server's own notice page: same scheme, host and port as `server`, no user info, the
/// path exactly `/notice` and no query (the fragment carries the display id and token).
pub fn notice_navigation_allowed(url: &tauri::Url, server: &str) -> bool {
    let Ok(server) = tauri::Url::parse(server) else {
        return false;
    };
    url.scheme() == server.scheme()
        && url.host_str().is_some()
        && url.host_str() == server.host_str()
        && url.port_or_known_default() == server.port_or_known_default()
        && url.username().is_empty()
        && url.password().is_none()
        && url.path() == "/notice"
        && url.query().is_none()
}

/// `<L>\mcp-monitor\notice-webview` for `%LOCALAPPDATA%` = `<L>`.
pub fn notice_data_dir(local_app_data: &Path) -> PathBuf {
    local_app_data.join("mcp-monitor").join("notice-webview")
}

/// `ProcessFailed` kinds after which the notice page is gone: the browser process or the main
/// frame's renderer exited (`COREWEBVIEW2_PROCESS_FAILED_KIND` 0 and 1). The others (an
/// unresponsive renderer, GPU, utility, iframe processes) recover or do not show the page.
pub fn process_failure_closes(kind: i32) -> bool {
    matches!(kind, 0 | 1)
}

/// The WebView2 browser process a notice window's page lives in. The real one is a process handle
/// opened while the window was made ([`BrowserHandle`]); the tests use a fake.
pub trait BrowserProcess: Send {
    /// True once the process has exited.
    fn exited(&self) -> bool;
}

/// The browser process by a `SYNCHRONIZE` handle, opened right after the window was made (so a
/// reused pid cannot stand in for it later). Closed on drop.
struct BrowserHandle(isize);

impl BrowserHandle {
    fn open(pid: u32) -> windows::core::Result<BrowserHandle> {
        use windows::Win32::System::Threading::{OpenProcess, PROCESS_SYNCHRONIZE};
        // SAFETY: a plain open; the handle is kept as an integer and closed on drop.
        let h = unsafe { OpenProcess(PROCESS_SYNCHRONIZE, false, pid) }?;
        Ok(BrowserHandle(h.0 as isize))
    }
}

impl BrowserProcess for BrowserHandle {
    fn exited(&self) -> bool {
        use windows::Win32::Foundation::{HANDLE, WAIT_OBJECT_0};
        use windows::Win32::System::Threading::WaitForSingleObject;
        // SAFETY: a handle we own, opened with SYNCHRONIZE; a zero timeout only polls.
        unsafe { WaitForSingleObject(HANDLE(self.0 as *mut _), 0) == WAIT_OBJECT_0 }
    }
}

impl Drop for BrowserHandle {
    fn drop(&mut self) {
        use windows::Win32::Foundation::{CloseHandle, HANDLE};
        // SAFETY: closed once, here.
        let _ = unsafe { CloseHandle(HANDLE(self.0 as *mut _)) };
    }
}

/// One notice window's close bookkeeping, shared with its window-event and WebView2 handlers.
///
/// The page can go away three ways, and any one of them is enough (review I3): the window is
/// destroyed ([`NoticeState::on_destroyed`]); WebView2 reports `ProcessFailed` or
/// `BrowserProcessExited` ([`NoticeState::on_process_failed`]); or the browser process is found
/// gone when the runner polls ([`NoticeState::check_browser`]), for when no WebView2 event comes
/// (Task 11: `ProcessFailed` did not fire on the CI runner after the browser was killed). Each
/// counts as a user close, once; the runner reports it, the dead window is closed, and the server
/// shows the notice again in a new window.
#[derive(Default)]
pub struct NoticeState {
    closing: AtomicBool,
    closed_by_user: AtomicBool,
    page_gone: AtomicBool,
    browser: Mutex<Option<Box<dyn BrowserProcess>>>,
}

impl NoticeState {
    /// We are closing the window (a `close_notice`, a newer notice, or the agent's exit).
    pub fn begin_close(&self) {
        self.closing.store(true, Ordering::SeqCst);
    }

    /// A close request (Alt+F4, `WM_CLOSE`) is refused unless we are closing.
    pub fn should_prevent_close(&self) -> bool {
        !self.closing.load(Ordering::SeqCst)
    }

    /// The window is gone: unless we closed it, the user (or something outside) did.
    pub fn on_destroyed(&self) {
        if !self.closing.load(Ordering::SeqCst) {
            self.closed_by_user.store(true, Ordering::SeqCst);
        }
    }

    /// A WebView2 browser or renderer process died: the page is gone, so it counts as a user
    /// close (the server shows the notice again a second later in a new window). Counted once,
    /// however many signals report it.
    pub fn on_process_failed(&self) {
        if !self.closing.load(Ordering::SeqCst) && !self.page_gone.swap(true, Ordering::SeqCst) {
            self.closed_by_user.store(true, Ordering::SeqCst);
        }
    }

    /// The browser process to poll in [`NoticeState::check_browser`].
    pub fn watch_browser(&self, process: Box<dyn BrowserProcess>) {
        *self.browser.lock().unwrap_or_else(|e| e.into_inner()) = Some(process);
    }

    /// The fallback signal: true (once) when the watched browser process has exited while we were
    /// not closing the window and no other signal said so yet; it then counts as
    /// [`NoticeState::on_process_failed`].
    pub fn check_browser(&self) -> bool {
        if self.closing.load(Ordering::SeqCst) || self.page_gone.load(Ordering::SeqCst) {
            return false;
        }
        let exited = self
            .browser
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .as_ref()
            .is_some_and(|b| b.exited());
        if exited {
            self.on_process_failed();
        }
        exited
    }

    /// The page died (the window may still be there, blank): it must be replaced.
    pub fn page_gone(&self) -> bool {
        self.page_gone.load(Ordering::SeqCst)
    }

    /// True once after the window went away without us; reading it clears it.
    pub fn take_closed_by_user(&self) -> bool {
        self.closed_by_user.swap(false, Ordering::SeqCst)
    }

    /// A new window.
    pub fn reset(&self) {
        self.closing.store(false, Ordering::SeqCst);
        self.closed_by_user.store(false, Ordering::SeqCst);
        self.page_gone.store(false, Ordering::SeqCst);
        *self.browser.lock().unwrap_or_else(|e| e.into_inner()) = None;
    }
}

/// `%LOCALAPPDATA%` of the session user (the variable, else the known folder).
pub fn local_app_data() -> Option<PathBuf> {
    if let Some(v) = std::env::var_os("LOCALAPPDATA").filter(|v| !v.is_empty()) {
        return Some(PathBuf::from(v));
    }
    use windows::Win32::System::Com::CoTaskMemFree;
    use windows::Win32::UI::Shell::{FOLDERID_LocalAppData, KF_FLAG_DEFAULT, SHGetKnownFolderPath};
    // SAFETY: plain call; the returned buffer is freed with CoTaskMemFree after copying it.
    unsafe {
        let p = SHGetKnownFolderPath(&FOLDERID_LocalAppData, KF_FLAG_DEFAULT, None).ok()?;
        let path = p.to_string().ok().map(PathBuf::from);
        CoTaskMemFree(Some(p.0 as *const _));
        path
    }
}

/// The default browser on `url` (the fallback when no WebView2 window can be made — the notice
/// must be shown, Python V25). `url` passed [`notice_navigation_allowed`] or came from the server.
fn open_in_browser(url: &str) -> Result<(), String> {
    crate::winutil::open_in_browser(url)
}

struct Shown {
    window: WebviewWindow,
    state: Arc<NoticeState>,
    /// Dropping it ends the top-most ticker.
    _ticker: mpsc::Sender<()>,
}

/// Window label → that notice window's state, read by the app's window-event handler
/// ([`on_notice_window_event`]).
pub type NoticeRegistry = Arc<Mutex<HashMap<String, Arc<NoticeState>>>>;

/// The notice windows' events, from the app's run callback: a close request is refused unless we
/// close the window; `Destroyed` is recorded (and the label forgotten).
pub fn on_notice_window_event(
    registry: &NoticeRegistry,
    label: &str,
    event: &tauri::WindowEvent,
    log: &Log,
) {
    let state = registry
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .get(label)
        .cloned();
    let Some(state) = state else {
        return;
    };
    match event {
        tauri::WindowEvent::CloseRequested { api, .. } => {
            if state.should_prevent_close() {
                api.prevent_close();
                log("notice window: close request refused");
            }
        }
        tauri::WindowEvent::Destroyed => {
            if state.should_prevent_close() {
                log("notice window: gone without a close_notice");
            }
            state.on_destroyed();
            registry
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .remove(label);
        }
        _ => {}
    }
}

/// The WebView2 notice window, driven from the runner's thread.
pub struct WebViewNotice {
    app: AppHandle,
    server: String,
    data_dir: PathBuf,
    log: Log,
    registry: NoticeRegistry,
    shown: Option<Shown>,
    /// Labels are unique per window: an old window's label is freed only after its `Destroyed`.
    next: AtomicU64,
}

impl WebViewNotice {
    pub fn new(
        app: AppHandle,
        server: String,
        data_dir: PathBuf,
        registry: NoticeRegistry,
        log: Log,
    ) -> WebViewNotice {
        WebViewNotice {
            app,
            server,
            data_dir,
            log,
            registry,
            shown: None,
            next: AtomicU64::new(1),
        }
    }
}

/// Logical size of the primary monitor's work area (or room for the full 640×600).
fn work_area(app: &AppHandle) -> (f64, f64) {
    match app.primary_monitor() {
        Ok(Some(m)) => {
            let scale = m.scale_factor().max(0.1);
            let size = m.work_area().size;
            (
                f64::from(size.width) / scale,
                f64::from(size.height) / scale,
            )
        }
        _ => (672.0, 632.0),
    }
}

/// The crash signals first (review I3: a failing settings call must not leave the window without
/// them), then the settings Tauri has no builder option for. The signals: `ProcessFailed`, the
/// environment's `BrowserProcessExited`, and a handle on the browser process that the runner polls
/// ([`NoticeState::check_browser`]). Each is best effort and independent of the others: a failure
/// is logged and the rest are still registered.
///
/// # Safety
/// Main thread only (the WebView2 COM objects are single-threaded).
unsafe fn configure_webview(
    controller: webview2_com::Microsoft::Web::WebView2::Win32::ICoreWebView2Controller,
    spec: &NoticeSpec,
    state: Arc<NoticeState>,
    log: Log,
) -> windows::core::Result<()> {
    use webview2_com::Microsoft::Web::WebView2::Win32::{
        COREWEBVIEW2_BROWSER_PROCESS_EXIT_KIND, COREWEBVIEW2_PROCESS_FAILED_KIND, ICoreWebView2_2,
        ICoreWebView2Environment5, ICoreWebView2Settings3,
    };
    use webview2_com::{BrowserProcessExitedEventHandler, ProcessFailedEventHandler};
    use windows::core::Interface;
    // SAFETY: COM calls on the main thread that owns the controller.
    unsafe {
        let webview = controller.CoreWebView2()?;
        // Each signal on its own (re-review nit 5): one that cannot be registered is logged and
        // the others are still set up.
        let mut failed_token = 0i64;
        let (failed_state, failed_log) = (state.clone(), log.clone());
        if let Err(e) = webview.add_ProcessFailed(
            &ProcessFailedEventHandler::create(Box::new(move |_, args| {
                let mut kind = COREWEBVIEW2_PROCESS_FAILED_KIND::default();
                if let Some(args) = args {
                    args.ProcessFailedKind(&mut kind)?;
                }
                failed_log(&format!(
                    "notice window: WebView2 process failed (kind {})",
                    kind.0
                ));
                if process_failure_closes(kind.0) {
                    failed_state.on_process_failed();
                }
                Ok(())
            })),
            &mut failed_token,
        ) {
            log(&format!("notice window: no ProcessFailed event: {e}"));
        }
        let mut pid = 0u32;
        match webview
            .BrowserProcessId(&mut pid)
            .and_then(|()| BrowserHandle::open(pid))
        {
            Ok(handle) => {
                log(&format!(
                    "notice window: watching the WebView2 browser process {pid}"
                ));
                state.watch_browser(Box::new(handle));
            }
            Err(e) => log(&format!(
                "notice window: the browser process cannot be watched: {e}"
            )),
        }
        let mut exited_token = 0i64;
        let (exited_state, exited_log) = (state.clone(), log.clone());
        let exited = webview
            .cast::<ICoreWebView2_2>()
            .and_then(|w| w.Environment())
            .and_then(|env| env.cast::<ICoreWebView2Environment5>())
            .and_then(|env| {
                env.add_BrowserProcessExited(
                    &BrowserProcessExitedEventHandler::create(Box::new(move |_, args| {
                        let mut kind = COREWEBVIEW2_BROWSER_PROCESS_EXIT_KIND::default();
                        if let Some(args) = args {
                            args.BrowserProcessExitKind(&mut kind)?;
                        }
                        exited_log(&format!(
                            "notice window: WebView2 browser process exited (kind {})",
                            kind.0
                        ));
                        exited_state.on_process_failed();
                        Ok(())
                    })),
                    &mut exited_token,
                )
            });
        if let Err(e) = exited {
            log(&format!(
                "notice window: no BrowserProcessExited event: {e}"
            ));
        }
        let settings = webview.Settings()?;
        settings.SetAreDevToolsEnabled(spec.devtools)?;
        settings.SetAreDefaultContextMenusEnabled(spec.context_menu)?;
        settings
            .cast::<ICoreWebView2Settings3>()?
            .SetAreBrowserAcceleratorKeysEnabled(spec.accelerator_keys)?;
    }
    Ok(())
}

/// Brings the new window to the front; a process that may not take the foreground flashes it
/// instead (until it is activated).
fn bring_to_front(hwnd: windows::Win32::Foundation::HWND) {
    use windows::Win32::UI::WindowsAndMessaging::{
        FLASHW_ALL, FLASHW_TIMERNOFG, FLASHWINFO, FlashWindowEx, SetForegroundWindow,
    };
    // SAFETY: plain calls on our own window.
    unsafe {
        if !SetForegroundWindow(hwnd).as_bool() {
            let info = FLASHWINFO {
                cbSize: std::mem::size_of::<FLASHWINFO>() as u32,
                hwnd,
                dwFlags: FLASHW_ALL | FLASHW_TIMERNOFG,
                uCount: 0,
                dwTimeout: 0,
            };
            let _ = FlashWindowEx(&info);
        }
    }
}

/// Greys the close item of the window menu (the title bar's close button). Tao does this once for
/// `closable(false)`, but it was once found enabled on the CI runner (two notices at once), so the
/// notice re-applies it after creation and on every top-most tick.
fn disable_close(hwnd: windows::Win32::Foundation::HWND) {
    use windows::Win32::UI::WindowsAndMessaging::{
        EnableMenuItem, GetSystemMenu, MF_BYCOMMAND, MF_GRAYED, SC_CLOSE,
    };
    // SAFETY: plain calls on our own window; a stale handle only makes them fail.
    unsafe {
        let menu = GetSystemMenu(hwnd, false);
        if !menu.is_invalid() {
            let _ = EnableMenuItem(menu, SC_CLOSE, MF_BYCOMMAND | MF_GRAYED);
        }
    }
}

/// Puts the window back on top every [`TOPMOST_EVERY`] without activating it (and keeps its close
/// button grey), until `stop` is dropped or the window is gone.
fn start_topmost_ticker(app: AppHandle, hwnd: isize, stop: mpsc::Receiver<()>) {
    let _ = std::thread::Builder::new()
        .name("agent-notice-topmost".into())
        .spawn(move || {
            use windows::Win32::Foundation::HWND;
            use windows::Win32::UI::WindowsAndMessaging::{
                HWND_TOPMOST, IsWindow, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, SetWindowPos,
            };
            while let Err(mpsc::RecvTimeoutError::Timeout) = stop.recv_timeout(TOPMOST_EVERY) {
                // SAFETY: IsWindow accepts any value.
                if !unsafe { IsWindow(Some(HWND(hwnd as *mut _))) }.as_bool() {
                    return;
                }
                let posted = app.run_on_main_thread(move || {
                    // SAFETY: plain call; a stale handle only makes it fail.
                    let _ = unsafe {
                        SetWindowPos(
                            HWND(hwnd as *mut _),
                            Some(HWND_TOPMOST),
                            0,
                            0,
                            0,
                            0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                        )
                    };
                    disable_close(HWND(hwnd as *mut _));
                });
                if posted.is_err() {
                    return;
                }
            }
        });
}

/// Builds the window for `url` (from the runner's thread: Tauri creates it on the event loop and
/// waits), then sets what the builder cannot (WebView2 settings, process-failure handler), greys
/// the close button and brings the window to the front on the main thread.
fn build_window(
    app: &AppHandle,
    label: String,
    url: tauri::Url,
    server: String,
    data_dir: PathBuf,
    state: Arc<NoticeState>,
    log: Log,
) -> Result<WebviewWindow, String> {
    let (w, h) = work_area(app);
    let spec = notice_spec(w, h);
    let window = WebviewWindowBuilder::new(app, label, WebviewUrl::External(url))
        .title(spec.title)
        .inner_size(spec.width, spec.height)
        .center()
        .always_on_top(spec.always_on_top)
        .closable(spec.closable)
        .minimizable(spec.minimizable)
        .maximizable(spec.maximizable)
        .resizable(spec.resizable)
        .skip_taskbar(spec.skip_taskbar)
        .incognito(spec.incognito)
        .focused(spec.focused)
        .decorations(spec.decorations)
        .devtools(spec.devtools)
        .data_directory(data_dir)
        .on_navigation(move |u| notice_navigation_allowed(u, &server))
        .on_new_window(|_, _| NewWindowResponse::Deny)
        .build()
        .map_err(|e| e.to_string())?;
    let configured = window.with_webview(move |wv| {
        // SAFETY: with_webview runs this on the main thread.
        if let Err(e) = unsafe { configure_webview(wv.controller(), &spec, state, log.clone()) } {
            log(&format!("notice window settings: {e}"));
        }
    });
    if let Err(e) = configured {
        let _ = window.destroy();
        return Err(e.to_string());
    }
    if let Ok(hwnd) = window.hwnd() {
        let hwnd = hwnd.0 as isize;
        let _ = app.run_on_main_thread(move || {
            use windows::Win32::Foundation::HWND;
            disable_close(HWND(hwnd as *mut _));
            bring_to_front(HWND(hwnd as *mut _));
        });
    }
    Ok(window)
}

impl NoticeWindow for WebViewNotice {
    fn open(&mut self, url: &str, _display_id: i64) -> Result<(), String> {
        self.close();
        let parsed = tauri::Url::parse(url).map_err(|e| format!("bad notice url: {e}"))?;
        if !notice_navigation_allowed(&parsed, &self.server) {
            return Err("not the server's notice page".into());
        }
        let state = Arc::new(NoticeState::default());
        let label = format!("notice-{}", self.next.fetch_add(1, Ordering::SeqCst));
        // registered before the window exists, so no event of it is missed
        self.registry
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(label.clone(), state.clone());
        let built = build_window(
            &self.app,
            label.clone(),
            parsed,
            self.server.clone(),
            self.data_dir.clone(),
            state.clone(),
            self.log.clone(),
        );
        match built {
            Ok(window) => {
                (self.log)("notice window: shown");
                let (stop, ticks) = mpsc::channel();
                if let Ok(hwnd) = window.hwnd() {
                    start_topmost_ticker(self.app.clone(), hwnd.0 as isize, ticks);
                }
                self.shown = Some(Shown {
                    window,
                    state,
                    _ticker: stop,
                });
                Ok(())
            }
            Err(e) => {
                self.registry
                    .lock()
                    .unwrap_or_else(|e| e.into_inner())
                    .remove(&label);
                (self.log)(&format!(
                    "notice window not created ({e}); opening the default browser"
                ));
                open_in_browser(url)
            }
        }
    }

    fn close(&mut self) {
        let Some(shown) = self.shown.take() else {
            return;
        };
        shown.state.begin_close();
        let _ = shown.window.destroy();
    }

    /// Polled by the runner at least every 2 s while a notice is shown. A window that went away, or
    /// whose page died (a WebView2 event, or the browser process found gone here), is reported
    /// once and closed for good: the server's next `show_notice` makes a fresh window.
    fn closed_by_user(&mut self) -> bool {
        let Some(shown) = &self.shown else {
            return false;
        };
        if shown.state.check_browser() {
            (self.log)("notice window: the WebView2 browser process is gone");
        }
        if !shown.state.take_closed_by_user() {
            return false;
        }
        if shown.state.page_gone() {
            (self.log)("notice window: closing the window whose page is gone");
        }
        self.close();
        true
    }
}

/// When Tauri cannot start at all: the notice goes to the default browser (no close tracking).
struct BrowserNotice;

impl NoticeWindow for BrowserNotice {
    fn open(&mut self, url: &str, _display_id: i64) -> Result<(), String> {
        open_in_browser(url)
    }
    fn close(&mut self) {}
    fn closed_by_user(&mut self) -> bool {
        false
    }
}

/// `agent --dialog webview`: the Tauri event loop on this (main) thread, the runner and its window
/// activity on another; the runner's end ends the app with its exit code (0, 3, 4, 5; 1 when the
/// session cannot be told). No plugins and no single instance: one agent per session, apart from
/// the app mode.
pub fn run_webview_agent(cfg: AgentConfig) -> i32 {
    let log = log_stderr();
    let session_id = match current_session_id() {
        Ok(id) => id,
        Err(e) => {
            log(&format!("cannot tell this process's session: {e}"));
            return 1;
        }
    };
    let data_dir = notice_data_dir(&local_app_data().unwrap_or_else(std::env::temp_dir));
    let client = Arc::new(ServerClient::new(
        cfg.server.clone(),
        cfg.token.clone(),
        cfg.server_key,
        Box::new(UreqTransport::new()),
    ));
    let server = cfg.server.clone();
    let runner_for = {
        let (cfg, log) = (Arc::new(cfg), log.clone());
        move |window: Box<dyn NoticeWindow>| {
            let runner =
                AgentRunner::new(&cfg, client.clone(), window, session_id, std::process::id())
                    .with_log(log.clone());
            run_with_activity(runner, WindowActivity::new(client).with_log(log))
        }
    };
    let code = Arc::new(AtomicI32::new(EXIT_OK));
    let done = Arc::new(AtomicBool::new(false));
    let registry = NoticeRegistry::default();
    let built = {
        let (code, done, log) = (code.clone(), done.clone(), log.clone());
        let runner_for = runner_for.clone();
        let notices = registry.clone();
        tauri::Builder::default()
            .setup(move |app| {
                let handle = app.handle().clone();
                std::thread::Builder::new()
                    .name("agent-runner".into())
                    .spawn(move || {
                        let window =
                            WebViewNotice::new(handle.clone(), server, data_dir, notices, log);
                        let c = runner_for(Box::new(window));
                        code.store(c, Ordering::SeqCst);
                        done.store(true, Ordering::SeqCst);
                        handle.exit(c);
                    })?;
                Ok(())
            })
            .build(crate::app::context())
    };
    let app = match built {
        Ok(app) => app,
        Err(e) => {
            log(&format!(
                "the window system did not start ({e}); notices open in the default browser"
            ));
            return runner_for(Box::new(BrowserNotice));
        }
    };
    let running = done.clone();
    app.run_return(move |_, event| match event {
        // Window events reach this callback from the window's creation on (a window's own
        // listeners are attached a moment later: an early Alt+F4 would slip past them).
        RunEvent::WindowEvent { label, event, .. } => {
            on_notice_window_event(&registry, &label, &event, &log)
        }
        // The last window closing (a notice the user got rid of) must not end the agent.
        RunEvent::ExitRequested {
            api, code: None, ..
        } if !running.load(Ordering::SeqCst) => api.prevent_exit(),
        _ => {}
    });
    code.load(Ordering::SeqCst)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The values `build_window` passes to the builder. That the window really has them (top-most,
    /// no close, minimise, maximise or sizing, 640×600) is checked on a real window in
    /// tests/agent_webview.rs (review item 12); `skip_taskbar` is not visible in the window's
    /// styles (tao removes the taskbar button through ITaskbarList) and is checked at P8.
    #[test]
    fn notice_window_spec_is_a_topmost_modal() {
        let s = notice_spec(1920.0, 1040.0);
        assert_eq!(
            s,
            NoticeSpec {
                title: "MCP Monitor 고지",
                width: 640.0,
                height: 600.0,
                always_on_top: true,
                closable: false,
                minimizable: false,
                maximizable: false,
                resizable: false,
                skip_taskbar: true,
                incognito: true,
                focused: true,
                decorations: true,
                context_menu: false,
                devtools: false,
                accelerator_keys: false
            }
        );
    }

    #[test]
    fn notice_size_fits_the_work_area() {
        assert_eq!(notice_size(1920.0, 1040.0), (640.0, 600.0));
        assert_eq!(notice_size(800.0, 560.0), (640.0, 528.0));
        assert_eq!(notice_size(500.0, 400.0), (468.0, 368.0));
        assert_eq!(notice_size(300.0, 250.0), (320.0, 300.0));
    }

    #[test]
    fn notice_navigation_allows_only_the_notice_page() {
        let server = "http://127.0.0.1:8700";
        let ok = |u: &str| notice_navigation_allowed(&tauri::Url::parse(u).unwrap(), server);
        assert!(
            ok("http://127.0.0.1:8700/notice#d=1&t=tok_ABCDEFGHIJKLmnop")
                && ok("http://127.0.0.1:8700/notice")
        );
        for bad in [
            "http://127.0.0.1:8700/admin",
            "http://127.0.0.1:8701/notice",
            "http://localhost:8700/notice",
            "https://127.0.0.1:8700/notice",
            "http://u@127.0.0.1:8700/notice",
            "http://127.0.0.1:8700/notice?x=1",
            "http://127.0.0.1:8700/notice/x",
            "file:///C:/Windows/win.ini",
            "https://evil.example/notice",
        ] {
            assert!(!ok(bad), "{bad}");
        }
    }

    #[test]
    fn notice_navigation_refuses_the_rest_too() {
        let server = "http://127.0.0.1:8700";
        let ok = |u: &str| notice_navigation_allowed(&tauri::Url::parse(u).unwrap(), server);
        for bad in [
            "http://127.0.0.1:8700/notice?",
            "http://:p@127.0.0.1:8700/notice",
            "http://127.0.0.1:8700/Notice",
            "http://127.0.0.1:8700/",
            "about:blank",
            "data:text/html,<p>x</p>",
            "javascript:alert(1)",
        ] {
            assert!(!ok(bad), "{bad}");
        }
        // the server's own spelling does not matter, the parsed parts do
        assert!(notice_navigation_allowed(
            &tauri::Url::parse("http://127.0.0.1:8700/notice#d=2").unwrap(),
            "http://127.0.0.1:8700/"
        ));
        assert!(notice_navigation_allowed(
            &tauri::Url::parse("http://127.0.0.1:80/notice").unwrap(),
            "http://127.0.0.1"
        ));
        assert!(!notice_navigation_allowed(
            &tauri::Url::parse("http://127.0.0.1:8700/notice").unwrap(),
            "not a url"
        ));
    }

    #[test]
    fn close_requests_are_refused_unless_we_close() {
        let s = NoticeState::default();
        assert!(s.should_prevent_close());
        s.on_destroyed(); // destroyed without our close (e.g. ended from outside)
        assert!(s.take_closed_by_user() && !s.take_closed_by_user());
        s.reset();
        s.begin_close();
        assert!(!s.should_prevent_close());
        s.on_destroyed();
        assert!(!s.take_closed_by_user());
    }

    #[test]
    fn a_failed_webview_counts_as_closed_by_the_user() {
        let s = NoticeState::default();
        s.on_process_failed();
        assert!(s.take_closed_by_user());
        s.begin_close();
        s.on_process_failed(); // while we close it: not the user
        assert!(!s.take_closed_by_user());
    }

    /// A browser process the test ends by hand.
    #[derive(Clone, Default)]
    struct FakeBrowser(Arc<AtomicBool>);

    impl BrowserProcess for FakeBrowser {
        fn exited(&self) -> bool {
            self.0.load(Ordering::SeqCst)
        }
    }

    /// Review I3: no WebView2 event at all (as on the CI runner in Task 11), only the browser
    /// process gone: the runner's poll finds it, once, and the page counts as gone.
    #[test]
    fn a_gone_browser_process_closes_the_notice_once_without_any_webview2_event() {
        let s = NoticeState::default();
        assert!(!s.check_browser(), "nothing watched yet");
        let browser = FakeBrowser::default();
        s.watch_browser(Box::new(browser.clone()));
        assert!(!s.check_browser() && !s.page_gone() && !s.take_closed_by_user());
        browser.0.store(true, Ordering::SeqCst);
        assert!(s.check_browser());
        assert!(s.page_gone() && s.take_closed_by_user());
        // Counted once: neither the next poll nor a late WebView2 event reports it again.
        assert!(!s.check_browser());
        s.on_process_failed();
        assert!(!s.take_closed_by_user());
    }

    #[test]
    fn a_webview2_event_and_the_poll_together_count_once() {
        let s = NoticeState::default();
        let browser = FakeBrowser::default();
        s.watch_browser(Box::new(browser.clone()));
        browser.0.store(true, Ordering::SeqCst);
        s.on_process_failed(); // ProcessFailed or BrowserProcessExited came first
        assert!(!s.check_browser());
        assert!(s.page_gone() && s.take_closed_by_user() && !s.take_closed_by_user());
    }

    #[test]
    fn the_browser_ending_because_we_close_the_window_is_not_a_user_close() {
        let s = NoticeState::default();
        let browser = FakeBrowser::default();
        s.watch_browser(Box::new(browser.clone()));
        s.begin_close();
        browser.0.store(true, Ordering::SeqCst);
        assert!(!s.check_browser());
        s.on_process_failed();
        assert!(!s.page_gone() && !s.take_closed_by_user());
        // A new window starts clean and watches nothing until told.
        s.reset();
        assert!(!s.check_browser() && !s.page_gone() && s.should_prevent_close());
    }

    #[test]
    fn only_a_gone_browser_or_page_renderer_closes_the_notice() {
        use webview2_com::Microsoft::Web::WebView2::Win32::*;
        assert!(process_failure_closes(
            COREWEBVIEW2_PROCESS_FAILED_KIND_BROWSER_PROCESS_EXITED.0
        ));
        assert!(process_failure_closes(
            COREWEBVIEW2_PROCESS_FAILED_KIND_RENDER_PROCESS_EXITED.0
        ));
        for other in [
            COREWEBVIEW2_PROCESS_FAILED_KIND_RENDER_PROCESS_UNRESPONSIVE,
            COREWEBVIEW2_PROCESS_FAILED_KIND_FRAME_RENDER_PROCESS_EXITED,
            COREWEBVIEW2_PROCESS_FAILED_KIND_GPU_PROCESS_EXITED,
            COREWEBVIEW2_PROCESS_FAILED_KIND_UTILITY_PROCESS_EXITED,
        ] {
            assert!(!process_failure_closes(other.0), "{other:?}");
        }
    }

    #[test]
    fn a_destroyed_notice_window_is_recorded_and_forgotten() {
        let lines = Arc::new(Mutex::new(Vec::<String>::new()));
        let l = lines.clone();
        let log: Log = Arc::new(move |s: &str| l.lock().unwrap().push(s.to_string()));
        let registry = NoticeRegistry::default();
        let (ours, theirs) = (
            Arc::new(NoticeState::default()),
            Arc::new(NoticeState::default()),
        );
        registry
            .lock()
            .unwrap()
            .insert("notice-1".into(), ours.clone());
        registry
            .lock()
            .unwrap()
            .insert("notice-2".into(), theirs.clone());
        theirs.begin_close();
        on_notice_window_event(&registry, "notice-1", &tauri::WindowEvent::Destroyed, &log);
        on_notice_window_event(&registry, "notice-2", &tauri::WindowEvent::Destroyed, &log);
        on_notice_window_event(&registry, "main", &tauri::WindowEvent::Destroyed, &log); // not a notice
        assert!(ours.take_closed_by_user());
        assert!(!theirs.take_closed_by_user());
        assert!(registry.lock().unwrap().is_empty());
        on_notice_window_event(
            &registry,
            "notice-1",
            &tauri::WindowEvent::Focused(true),
            &log,
        );
        assert_eq!(
            lines.lock().unwrap().as_slice(),
            ["notice window: gone without a close_notice"]
        );
        assert!(!ours.take_closed_by_user());
    }

    #[test]
    fn notice_profile_lives_under_the_removed_folder() {
        assert_eq!(
            notice_data_dir(Path::new(r"C:\Users\hong\AppData\Local")),
            Path::new(r"C:\Users\hong\AppData\Local\mcp-monitor\notice-webview")
        );
    }

    #[test]
    fn local_app_data_is_this_users_folder() {
        let p = local_app_data().unwrap();
        assert!(p.is_absolute() && p.is_dir(), "{}", p.display());
    }
}
