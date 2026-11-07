//! Command line of `mcp-monitor.exe` (hand-written parser, appendix B).
//!
//! The elevated relaunch (Y13) never forwards the caller's raw argument strings: it rebuilds the
//! argument list from the parsed fields ([`relaunch_args`]), drops `--dry-run` and always ends
//! with `--interactive`. Only the installer modes can ask for elevation ([`needs_relaunch`]).

use std::collections::HashMap;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq)]
pub enum Command {
    Auto,
    App(AppArgs),
    Install(InstallArgs),
    Uninstall(UninstallArgs),
    AuditPolicy(AuditArgs),
    Agent(AgentArgs),
    Autostart(bool),
    VerifyPayload(PathBuf),
    Version,
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct InstallArgs {
    pub install_dir: Option<PathBuf>,
    pub data_root: Option<PathBuf>,
    pub open_firewall: bool,
    pub skip_audit_policy: bool,
    pub local_port: Option<u16>,
    pub external_port: Option<u16>,
    pub dry_run: bool,
    pub interactive: bool,
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct UninstallArgs {
    pub install_dir: Option<PathBuf>,
    pub data_root: Option<PathBuf>,
    pub remove_data: bool,
    pub restore_audit_policy: bool,
    pub dry_run: bool,
    pub interactive: bool,
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct AuditArgs {
    pub enable: bool,
    pub restore: Option<PathBuf>,
    pub data_root: Option<PathBuf>,
    pub dry_run: bool,
    pub interactive: bool,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Dialog {
    Webview,
    Print,
}

#[derive(Debug, Clone, PartialEq)]
pub struct AgentArgs {
    pub server: String,
    pub dialog: Dialog,
    pub url_file: Option<PathBuf>,
    pub unreachable_exit_sec: f64,
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct AppArgs {
    pub background: bool,
    /// Development builds only (`--features dev`, Y24).
    pub server_url: Option<String>,
}

/// A command-line error: one Korean sentence that names the option. Printed as `오류: <text>`, exit 2.
#[derive(Debug, Clone, PartialEq)]
pub struct ArgError(pub String);

/// Every command and option an operator can use; the operations guide must mention each one
/// (Task 15). `--server-url` is a development feature and is left out.
pub const DOCUMENTED_OPTIONS: &[&str] = &[
    "install",
    "uninstall",
    "audit-policy",
    "agent",
    "app",
    "autostart",
    "verify-payload",
    "--version",
    "--install-dir",
    "--data-root",
    "--open-firewall",
    "--skip-audit-policy",
    "--local-port",
    "--external-port",
    "--dry-run",
    "--interactive",
    "--remove-data",
    "--restore-audit-policy",
    "--enable",
    "--restore",
    "--background",
    "--server",
    "--dialog",
    "--url-file",
    "--unreachable-exit-sec",
];

/// The first-argument words (checked against [`DOCUMENTED_OPTIONS`]).
#[cfg(test)]
const COMMANDS: &[&str] = &[
    "install",
    "uninstall",
    "audit-policy",
    "agent",
    "app",
    "autostart",
    "verify-payload",
    "--version",
];

/// An option name and whether it takes a value.
type Spec = &'static [(&'static str, bool)];

const INSTALL_OPTIONS: Spec = &[
    ("--install-dir", true),
    ("--data-root", true),
    ("--open-firewall", false),
    ("--skip-audit-policy", false),
    ("--local-port", true),
    ("--external-port", true),
    ("--dry-run", false),
    ("--interactive", false),
];
const UNINSTALL_OPTIONS: Spec = &[
    ("--install-dir", true),
    ("--data-root", true),
    ("--remove-data", false),
    ("--restore-audit-policy", false),
    ("--dry-run", false),
    ("--interactive", false),
];
const AUDIT_OPTIONS: Spec = &[
    ("--enable", false),
    ("--restore", true),
    ("--data-root", true),
    ("--dry-run", false),
    ("--interactive", false),
];
const AGENT_OPTIONS: Spec = &[
    ("--server", true),
    ("--dialog", true),
    ("--url-file", true),
    ("--unreachable-exit-sec", true),
];
const APP_OPTIONS: Spec = &[("--background", false)];
const APP_DEV_OPTIONS: Spec = &[("--background", false), ("--server-url", true)];

/// The option tables of a release build, by command (checked against [`DOCUMENTED_OPTIONS`]).
#[cfg(test)]
const OPTION_SPECS: &[(&str, Spec)] = &[
    ("install", INSTALL_OPTIONS),
    ("uninstall", UNINSTALL_OPTIONS),
    ("audit-policy", AUDIT_OPTIONS),
    ("agent", AGENT_OPTIONS),
    ("app", APP_OPTIONS),
];

const DEFAULT_UNREACHABLE_EXIT_SEC: f64 = 120.0;

fn err(text: impl Into<String>) -> ArgError {
    ArgError(text.into())
}

/// The options given after a command: name → value (`None` for a flag).
struct Opts(HashMap<&'static str, Option<String>>);

impl Opts {
    fn parse(command: &str, args: &[String], spec: Spec) -> Result<Opts, ArgError> {
        let mut found = HashMap::new();
        let mut it = args.iter();
        while let Some(arg) = it.next() {
            let Some(&(name, takes_value)) = spec.iter().find(|(n, _)| n == arg) else {
                return Err(if arg.starts_with('-') {
                    err(format!("{arg}은(는) {command}에서 쓸 수 없는 옵션입니다"))
                } else {
                    err(format!("{command}에서 알 수 없는 인자입니다: {arg}"))
                });
            };
            if found.contains_key(name) {
                return Err(err(format!("{name}을(를) 두 번 지정했습니다")));
            }
            let value = if takes_value {
                match it.next() {
                    // A value that looks like an option is a missing value: `--install-dir --dry-run`
                    // must not install into a folder named "--dry-run".
                    None => return Err(err(format!("{name}에 값이 없습니다"))),
                    Some(v) if v.starts_with("--") => {
                        return Err(err(format!("{name}에 값이 없습니다")));
                    }
                    Some(v) if v.is_empty() => {
                        return Err(err(format!("{name}의 값이 비어 있습니다")));
                    }
                    Some(v) => Some(v.clone()),
                }
            } else {
                None
            };
            found.insert(name, value);
        }
        Ok(Opts(found))
    }

    fn flag(&self, name: &str) -> bool {
        self.0.contains_key(name)
    }

    fn value(&self, name: &str) -> Option<&str> {
        self.0.get(name).and_then(|v| v.as_deref())
    }

    fn path(&self, name: &str) -> Option<PathBuf> {
        self.value(name).map(PathBuf::from)
    }

    fn port(&self, name: &str) -> Result<Option<u16>, ArgError> {
        let Some(v) = self.value(name) else {
            return Ok(None);
        };
        let bad = || err(format!("{name}는 1에서 65535 사이의 숫자여야 합니다: {v}"));
        if v.is_empty() || v.len() > 5 || !v.bytes().all(|b| b.is_ascii_digit()) {
            return Err(bad());
        }
        match v.parse::<u32>() {
            Ok(n @ 1..=65535) => Ok(Some(n as u16)),
            _ => Err(bad()),
        }
    }
}

/// Parses the arguments after the program name (appendix B grammar).
pub fn parse(args: &[String]) -> Result<Command, ArgError> {
    let Some((first, rest)) = args.split_first() else {
        return Ok(Command::Auto);
    };
    match first.as_str() {
        "--version" => {
            if rest.is_empty() {
                Ok(Command::Version)
            } else {
                Err(err("--version 뒤에는 다른 인자를 둘 수 없습니다"))
            }
        }
        "app" => {
            let spec = if cfg!(feature = "dev") {
                APP_DEV_OPTIONS
            } else {
                APP_OPTIONS
            };
            let o = Opts::parse(first, rest, spec)?;
            Ok(Command::App(AppArgs {
                background: o.flag("--background"),
                server_url: o.value("--server-url").map(str::to_string),
            }))
        }
        "install" => {
            let o = Opts::parse(first, rest, INSTALL_OPTIONS)?;
            Ok(Command::Install(InstallArgs {
                install_dir: o.path("--install-dir"),
                data_root: o.path("--data-root"),
                open_firewall: o.flag("--open-firewall"),
                skip_audit_policy: o.flag("--skip-audit-policy"),
                local_port: o.port("--local-port")?,
                external_port: o.port("--external-port")?,
                dry_run: o.flag("--dry-run"),
                interactive: o.flag("--interactive"),
            }))
        }
        "uninstall" => {
            let o = Opts::parse(first, rest, UNINSTALL_OPTIONS)?;
            Ok(Command::Uninstall(UninstallArgs {
                install_dir: o.path("--install-dir"),
                data_root: o.path("--data-root"),
                remove_data: o.flag("--remove-data"),
                restore_audit_policy: o.flag("--restore-audit-policy"),
                dry_run: o.flag("--dry-run"),
                interactive: o.flag("--interactive"),
            }))
        }
        "audit-policy" => {
            let o = Opts::parse(first, rest, AUDIT_OPTIONS)?;
            let enable = o.flag("--enable");
            let restore = o.path("--restore");
            if enable == restore.is_some() {
                return Err(err(
                    "audit-policy에는 --enable 또는 --restore <파일> 중 하나만 지정합니다",
                ));
            }
            Ok(Command::AuditPolicy(AuditArgs {
                enable,
                restore,
                data_root: o.path("--data-root"),
                dry_run: o.flag("--dry-run"),
                interactive: o.flag("--interactive"),
            }))
        }
        "agent" => {
            let o = Opts::parse(first, rest, AGENT_OPTIONS)?;
            let Some(server) = o.value("--server") else {
                return Err(err("agent에는 --server <주소>가 필요합니다"));
            };
            let dialog = match o.value("--dialog") {
                None | Some("webview") => Dialog::Webview,
                Some("print") => Dialog::Print,
                Some(_) => return Err(err("--dialog는 webview 또는 print입니다")),
            };
            let url_file = o.path("--url-file");
            if dialog == Dialog::Print && url_file.is_none() {
                return Err(err("--dialog print에는 --url-file이 필요합니다"));
            }
            let unreachable_exit_sec = match o.value("--unreachable-exit-sec") {
                None => DEFAULT_UNREACHABLE_EXIT_SEC,
                Some(v) => match v.parse::<f64>() {
                    Ok(sec) if sec.is_finite() && sec > 0.0 => sec,
                    _ => {
                        return Err(err(format!(
                            "--unreachable-exit-sec는 0보다 큰 초 단위 숫자여야 합니다: {v}"
                        )));
                    }
                },
            };
            Ok(Command::Agent(AgentArgs {
                server: server.to_string(),
                dialog,
                url_file,
                unreachable_exit_sec,
            }))
        }
        "autostart" => match rest {
            [v] if v == "on" => Ok(Command::Autostart(true)),
            [v] if v == "off" => Ok(Command::Autostart(false)),
            _ => Err(err("autostart 뒤에는 on 또는 off 하나만 씁니다")),
        },
        "verify-payload" => match rest {
            [dir] if !dir.is_empty() && !dir.starts_with("--") => {
                Ok(Command::VerifyPayload(PathBuf::from(dir)))
            }
            _ => Err(err("verify-payload 뒤에는 빈 폴더 경로 하나만 씁니다")),
        },
        other if other.starts_with('-') => Err(err(format!("알 수 없는 옵션입니다: {other}"))),
        other => Err(err(format!("알 수 없는 명령입니다: {other}"))),
    }
}

fn path_arg(p: &Path) -> String {
    p.to_string_lossy().into_owned()
}

/// The arguments for the elevated copy of this exe, rebuilt from the parsed fields only (never the
/// caller's strings), in grammar order, without `--dry-run` and always ending with `--interactive`.
/// Empty for every command that is never elevated.
pub fn relaunch_args(cmd: &Command) -> Vec<String> {
    fn value(out: &mut Vec<String>, name: &str, v: String) {
        out.push(name.to_string());
        out.push(v);
    }
    let mut out: Vec<String> = Vec::new();
    match cmd {
        Command::Install(a) => {
            out.push("install".into());
            if let Some(p) = &a.install_dir {
                value(&mut out, "--install-dir", path_arg(p));
            }
            if let Some(p) = &a.data_root {
                value(&mut out, "--data-root", path_arg(p));
            }
            if a.open_firewall {
                out.push("--open-firewall".into());
            }
            if a.skip_audit_policy {
                out.push("--skip-audit-policy".into());
            }
            if let Some(port) = a.local_port {
                value(&mut out, "--local-port", port.to_string());
            }
            if let Some(port) = a.external_port {
                value(&mut out, "--external-port", port.to_string());
            }
        }
        Command::Uninstall(a) => {
            out.push("uninstall".into());
            if let Some(p) = &a.install_dir {
                value(&mut out, "--install-dir", path_arg(p));
            }
            if let Some(p) = &a.data_root {
                value(&mut out, "--data-root", path_arg(p));
            }
            if a.remove_data {
                out.push("--remove-data".into());
            }
            if a.restore_audit_policy {
                out.push("--restore-audit-policy".into());
            }
        }
        Command::AuditPolicy(a) => {
            out.push("audit-policy".into());
            if a.enable {
                out.push("--enable".into());
            }
            if let Some(p) = &a.restore {
                value(&mut out, "--restore", path_arg(p));
            }
            if let Some(p) = &a.data_root {
                value(&mut out, "--data-root", path_arg(p));
            }
        }
        _ => return Vec::new(),
    }
    out.push("--interactive".into());
    out
}

/// True when this process must re-run itself elevated: only `install`/`uninstall`/`audit-policy`
/// with `--interactive` and without `--dry-run`, and only when not already elevated. Without
/// `--interactive` the plan's first step answers "not an administrator" instead.
pub fn needs_relaunch(cmd: &Command, elevated: bool) -> bool {
    if elevated {
        return false;
    }
    match cmd {
        Command::Install(a) => a.interactive && !a.dry_run,
        Command::Uninstall(a) => a.interactive && !a.dry_run,
        Command::AuditPolicy(a) => a.interactive && !a.dry_run,
        _ => false,
    }
}

/// The command with every path option made absolute by `absolute` (the caller's working folder
/// is lost across the elevation: the elevated process starts in System32).
pub fn with_absolute_paths(
    cmd: &Command,
    absolute: impl Fn(&Path) -> std::io::Result<PathBuf>,
) -> Result<Command, ArgError> {
    let abs = |p: &Option<PathBuf>| -> Result<Option<PathBuf>, ArgError> {
        p.as_deref()
            .map(|p| {
                absolute(p).map_err(|e| {
                    err(format!(
                        "{}을(를) 전체 경로로 바꿀 수 없습니다: {e}",
                        p.display()
                    ))
                })
            })
            .transpose()
    };
    Ok(match cmd {
        Command::Install(a) => Command::Install(InstallArgs {
            install_dir: abs(&a.install_dir)?,
            data_root: abs(&a.data_root)?,
            ..a.clone()
        }),
        Command::Uninstall(a) => Command::Uninstall(UninstallArgs {
            install_dir: abs(&a.install_dir)?,
            data_root: abs(&a.data_root)?,
            ..a.clone()
        }),
        Command::AuditPolicy(a) => Command::AuditPolicy(AuditArgs {
            restore: abs(&a.restore)?,
            data_root: abs(&a.data_root)?,
            ..a.clone()
        }),
        other => other.clone(),
    })
}

/// One argument for a Windows command line, quoted by the MSVCRT rules (Plan 5
/// `ConvertTo-CommandLineArg`): left as it is unless empty or holding whitespace or `"`; else in
/// quotes, with each `"` and the backslashes before it escaped, and trailing backslashes doubled.
pub fn quote_arg(a: &str) -> String {
    if !a.is_empty() && !a.chars().any(|c| c.is_whitespace() || c == '"') {
        return a.to_string();
    }
    let mut out = String::with_capacity(a.len() + 2);
    out.push('"');
    let mut slashes = 0usize;
    for c in a.chars() {
        if c == '\\' {
            slashes += 1;
            continue;
        }
        if c == '"' {
            out.extend(std::iter::repeat_n('\\', 2 * slashes + 1));
        } else {
            out.extend(std::iter::repeat_n('\\', slashes));
        }
        out.push(c);
        slashes = 0;
    }
    out.extend(std::iter::repeat_n('\\', 2 * slashes));
    out.push('"');
    out
}

/// The arguments quoted with [`quote_arg`] and joined by single spaces.
pub fn join_command_line(args: &[String]) -> String {
    args.iter()
        .map(|a| quote_arg(a))
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(v: &[&str]) -> Vec<String> {
        v.iter().map(|x| x.to_string()).collect()
    }

    #[test]
    fn no_arguments_is_auto_and_version_is_version() {
        assert_eq!(parse(&[]).unwrap(), Command::Auto);
        assert_eq!(parse(&s(&["--version"])).unwrap(), Command::Version);
    }

    #[test]
    fn install_options_are_parsed() {
        let c = parse(&s(&[
            "install",
            "--install-dir",
            r"D:\설치 폴더",
            "--data-root",
            r"D:\데이터",
            "--open-firewall",
            "--skip-audit-policy",
            "--local-port",
            "9700",
            "--external-port",
            "9701",
            "--dry-run",
        ]))
        .unwrap();
        assert_eq!(
            c,
            Command::Install(InstallArgs {
                install_dir: Some(r"D:\설치 폴더".into()),
                data_root: Some(r"D:\데이터".into()),
                open_firewall: true,
                skip_audit_policy: true,
                local_port: Some(9700),
                external_port: Some(9701),
                dry_run: true,
                interactive: false
            })
        );
        let a = parse(&s(&["agent", "--server", "http://127.0.0.1:8700"])).unwrap();
        assert_eq!(
            a,
            Command::Agent(AgentArgs {
                server: "http://127.0.0.1:8700".into(),
                dialog: Dialog::Webview,
                url_file: None,
                unreachable_exit_sec: 120.0
            })
        );
    }

    #[test]
    fn the_other_commands_are_parsed() {
        assert_eq!(
            parse(&s(&[
                "uninstall",
                "--interactive",
                "--remove-data",
                "--restore-audit-policy",
                "--data-root",
                r"E:\d",
                "--install-dir",
                r"E:\i",
                "--dry-run"
            ]))
            .unwrap(),
            Command::Uninstall(UninstallArgs {
                install_dir: Some(r"E:\i".into()),
                data_root: Some(r"E:\d".into()),
                remove_data: true,
                restore_audit_policy: true,
                dry_run: true,
                interactive: true
            })
        );
        assert_eq!(
            parse(&s(&["audit-policy", "--enable", "--data-root", r"E:\d"])).unwrap(),
            Command::AuditPolicy(AuditArgs {
                enable: true,
                restore: None,
                data_root: Some(r"E:\d".into()),
                dry_run: false,
                interactive: false
            })
        );
        assert_eq!(
            parse(&s(&[
                "agent",
                "--dialog",
                "print",
                "--url-file",
                r"C:\t\u.url",
                "--server",
                "http://127.0.0.1:9",
                "--unreachable-exit-sec",
                "2.5"
            ]))
            .unwrap(),
            Command::Agent(AgentArgs {
                server: "http://127.0.0.1:9".into(),
                dialog: Dialog::Print,
                url_file: Some(r"C:\t\u.url".into()),
                unreachable_exit_sec: 2.5
            })
        );
        assert_eq!(
            parse(&s(&["app"])).unwrap(),
            Command::App(AppArgs::default())
        );
        assert_eq!(
            parse(&s(&["app", "--background"])).unwrap(),
            Command::App(AppArgs {
                background: true,
                server_url: None
            })
        );
        assert_eq!(
            parse(&s(&["autostart", "on"])).unwrap(),
            Command::Autostart(true)
        );
        assert_eq!(
            parse(&s(&["autostart", "off"])).unwrap(),
            Command::Autostart(false)
        );
        assert_eq!(
            parse(&s(&["verify-payload", r"C:\빈 폴더"])).unwrap(),
            Command::VerifyPayload(r"C:\빈 폴더".into())
        );
        assert_eq!(
            parse(&s(&[
                "install",
                "--local-port",
                "1",
                "--external-port",
                "65535"
            ]))
            .unwrap(),
            Command::Install(InstallArgs {
                local_port: Some(1),
                external_port: Some(65535),
                ..InstallArgs::default()
            })
        );
    }

    #[test]
    fn malformed_arguments_are_errors() {
        let bad: &[&[&str]] = &[
            &["install", "--bogus"],
            &["install", "--local-port", "0"],
            &["install", "--local-port", "70000"],
            &["install", "--local-port", "x"],
            &["install", "--install-dir"],
            &["install", "--dry-run", "--dry-run"],
            &["agent"],
            &[
                "agent",
                "--server",
                "http://127.0.0.1:8700",
                "--dialog",
                "edge",
            ],
            &[
                "agent",
                "--server",
                "http://127.0.0.1:8700",
                "--dialog",
                "print",
            ],
            &["audit-policy"],
            &["audit-policy", "--enable", "--restore", "x.csv"],
            &["autostart", "maybe"],
            &["frobnicate"],
            &["verify-payload"],
        ];
        for b in bad {
            let e = parse(&s(b)).unwrap_err();
            assert!(!e.0.is_empty(), "{b:?}");
        }
        if !cfg!(feature = "dev") {
            assert!(parse(&s(&["app", "--server-url", "http://127.0.0.1:1"])).is_err());
        }
    }

    #[test]
    fn server_url_is_a_development_option_only() {
        let parsed = parse(&s(&["app", "--server-url", "http://127.0.0.1:1"]));
        if cfg!(feature = "dev") {
            assert_eq!(
                parsed.unwrap(),
                Command::App(AppArgs {
                    background: false,
                    server_url: Some("http://127.0.0.1:1".into())
                })
            );
        } else {
            assert!(parsed.unwrap_err().0.contains("--server-url"));
        }
    }

    #[test]
    fn more_malformed_arguments_are_errors_that_name_the_option() {
        let bad: &[(&[&str], &str)] = &[
            (&["--version", "extra"], "--version"),
            (&["--help"], "--help"),
            (&["install", "--local-port", "+9700"], "--local-port"),
            (&["install", "--local-port", "-1"], "--local-port"),
            (&["install", "--external-port", "65536"], "--external-port"),
            (
                &["install", "--external-port", "99999999999"],
                "--external-port",
            ),
            (&["install", "--local-port", ""], "--local-port"),
            (&["install", "--install-dir", ""], "--install-dir"),
            // A missing value must not swallow the next option: this would otherwise
            // install into a folder named "--dry-run" instead of doing a dry run.
            (
                &["install", "--install-dir", "--dry-run", "--interactive"],
                "--install-dir",
            ),
            (&["install", "--local-port=9700"], "--local-port=9700"),
            (&["install", "extra"], "extra"),
            (&["uninstall", "--open-firewall"], "--open-firewall"),
            (
                &["uninstall", "--remove-data", "--remove-data"],
                "--remove-data",
            ),
            (&["audit-policy", "--restore"], "--restore"),
            (&["audit-policy", "--data-root", r"C:\d"], "--enable"),
            (&["audit-policy", "--enable", "--enable"], "--enable"),
            (&["agent", "--server"], "--server"),
            (&["agent", "--dialog", "webview"], "--server"),
            (
                &[
                    "agent",
                    "--server",
                    "http://127.0.0.1:1",
                    "--server",
                    "http://127.0.0.1:2",
                ],
                "--server",
            ),
            (
                &[
                    "agent",
                    "--server",
                    "http://127.0.0.1:1",
                    "--dialog",
                    "edge",
                ],
                "--dialog",
            ),
            (
                &[
                    "agent",
                    "--server",
                    "http://127.0.0.1:1",
                    "--dialog",
                    "print",
                ],
                "--url-file",
            ),
            (
                &[
                    "agent",
                    "--server",
                    "http://127.0.0.1:1",
                    "--unreachable-exit-sec",
                    "x",
                ],
                "--unreachable-exit-sec",
            ),
            (
                &[
                    "agent",
                    "--server",
                    "http://127.0.0.1:1",
                    "--unreachable-exit-sec",
                    "0",
                ],
                "--unreachable-exit-sec",
            ),
            (
                &[
                    "agent",
                    "--server",
                    "http://127.0.0.1:1",
                    "--unreachable-exit-sec",
                    "-5",
                ],
                "--unreachable-exit-sec",
            ),
            (
                &[
                    "agent",
                    "--server",
                    "http://127.0.0.1:1",
                    "--unreachable-exit-sec",
                    "inf",
                ],
                "--unreachable-exit-sec",
            ),
            (
                &[
                    "agent",
                    "--server",
                    "http://127.0.0.1:1",
                    "--unreachable-exit-sec",
                    "NaN",
                ],
                "--unreachable-exit-sec",
            ),
            (&["app", "--background", "--background"], "--background"),
            (&["app", "--interactive"], "--interactive"),
            (&["autostart"], "autostart"),
            (&["autostart", "on", "off"], "autostart"),
            (&["verify-payload", "a", "b"], "verify-payload"),
            (&["verify-payload", "--dry-run"], "verify-payload"),
            (&["verify-payload", ""], "verify-payload"),
            (&["Install"], "Install"),
        ];
        for (args, named) in bad {
            let e = parse(&s(args)).unwrap_err();
            assert!(e.0.contains(named), "{args:?}: {:?}", e.0);
            assert!(!e.0.contains('\n'), "{args:?}: one sentence, one line");
        }
        assert_eq!(
            parse(&s(&[
                "agent",
                "--server",
                "http://127.0.0.1:8700",
                "--dialog",
                "edge"
            ]))
            .unwrap_err()
            .0,
            "--dialog는 webview 또는 print입니다"
        );
    }

    #[test]
    fn relaunch_args_carry_only_parsed_options_and_add_interactive() {
        let c = parse(&s(&[
            "install",
            "--local-port",
            "9700",
            "--install-dir",
            r"C:\Program Files\MCP Monitor",
            "--open-firewall",
        ]))
        .unwrap();
        assert_eq!(
            relaunch_args(&c),
            s(&[
                "install",
                "--install-dir",
                r"C:\Program Files\MCP Monitor",
                "--open-firewall",
                "--local-port",
                "9700",
                "--interactive"
            ])
        );
        let u = parse(&s(&["uninstall", "--remove-data", "--interactive"])).unwrap();
        assert_eq!(
            relaunch_args(&u),
            s(&["uninstall", "--remove-data", "--interactive"])
        );
        let r = parse(&s(&["audit-policy", "--restore", r"C:\백업\a.csv"])).unwrap();
        assert_eq!(
            relaunch_args(&r),
            s(&[
                "audit-policy",
                "--restore",
                r"C:\백업\a.csv",
                "--interactive"
            ])
        );
        assert!(
            relaunch_args(&parse(&s(&["agent", "--server", "http://127.0.0.1:8700"])).unwrap())
                .is_empty()
        );
    }

    #[test]
    fn relaunch_args_follow_the_grammar_order_for_every_option() {
        let i = parse(&s(&[
            "install",
            "--interactive",
            "--dry-run",
            "--external-port",
            "9701",
            "--local-port",
            "9700",
            "--skip-audit-policy",
            "--open-firewall",
            "--data-root",
            r"D:\d",
            "--install-dir",
            r"D:\i",
        ]))
        .unwrap();
        assert_eq!(
            relaunch_args(&i),
            s(&[
                "install",
                "--install-dir",
                r"D:\i",
                "--data-root",
                r"D:\d",
                "--open-firewall",
                "--skip-audit-policy",
                "--local-port",
                "9700",
                "--external-port",
                "9701",
                "--interactive"
            ])
        );
        let u = parse(&s(&[
            "uninstall",
            "--restore-audit-policy",
            "--remove-data",
            "--data-root",
            r"D:\d",
            "--install-dir",
            r"D:\i",
        ]))
        .unwrap();
        assert_eq!(
            relaunch_args(&u),
            s(&[
                "uninstall",
                "--install-dir",
                r"D:\i",
                "--data-root",
                r"D:\d",
                "--remove-data",
                "--restore-audit-policy",
                "--interactive"
            ])
        );
        let a = parse(&s(&["audit-policy", "--data-root", r"D:\d", "--enable"])).unwrap();
        assert_eq!(
            relaunch_args(&a),
            s(&[
                "audit-policy",
                "--enable",
                "--data-root",
                r"D:\d",
                "--interactive"
            ])
        );
        // Whatever the relaunch carries parses back to the same command (plus --interactive).
        for c in [&i, &u, &a] {
            let back = parse(&relaunch_args(c)).unwrap();
            assert!(needs_relaunch(&back, false), "{back:?}");
            assert_eq!(relaunch_args(&back), relaunch_args(c));
        }
        for c in [
            Command::Auto,
            Command::Version,
            Command::App(AppArgs::default()),
            Command::Autostart(true),
            Command::VerifyPayload(r"C:\x".into()),
        ] {
            assert!(relaunch_args(&c).is_empty(), "{c:?}");
        }
    }

    #[test]
    fn dry_run_is_never_elevated() {
        let dry = parse(&s(&["install", "--dry-run", "--interactive"])).unwrap();
        assert!(!needs_relaunch(&dry, false));
        assert!(
            !relaunch_args(&parse(&s(&["install", "--dry-run"])).unwrap())
                .contains(&"--dry-run".to_string())
        );
        let real = parse(&s(&["install", "--interactive"])).unwrap();
        assert!(needs_relaunch(&real, false) && !needs_relaunch(&real, true));
        assert!(!needs_relaunch(&parse(&s(&["install"])).unwrap(), false)); // the plan's require_admin answers
        assert!(
            !needs_relaunch(&Command::Auto, false) && !needs_relaunch(&Command::Version, false)
        );
    }

    #[test]
    fn only_interactive_installer_modes_are_ever_elevated() {
        for args in [
            &["uninstall", "--interactive"][..],
            &["audit-policy", "--enable", "--interactive"][..],
            &["audit-policy", "--restore", "a.csv", "--interactive"][..],
        ] {
            let c = parse(&s(args)).unwrap();
            assert!(
                needs_relaunch(&c, false) && !needs_relaunch(&c, true),
                "{args:?}"
            );
        }
        for args in [
            &["uninstall", "--interactive", "--dry-run"][..],
            &["audit-policy", "--enable", "--interactive", "--dry-run"][..],
            &["uninstall"][..],
            &["audit-policy", "--enable"][..],
            &["app"][..],
            &["app", "--background"][..],
            &["agent", "--server", "http://127.0.0.1:8700"][..],
            &["autostart", "on"][..],
            &["verify-payload", r"C:\x"][..],
        ] {
            let c = parse(&s(args)).unwrap();
            assert!(!needs_relaunch(&c, false), "{args:?}");
        }
    }

    #[test]
    fn relative_paths_become_absolute_before_a_relaunch() {
        let c = parse(&s(&[
            "install",
            "--install-dir",
            r"sub\i",
            "--data-root",
            r"D:\d",
            "--interactive",
        ]))
        .unwrap();
        let abs = with_absolute_paths(&c, |p| Ok(Path::new(r"C:\cwd").join(p))).unwrap();
        assert_eq!(
            relaunch_args(&abs),
            s(&[
                "install",
                "--install-dir",
                r"C:\cwd\sub\i",
                "--data-root",
                r"D:\d",
                "--interactive"
            ])
        );
        let real = with_absolute_paths(&c, |p| std::path::absolute(p)).unwrap();
        let Command::Install(a) = &real else {
            panic!("{real:?}")
        };
        let dir = a.install_dir.as_ref().unwrap();
        assert!(dir.is_absolute() && dir.ends_with(r"sub\i"), "{dir:?}");
        assert_eq!(a.data_root.as_deref(), Some(Path::new(r"D:\d")));
        let r = parse(&s(&["audit-policy", "--restore", "b.csv", "--interactive"])).unwrap();
        let Command::AuditPolicy(a) = with_absolute_paths(&r, |p| std::path::absolute(p)).unwrap()
        else {
            panic!()
        };
        assert!(a.restore.unwrap().is_absolute());
        let failing = |_: &Path| Err(std::io::Error::other("no"));
        assert!(
            with_absolute_paths(&c, failing)
                .unwrap_err()
                .0
                .contains("sub")
        );
        let agent = parse(&s(&["agent", "--server", "http://127.0.0.1:8700"])).unwrap();
        assert_eq!(with_absolute_paths(&agent, failing).unwrap(), agent);
    }

    #[test]
    fn quote_arg_follows_the_msvcrt_rules() {
        assert_eq!(quote_arg("plain"), "plain");
        assert_eq!(quote_arg(r"C:\a\b"), r"C:\a\b");
        assert_eq!(quote_arg(""), r#""""#);
        assert_eq!(quote_arg("a b"), r#""a b""#);
        assert_eq!(quote_arg("a\tb"), "\"a\tb\"");
        assert_eq!(quote_arg(r#"a"b"#), r#""a\"b""#);
        assert_eq!(quote_arg(r#"a\"b"#), r#""a\\\"b""#);
        assert_eq!(quote_arg(r"C:\dir with space\"), r#""C:\dir with space\\""#);
        assert_eq!(
            join_command_line(&s(&["install", "--install-dir", r"C:\Program Files\M"])),
            r#"install --install-dir "C:\Program Files\M""#
        );
    }

    #[test]
    fn quoting_survives_command_line_to_argv() {
        let cases = s(&[
            r#""C:\Program Files\MCP Monitor\bin\monitor\mcp-monitor-server.exe" service --root "C:\Data\x y" --local-port 8700"#,
            "name=MCP Monitor (8701)",
            "",
            "plain",
            r"a\\b\",
            r#"tail\"q"#,
            r"C:\dir with space\",
            r"/file:C:\관리 폴더\a.csv",
        ]);
        let line = format!("x.exe {}", join_command_line(&cases));
        assert_eq!(
            &crate::winutil::command_line_to_argv(&line)[1..],
            &cases[..]
        );
    }

    #[test]
    fn documented_options_are_exactly_what_the_parser_accepts() {
        let mut accepted: Vec<&str> = COMMANDS.to_vec();
        for (_, spec) in OPTION_SPECS {
            for (name, _) in *spec {
                if !accepted.contains(name) {
                    accepted.push(name);
                }
            }
        }
        accepted.sort_unstable();
        let mut documented = DOCUMENTED_OPTIONS.to_vec();
        documented.sort_unstable();
        assert_eq!(documented, accepted);
        assert!(!DOCUMENTED_OPTIONS.contains(&"--server-url"));
        for word in [
            "install",
            "uninstall",
            "audit-policy",
            "agent",
            "app",
            "autostart",
            "verify-payload",
            "--version",
        ] {
            assert!(DOCUMENTED_OPTIONS.contains(&word), "{word}");
        }
    }

    #[test]
    fn tests_are_not_elevated() {
        if crate::winutil::skip_when_elevated(
            "tests_are_not_elevated",
            "the runner's only user is an administrator",
        ) {
            return;
        }
        assert!(
            !crate::winutil::is_elevated(),
            "run the tests from a non-elevated shell"
        );
    }
}
