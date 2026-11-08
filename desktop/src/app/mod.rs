//! The window side of the exe: with no arguments it decides between installing, upgrading and
//! opening the window (Y12); `app` is the single-instance WebView2 window on the local channel
//! with a tray icon (Y11); `autostart on|off` is the user's sign-in start.
//!
//! The window only shows `http://127.0.0.1:<local port>` and its own "connecting" page; every
//! other web address goes to the default browser and anything else is refused ([`nav`]). New
//! windows are never made. Devtools are off. Closing the window hides it (the tray stays and the
//! service keeps running); `트레이 종료` ends the app. A second start brings the first window
//! forward (single instance, this mode only).

pub mod autostart;
pub mod detect;
pub mod nav;
pub mod tray;

use crate::cli::AppArgs;
use crate::install::host::Installed;
use crate::install::install_plan::service_folders;
use crate::version::{Version, product};
use detect::{AutoAction, InstallInfo, app_data_dir, app_url, decide, installed_version};
use nav::{NavDecision, classify_navigation};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};
use tauri::webview::NewWindowResponse;
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

pub const MAIN_LABEL: &str = "main";
pub const WINDOW_TITLE: &str = "MCP Monitor";
/// The error box of `app` when nothing tells the local port.
pub const NOT_INSTALLED: &str =
    "MCP Monitor가 설치되어 있지 않습니다. mcp-monitor.exe를 다시 실행해 설치하세요.";
/// The box when the window would run with an administrator's token (review item 18).
pub const ELEVATED_APP: &str = "관리자 권한으로 실행 중이라 MCP Monitor 창을 열지 않습니다(창과 트레이는 사용자 권한으로만 엽니다). 시작 메뉴의 MCP Monitor로 여세요.";
/// The information box after an install or upgrade that succeeded in an elevated run: the
/// window is not opened ([`ELEVATED_APP`]), but nothing failed (Plan 6 re-review, minor 2).
pub const INSTALLED_ELEVATED: &str = "설치를 마쳤습니다. 관리자 권한으로 실행 중이라 MCP Monitor 창은 열지 않습니다(창과 트레이는 사용자 권한으로만 엽니다). 시작 메뉴의 MCP Monitor로 여세요.";
/// How often the "connecting" page asks the server, and when it says the service is not answering.
pub const CONNECT_EVERY: Duration = Duration::from_secs(1);
pub const STOPPED_AFTER: Duration = Duration::from_secs(30);
pub const STOPPED_EVERY: Duration = Duration::from_secs(5);
const STOPPED_PAGE: &str = "http://tauri.localhost/index.html#stopped";

/// The Tauri context of this exe (config, the "connecting" page, the icon). One expansion for
/// the app and the agent.
pub fn context() -> tauri::Context<tauri::Wry> {
    tauri::generate_context!()
}

/// What the window modes need from this PC beyond [`crate::Elevator`]. [`crate::SystemElevator`]
/// is the real one; unit tests use a fake, so no test opens a window, a message box, a process or
/// a registry key.
pub trait Desktop {
    /// The Apps & features entry (`DisplayVersion`, `InstallLocation`).
    fn installed(&self) -> Option<Installed>;
    fn service_exists(&self) -> bool;
    /// The service's command line (a 1.0.0 install names its folders only there, F13).
    fn service_bin_path(&self) -> Option<String>;
    /// A folder variable (`ProgramFiles`, `ProgramData`).
    fn env_folder(&self, name: &str) -> Option<PathBuf>;
    /// A Yes/No message box; true for Yes.
    fn ask_yes_no(&self, text: &str) -> bool;
    /// Starts `<exe> app` as this (non-elevated) user without waiting.
    fn start_app(&self, exe: &Path) -> Result<(), String>;
    /// The window and the tray until `트레이 종료`; the exit code.
    fn open_window(&self, target: AppTarget, background: bool) -> i32;
    /// Writes or removes the current user's `Run` value for `install_dir`.
    fn set_autostart(&self, install_dir: &Path, on: bool) -> Result<(), String>;
}

