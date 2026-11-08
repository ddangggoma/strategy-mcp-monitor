//! The app mode's notification-area icon: the app icon, tooltip "MCP Monitor", a left click opens
//! the window, and a menu with `창 열기`, the service's state (a grey line, refreshed every 5 s),
//! `로그인할 때 트레이 시작` (the user's `Run` value) and `트레이 종료` (ends this app only; the
//! service keeps running).

use super::autostart::{autostart_enabled, set_autostart};
use crate::install::registry::WinRegistry;
use std::path::PathBuf;
use std::time::Duration;
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager};

pub const TOOLTIP: &str = "MCP Monitor";
pub const OPEN_TEXT: &str = "창 열기";
pub const AUTOSTART_TEXT: &str = "로그인할 때 트레이 시작";
pub const QUIT_TEXT: &str = "트레이 종료";
/// How often the service line is refreshed.
pub const SERVICE_EVERY: Duration = Duration::from_secs(5);

const OPEN_ID: &str = "open";
const SERVICE_ID: &str = "service";
const AUTOSTART_ID: &str = "autostart";
const QUIT_ID: &str = "quit";

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ServiceState {
    Running,
    Starting,
    Stopping,
    Stopped,
    NotInstalled,
}

/// The state from `SERVICE_STATUS.dwCurrentState` (`None`: no such service, or it cannot be read).
pub fn service_state_from(current_state: Option<u32>) -> ServiceState {
    use windows::Win32::System::Services::{
        SERVICE_CONTINUE_PENDING, SERVICE_RUNNING, SERVICE_START_PENDING, SERVICE_STOP_PENDING,
    };
    match current_state {
        None => ServiceState::NotInstalled,
        Some(s) if s == SERVICE_RUNNING.0 => ServiceState::Running,
        Some(s) if s == SERVICE_START_PENDING.0 || s == SERVICE_CONTINUE_PENDING.0 => {
            ServiceState::Starting
        }
        Some(s) if s == SERVICE_STOP_PENDING.0 => ServiceState::Stopping,
        Some(_) => ServiceState::Stopped,
    }
}

/// The menu's service line.
pub fn service_label(state: ServiceState) -> &'static str {
    match state {
        ServiceState::Running => "서비스: 실행 중",
        ServiceState::Starting => "서비스: 시작하는 중",
        ServiceState::Stopping => "서비스: 멈추는 중",
        ServiceState::Stopped => "서비스: 중지됨",
        ServiceState::NotInstalled => "서비스: 설치 안 됨",
    }
}

/// `QueryServiceStatus` of the `mcp-monitor` service (no admin needed).
pub fn query_service_state() -> ServiceState {
    use crate::install::host::open_service;
    use windows::Win32::System::Services::{
        QueryServiceStatus, SERVICE_QUERY_STATUS, SERVICE_STATUS,
    };
    let current = open_service(SERVICE_QUERY_STATUS).and_then(|service| {
        let mut status = SERVICE_STATUS::default();
        // SAFETY: a valid handle and out pointer.
        unsafe { QueryServiceStatus(service.0, &mut status) }
            .ok()
            .map(|()| status.dwCurrentState.0)
    });
    service_state_from(current)
}

/// Shows the main window, restores it and brings it to the front.
pub fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(super::MAIN_LABEL) {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

/// The tray icon and its menu. `install_dir` (the Apps & features location) names the `Run`
/// value; without it (a development run against another server) the check item is grey.
pub fn create(app: &AppHandle, install_dir: Option<PathBuf>) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, OPEN_ID, OPEN_TEXT, true, None::<&str>)?;
    let service = MenuItem::with_id(
        app,
        SERVICE_ID,
        service_label(query_service_state()),
        false,
        None::<&str>,
    )?;
    let enabled = install_dir
        .as_deref()
        .is_some_and(|dir| autostart_enabled(&WinRegistry, dir));
    let autostart = CheckMenuItem::with_id(
        app,
        AUTOSTART_ID,
        AUTOSTART_TEXT,
        install_dir.is_some(),
        enabled,
        None::<&str>,
    )?;
    let quit = MenuItem::with_id(app, QUIT_ID, QUIT_TEXT, true, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[
            &open,
            &service,
            &PredefinedMenuItem::separator(app)?,
            &autostart,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )?;
    let mut builder = TrayIconBuilder::with_id("main")
        .tooltip(TOOLTIP)
        .menu(&menu)
        .show_menu_on_left_click(false);
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    let check = autostart.clone();
    builder
        .on_menu_event(move |app, event| match event.id().as_ref() {
            OPEN_ID => show_main(app),
            AUTOSTART_ID => {
                if let Some(dir) = &install_dir {
                    let want = check.is_checked().unwrap_or(false);
                    if let Err(e) = set_autostart(&mut WinRegistry, dir, want) {
                        crate::winutil::message_box(
                            &format!("로그인할 때 시작 설정을 바꾸지 못했습니다.\n\n{e}"),
                            crate::winutil::MsgKind::Error,
                        );
                    }
                    let _ = check.set_checked(autostart_enabled(&WinRegistry, dir));
                }
            }
            QUIT_ID => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main(tray.app_handle());
            }
        })
        .build(app)?;
    start_service_line(service);
    Ok(())
}

/// Refreshes the service line every [`SERVICE_EVERY`] until the app is gone.
fn start_service_line(item: MenuItem<tauri::Wry>) {
    let _ = std::thread::Builder::new()
        .name("tray-service-state".into())
        .spawn(move || {
            let mut shown = item.text().unwrap_or_default();
            loop {
                std::thread::sleep(SERVICE_EVERY);
                let text = service_label(query_service_state());
                if text != shown {
                    if item.set_text(text).is_err() {
                        return;
                    }
                    shown = text.to_string();
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;
    use windows::Win32::System::Services::*;

    #[test]
    fn the_service_line_names_the_state_in_korean() {
        let cases = [
            (None, "서비스: 설치 안 됨"),
            (Some(SERVICE_RUNNING.0), "서비스: 실행 중"),
            (Some(SERVICE_STOPPED.0), "서비스: 중지됨"),
            (Some(SERVICE_PAUSED.0), "서비스: 중지됨"),
            (Some(SERVICE_START_PENDING.0), "서비스: 시작하는 중"),
            (Some(SERVICE_CONTINUE_PENDING.0), "서비스: 시작하는 중"),
            (Some(SERVICE_STOP_PENDING.0), "서비스: 멈추는 중"),
        ];
        for (state, want) in cases {
            assert_eq!(service_label(service_state_from(state)), want, "{state:?}");
        }
    }

    #[test]
    fn this_pc_has_no_service_of_ours_or_reads_its_state() {
        // The dev PC and the CI runner have no `mcp-monitor` service; a PC with one reads it.
        let state = query_service_state();
        let exists = crate::install::host::open_service(SERVICE_QUERY_STATUS).is_some();
        assert_eq!(state == ServiceState::NotInstalled, !exists, "{state:?}");
    }

    #[test]
    fn menu_texts_are_korean_and_the_tooltip_is_the_product() {
        assert_eq!(
            (TOOLTIP, OPEN_TEXT, AUTOSTART_TEXT, QUIT_TEXT),
            (
                "MCP Monitor",
                "창 열기",
                "로그인할 때 트레이 시작",
                "트레이 종료"
            )
        );
    }
}