/// What the window opens: the local channel's port (from `install.json`, or `--server-url` in a
/// development build) and the install folder (for the tray's sign-in item).
#[derive(Debug, Clone, PartialEq)]
pub struct AppTarget {
    pub info: InstallInfo,
    pub install_dir: Option<PathBuf>,
}

/// The port of a development `--server-url`: exactly `http://127.0.0.1:<port>` (a path of `/` is
/// fine), the only origin the window accepts.
pub fn server_url_port(url: &str) -> Option<u16> {
    let u = Url::parse(url).ok()?;
    (u.scheme() == "http"
        && u.host_str() == Some("127.0.0.1")
        && u.username().is_empty()
        && u.password().is_none()
        && u.path() == "/"
        && u.query().is_none()
        && u.fragment().is_none())
    .then(|| u.port())
    .flatten()
}

/// The window's target: `--server-url`'s port, else `<install_dir>\install.json`; `None` when
/// neither tells (not installed).
pub fn app_target(server_url: Option<&str>, install_dir: Option<PathBuf>) -> Option<AppTarget> {
    let info = match server_url {
        Some(url) => InstallInfo {
            version: crate::version::PRODUCT.to_string(),
            local_port: server_url_port(url)?,
            external_port: 0,
            data_root: PathBuf::new(),
        },
        None => detect::read_install_info(install_dir.as_deref()?)?,
    };
    Some(AppTarget { info, install_dir })
}

/// The install folder: the Apps & features location, else the service's binPath (a 1.0.0 install,
/// F13), else `%ProgramFiles%\MCP Monitor` (what a new install uses).
pub fn install_dir_of(
    installed: Option<&Installed>,
    service_bin_path: Option<&str>,
    program_files: Option<&Path>,
) -> Option<PathBuf> {
    installed
        .map(|i| i.install_location.clone())
        .or_else(|| service_folders(service_bin_path?)?.install_dir)
        .or_else(|| program_files.map(|p| p.join("MCP Monitor")))
}

/// The data root an install into `install_dir` would use: `install.json`, else the service's
/// binPath, else `%ProgramData%\MCP Monitor`.
fn data_root_of(
    install_dir: Option<&Path>,
    service_bin_path: Option<&str>,
    program_data: Option<&Path>,
) -> Option<PathBuf> {
    install_dir
        .and_then(detect::read_install_info)
        .map(|i| i.data_root)
        .or_else(|| service_folders(service_bin_path?)?.data_root)
        .or_else(|| program_data.map(|p| p.join("MCP Monitor")))
}

fn shown(p: Option<&Path>) -> String {
    p.map_or_else(|| "(알 수 없음)".to_string(), |p| p.display().to_string())
}

pub fn install_prompt(install_dir: Option<&Path>, data_root: Option<&Path>) -> String {
    format!(
        "MCP Monitor가 이 PC에 설치되어 있지 않습니다.\n\n지금 설치할까요? 관리자 권한이 필요합니다.\n설치 위치: {}\n데이터: {}",
        shown(install_dir),
        shown(data_root)
    )
}

pub fn upgrade_prompt(installed: Option<Version>, own: Version) -> String {
    let from = installed.map_or_else(|| "알 수 없는 버전".to_string(), |v| v.to_string());
    format!(
        "설치된 MCP Monitor {from}을(를) {own}(으)로 업그레이드할까요?\n\n서비스가 잠시 멈추고, 데이터와 설정은 그대로 남습니다. 관리자 권한이 필요합니다."
    )
}

pub fn older_notice(installed: Version, own: Version) -> String {
    format!(
        "설치된 MCP Monitor({installed})가 이 실행 파일({own})보다 새롭습니다. 설치된 MCP Monitor의 창을 엽니다."
    )
}

/// No arguments (Y12): install or upgrade after a Yes (the same exe elevated with
/// `install --interactive`, which shows its own result), then the installed copy's window; the
/// window when the same version is installed; a notice, then the installed copy's window, when a
/// newer one is (no downgrade). No, or a cancelled UAC prompt, ends with 0.
pub fn run_auto(sys: &dyn crate::System) -> i32 {
    let own = product();
    let arp = sys.installed();
    let bin_path = sys.service_bin_path();
    let install_dir = install_dir_of(
        arp.as_ref(),
        bin_path.as_deref(),
        sys.env_folder("ProgramFiles").as_deref(),
    );
    let installed = installed_version(
        arp.as_ref().map(|a| a.version.clone()),
        install_dir.as_deref().unwrap_or(Path::new("")),
    );
    let action = decide(installed, sys.service_exists(), own);
    // Review item 17 (F06): an install or upgrade run from the installed copy (or its .staging /
    // .old neighbour) would be refused at `(stage)` after the UAC prompt: say so first.
    if matches!(action, AutoAction::Install | AutoAction::Upgrade { .. })
        && let (Ok(me), Some(dir)) = (sys.current_exe(), install_dir.as_deref())
        && let Some(why) = crate::install::stage::running_inside_problem(&me, dir, &own.to_string())
    {
        sys.error_box(&why);
        return 1;
    }
    match action {
        AutoAction::App => open_installed(sys, install_dir),
        AutoAction::OlderThanInstalled { installed } => {
            sys.info_box(&older_notice(installed, own));
            open_installed(sys, install_dir)
        }
        AutoAction::Install => {
            let data_root = data_root_of(
                install_dir.as_deref(),
                bin_path.as_deref(),
                sys.env_folder("ProgramData").as_deref(),
            );
            if !sys.ask_yes_no(&install_prompt(
                install_dir.as_deref(),
                data_root.as_deref(),
            )) {
                return 0;
            }
            install_then_open(sys, vec!["install".into(), "--interactive".into()])
        }
        AutoAction::Upgrade { installed } => {
            if !sys.ask_yes_no(&upgrade_prompt(installed, own)) {
                return 0;
            }
            let mut args = vec!["install".to_string()];
            if let Some(dir) = &install_dir {
                args.push("--install-dir".into());
                args.push(dir.display().to_string());
            }
            args.push("--interactive".into());
            install_then_open(sys, args)
        }
    }
}

/// Runs the installer elevated; on 0 opens the window of the copy it installed (its Apps &
/// features location), or, when this process is itself elevated, ends with an information box
/// ([`INSTALLED_ELEVATED`]) and 0. Its non-zero code is ours (it showed why); a cancelled UAC
/// prompt is 0.
fn install_then_open(sys: &dyn crate::System, args: Vec<String>) -> i32 {
    let exe = match sys.current_exe() {
        Ok(exe) => exe,
        Err(e) => {
            sys.error_box(&format!("실행 파일 위치를 알 수 없습니다: {e}"));
            return 1;
        }
    };
    match sys.elevate_and_wait(&exe, &args) {
        Ok(0) if sys.is_elevated() => {
            sys.info_box(INSTALLED_ELEVATED);
            0
        }
        Ok(0) => open_installed(sys, sys.installed().map(|i| i.install_location)),
        Ok(code) => code,
        Err(e) if e == crate::winutil::ELEVATION_CANCELLED => 0,
        Err(e) => {
            sys.error_box(&e);
            1
        }
    }
}

/// The window of the installed copy (F27): when this exe is not `<I>\mcp-monitor.exe` (a download)
/// and that file exists, it is started (`app`) and this one ends, so the download is not kept busy
/// by the tray; otherwise (or if it cannot be started) this process opens the window.
fn open_installed(sys: &dyn crate::System, install_dir: Option<PathBuf>) -> i32 {
    // A copy started from here would inherit an administrator's token (review item 18).
    if sys.is_elevated() {
        sys.error_box(ELEVATED_APP);
        return 1;
    }
    if let Some(exe) = install_dir.map(|d| d.join("mcp-monitor.exe")) {
        let is_me = sys
            .current_exe()
            .is_ok_and(|me| crate::install::paths::same_path(&me, &exe));
        if !is_me && exe.is_file() && sys.start_app(&exe).is_ok() {
            return 0;
        }
    }
    run_app_command(sys, &AppArgs::default())
}

/// `app`: the window for the installed server (the Apps & features location, else this exe's own
/// folder when it holds `install.json`), or `--server-url` in a development build. Not installed:
/// an error box and 1. Elevated: [`ELEVATED_APP`] and 1 (the window, the tray and its sign-in
/// item belong to the user's own token, review item 18) — except a development build attached to
/// a development server with `--server-url` (no installed copy; the CI runner is elevated).
pub fn run_app_command(sys: &dyn crate::System, args: &AppArgs) -> i32 {
    let dev_server = cfg!(feature = "dev") && args.server_url.is_some();
    if sys.is_elevated() && !dev_server {
        sys.error_box(ELEVATED_APP);
        return 1;
    }
    let install_dir = sys.installed().map(|i| i.install_location).or_else(|| {
        let dir = sys.current_exe().ok()?.parent()?.to_path_buf();
        dir.join("install.json").is_file().then_some(dir)
    });
    match app_target(args.server_url.as_deref(), install_dir) {
        Some(target) => sys.open_window(target, args.background),
        None => {
            sys.error_box(NOT_INSTALLED);
            1
        }
    }
}

/// One step of the "connecting" page: the server answered → the admin screen; no answer for
/// [`STOPPED_AFTER`] → the `#stopped` text (once), then ask every [`STOPPED_EVERY`]; before that
/// every [`CONNECT_EVERY`].
#[derive(Debug, PartialEq)]
pub enum Connect {
    Open,
    ShowStopped,
    Wait(Duration),
}

pub fn connect_step(answered: bool, since_start: Duration, stopped_shown: bool) -> Connect {
    if answered {
        Connect::Open
    } else if stopped_shown {
        Connect::Wait(STOPPED_EVERY)
    } else if since_start >= STOPPED_AFTER {
        Connect::ShowStopped
    } else {
        Connect::Wait(CONNECT_EVERY)
    }
}

/// `GET http://127.0.0.1:<port>/api/channel` answered 200 (no proxy, no redirects, 2 s); else why not.
fn channel_answers(agent: &ureq::Agent, port: u16) -> Result<(), String> {
    match agent
        .get(format!("http://127.0.0.1:{port}/api/channel"))
        .call()
    {
        Ok(r) if r.status() == 200 => Ok(()),
        Ok(r) => Err(format!("status {}", r.status())),
        Err(e) => Err(e.to_string()),
    }
}

/// The thread behind the "connecting" page: asks the server until it answers, then shows the
/// admin screen (and ends).
fn start_connecting(window: WebviewWindow, port: u16, admin: Url) {
    let _ = std::thread::Builder::new()
        .name("app-connect".into())
        .spawn(move || {
            let agent = ureq::Agent::new_with_config(
                ureq::Agent::config_builder()
                    .proxy(None)
                    .http_status_as_error(false)
                    .max_redirects(0)
                    .timeout_global(Some(Duration::from_secs(2)))
                    .build(),
            );
            let start = Instant::now();
            let mut stopped_shown = false;
            let mut told = false;
            loop {
                let answer = channel_answers(&agent, port);
                if let Err(e) = &answer
                    && !std::mem::replace(&mut told, true)
                {
                    eprintln!("app window: waiting for the server ({e})");
                }
                match connect_step(answer.is_ok(), start.elapsed(), stopped_shown) {
                    Connect::Open => {
                        let opened = window.navigate(admin);
                        eprintln!("app window: the server answered; admin page ({opened:?})");
                        return;
                    }
                    Connect::ShowStopped => {
                        stopped_shown = true;
                        let stopped = Url::parse(STOPPED_PAGE).expect("a valid address");
                        let shown = window.navigate(stopped);
                        eprintln!("app window: no answer for 30 s; #stopped ({shown:?})");
                        if shown.is_err() {
                            return;
                        }
                        std::thread::sleep(STOPPED_EVERY);
                    }
                    Connect::Wait(wait) => std::thread::sleep(wait),
                }
            }
        });
}

/// Devtools off in the WebView2 settings too (the "Inspect" item of the context menu and F12).
///
/// # Safety
/// Main thread only (the WebView2 COM objects are single-threaded).
unsafe fn turn_off_devtools(
    controller: webview2_com::Microsoft::Web::WebView2::Win32::ICoreWebView2Controller,
) -> windows::core::Result<()> {
    // SAFETY: COM calls on the main thread that owns the controller.
    unsafe {
        controller
            .CoreWebView2()?
            .Settings()?
            .SetAreDevToolsEnabled(false)
    }
}

/// What a navigation the table does not allow does: a web page opens in the default browser.
fn leave(url: &Url, port: u16) -> NavDecision {
    let decision = classify_navigation(url.as_str(), port);
    if decision == NavDecision::OpenExternal {
        let _ = crate::winutil::open_in_browser(url.as_str());
    }
    decision
}

/// wry's own default browser arguments (kept when we pass ours).
const WRY_BROWSER_ARGS: &str = "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection";

/// Development builds only (Y24): `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` (e.g. the DevTools port
/// of the window tests) passed through the WebView2 options too — on the CI runner (an elevated
/// process) WebView2 did not apply the variable. `None` in every other build and without the variable.
fn dev_browser_args() -> Option<String> {
    if !cfg!(feature = "dev") {
        return None;
    }
    let extra = std::env::var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS").ok()?;
    let extra = extra.trim();
    (!extra.is_empty()).then(|| format!("{WRY_BROWSER_ARGS} {extra}"))
}

/// The main window on the "connecting" page (from `setup`, on the main thread).
fn build_main_window(
    app: &AppHandle,
    port: u16,
    data_dir: PathBuf,
    background: bool,
) -> Result<WebviewWindow, String> {
    let same_window = app.clone();
    let mut builder =
        WebviewWindowBuilder::new(app, MAIN_LABEL, WebviewUrl::App("index.html".into()));
    if let Some(args) = dev_browser_args() {
        builder = builder.additional_browser_args(&args);
    }
    let window = builder
        .title(WINDOW_TITLE)
        .inner_size(1280.0, 800.0)
        .min_inner_size(640.0, 600.0)
        .center()
        .visible(!background)
        .devtools(false)
        .data_directory(data_dir)
        .on_navigation(move |url| {
            let decision = leave(url, port);
            eprintln!(
                "app window: navigation to {}://{} {decision:?}",
                url.scheme(),
                url.host_str().unwrap_or_default()
            );
            decision == NavDecision::Allow
        })
        .on_new_window(move |url, _features| {
            if leave(&url, port) == NavDecision::Allow
                && let Some(main) = same_window.get_webview_window(MAIN_LABEL)
            {
                // Not from inside WebView2's own event: the navigation is queued to the loop.
                std::thread::spawn(move || {
                    let _ = main.navigate(url);
                });
            }
            NewWindowResponse::Deny
        })
        .build()
        .map_err(|e| e.to_string())?;
    let configured = window.with_webview(|wv| {
        // SAFETY: with_webview runs this on the main thread.
        if let Err(e) = unsafe { turn_off_devtools(wv.controller()) } {
            eprintln!("app window settings: {e}");
        }
    });
    if let Err(e) = configured {
        let _ = window.destroy();
        return Err(e.to_string());
    }
    Ok(window)
}

fn window_error(e: &str) -> String {
    format!(
        "MCP Monitor 창을 열 수 없습니다. Microsoft Edge WebView2 런타임이 설치되어 있는지 확인하세요.\n\n{e}"
    )
}

/// `app` for real: the WebView2 window, the tray and the single-instance hand-off; returns when
/// the user picks `트레이 종료` (0) or the window cannot be made (1, after an error box).
pub fn run_window(target: AppTarget, background: bool) -> i32 {
    if !cfg!(feature = "dev") {
        // Before any thread or WebView2 starts (Y24).
        crate::agent::config::strip_webview2_env(&mut crate::agent::config::ProcessEnv);
    }
    let port = target.info.local_port;
    let admin = Url::parse(&app_url(&target.info)).expect("a valid address");
    let data_dir =
        app_data_dir(&crate::agent::webview::local_app_data().unwrap_or_else(std::env::temp_dir));
    let install_dir = target.install_dir;
    let built = tauri::Builder::default()
        // App mode only: the agent and the installer may run many times (Y11).
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            tray::show_main(app)
        }))
        .setup(move |app| {
            let handle = app.handle().clone();
            match build_main_window(&handle, port, data_dir, background) {
                Ok(window) => {
                    eprintln!("app window: created");
                    if let Err(e) = tray::create(&handle, install_dir) {
                        eprintln!("tray icon: {e}");
                        // Without a tray a hidden window could never be opened.
                        let _ = window.show();
                    }
                    start_connecting(window, port, admin);
                }
                Err(e) => {
                    eprintln!("app window: not created: {e}");
                    crate::winutil::message_box(&window_error(&e), crate::winutil::MsgKind::Error);
                    handle.exit(1);
                }
            }
            Ok(())
        })
        .build(context());
    let app = match built {
        Ok(app) => app,
        Err(e) => {
            eprintln!("app: the window system did not start: {e}");
            crate::winutil::message_box(
                &window_error(&e.to_string()),
                crate::winutil::MsgKind::Error,
            );
            return 1;
        }
    };
    // Window events reach this callback from the window's creation on (its own listeners are
    // attached a moment later, Task 11).
    app.run_return(|app, event| match event {
        RunEvent::WindowEvent {
            label,
            event: tauri::WindowEvent::CloseRequested { api, .. },
            ..
        } if label == MAIN_LABEL => {
            api.prevent_close();
            if let Some(window) = app.get_webview_window(MAIN_LABEL) {
                let _ = window.hide();
            }
        }
        // Only `트레이 종료` (or a failed start) ends the app, never a last window going away.
        RunEvent::ExitRequested {
            api, code: None, ..
        } => api.prevent_exit(),
        _ => {}
    })
}

/// [`Desktop`] on this PC.
impl Desktop for crate::SystemElevator {
    fn installed(&self) -> Option<Installed> {
        use crate::install::host::Host;
        crate::install::host::SystemHost::new().installed()
    }
    fn service_exists(&self) -> bool {
        use crate::install::host::Host;
        crate::install::host::SystemHost::new().service_exists()
    }
    fn service_bin_path(&self) -> Option<String> {
        use crate::install::host::Host;
        crate::install::host::SystemHost::new().service_bin_path()
    }
    fn env_folder(&self, name: &str) -> Option<PathBuf> {
        std::env::var_os(name)
            .filter(|v| !v.is_empty())
            .map(PathBuf::from)
    }
    fn ask_yes_no(&self, text: &str) -> bool {
        crate::winutil::message_box(text, crate::winutil::MsgKind::YesNo)
            == crate::winutil::MsgAnswer::Yes
    }
    fn start_app(&self, exe: &Path) -> Result<(), String> {
        use std::process::{Command, Stdio};
        Command::new(exe)
            .arg("app")
            .current_dir(crate::winutil::system_dir())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map(drop)
            .map_err(|e| e.to_string())
    }
    fn open_window(&self, target: AppTarget, background: bool) -> i32 {
        run_window(target, background)
    }
    fn set_autostart(&self, install_dir: &Path, on: bool) -> Result<(), String> {
        autostart::set_autostart(&mut crate::install::registry::WinRegistry, install_dir, on)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_connecting_page_waits_30_seconds_then_says_the_service_is_stopped() {
        let s = Duration::from_secs;
        assert_eq!(connect_step(true, s(0), false), Connect::Open);
        assert_eq!(connect_step(false, s(0), false), Connect::Wait(s(1)));
        assert_eq!(connect_step(false, s(29), false), Connect::Wait(s(1)));
        assert_eq!(connect_step(false, s(30), false), Connect::ShowStopped);
        assert_eq!(connect_step(false, s(31), true), Connect::Wait(s(5)));
        assert_eq!(connect_step(true, s(300), true), Connect::Open);
        assert_eq!(
            classify_navigation(STOPPED_PAGE, 8700),
            NavDecision::Allow,
            "the window may show its own #stopped page"
        );
    }

    #[test]
    fn only_development_builds_pass_extra_browser_arguments() {
        if !cfg!(feature = "dev") {
            assert_eq!(dev_browser_args(), None);
        } else if let Some(args) = dev_browser_args() {
            assert!(args.starts_with(WRY_BROWSER_ARGS), "{args}");
        }
    }

    #[test]
    fn a_development_server_url_is_the_local_channel_only() {
        assert_eq!(server_url_port("http://127.0.0.1:9700"), Some(9700));
        assert_eq!(server_url_port("http://127.0.0.1:9700/"), Some(9700));
        for bad in [
            "http://127.0.0.1",
            "http://localhost:9700",
            "https://127.0.0.1:9700",
            "http://127.0.0.1:9700/admin",
            "http://u@127.0.0.1:9700",
            "http://127.0.0.1:9700/?x",
            "127.0.0.1:9700",
            "",
        ] {
            assert_eq!(server_url_port(bad), None, "{bad}");
        }
    }

    #[test]
    fn the_target_comes_from_install_json_or_the_development_server() {
        let d = tempfile::tempdir().unwrap();
        assert_eq!(app_target(None, None), None);
        assert_eq!(app_target(None, Some(d.path().to_path_buf())), None);
        std::fs::write(
            d.path().join("install.json"),
            r#"{"version":"1.1.0","local_port":9700,"external_port":9701,"data_root":"D:\\MCP"}"#,
        )
        .unwrap();
        let t = app_target(None, Some(d.path().to_path_buf())).unwrap();
        assert_eq!(
            (t.info.local_port, t.install_dir.as_deref()),
            (9700, Some(d.path()))
        );
        let dev = app_target(Some("http://127.0.0.1:5555"), None).unwrap();
        assert_eq!((dev.info.local_port, dev.install_dir), (5555, None));
        assert_eq!(app_url(&dev.info), "http://127.0.0.1:5555/admin");
        assert_eq!(app_target(Some("http://localhost:5555"), None), None);
    }

    #[test]
    fn the_install_folder_is_the_entry_then_the_service_then_program_files() {
        let pf = Path::new(r"C:\Program Files");
        let arp = Installed {
            version: "1.1.0".into(),
            install_location: PathBuf::from(r"D:\Apps\MCP Monitor"),
        };
        let old = r#""E:\MCP\bin\monitor\mcp-monitor.exe" service --root "E:\MCP Data" --local-port 9700"#;
        assert_eq!(
            install_dir_of(Some(&arp), Some(old), Some(pf)),
            Some(PathBuf::from(r"D:\Apps\MCP Monitor"))
        );
        assert_eq!(
            install_dir_of(None, Some(old), Some(pf)),
            Some(PathBuf::from(r"E:\MCP"))
        );
        assert_eq!(
            install_dir_of(None, Some(r"C:\Windows\x.exe"), Some(pf)),
            Some(PathBuf::from(r"C:\Program Files\MCP Monitor"))
        );
        assert_eq!(install_dir_of(None, None, None), None);
        assert_eq!(
            data_root_of(None, Some(old), Some(Path::new(r"C:\ProgramData"))),
            Some(PathBuf::from(r"E:\MCP Data"))
        );
        assert_eq!(
            data_root_of(None, None, Some(Path::new(r"C:\ProgramData"))),
            Some(PathBuf::from(r"C:\ProgramData\MCP Monitor"))
        );
    }

    #[test]
    fn prompts_say_what_happens_in_korean() {
        assert_eq!(
            install_prompt(
                Some(Path::new(r"C:\Program Files\MCP Monitor")),
                Some(Path::new(r"C:\ProgramData\MCP Monitor"))
            ),
            "MCP Monitor가 이 PC에 설치되어 있지 않습니다.\n\n지금 설치할까요? 관리자 권한이 필요합니다.\n설치 위치: C:\\Program Files\\MCP Monitor\n데이터: C:\\ProgramData\\MCP Monitor"
        );
        assert_eq!(
            upgrade_prompt(Some(Version(1, 0, 0)), Version(1, 1, 0)),
            "설치된 MCP Monitor 1.0.0을(를) 1.1.0(으)로 업그레이드할까요?\n\n서비스가 잠시 멈추고, 데이터와 설정은 그대로 남습니다. 관리자 권한이 필요합니다."
        );
        assert!(
            upgrade_prompt(None, Version(1, 1, 0))
                .starts_with("설치된 MCP Monitor 알 수 없는 버전을(를) 1.1.0(으)로")
        );
        assert_eq!(
            older_notice(Version(1, 2, 0), Version(1, 1, 0)),
            "설치된 MCP Monitor(1.2.0)가 이 실행 파일(1.1.0)보다 새롭습니다. 설치된 MCP Monitor의 창을 엽니다."
        );
    }
}
