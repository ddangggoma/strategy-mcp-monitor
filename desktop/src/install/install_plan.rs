//! `install [--dry-run]`: the install and upgrade plan (Plan 5's PowerShell install script with
//! the same steps and arguments where the action is the same, Y17), built from the arguments,
//! what this PC says ([`Host`]) and the files of an earlier install. Nothing here changes
//! anything.

use crate::cli::{ArgError, InstallArgs};
use crate::install::acl::{
    ADMINISTRATORS, SYSTEM, ancestor_problem, data_root_problem, data_root_readable, read_security,
};
use crate::install::audit::{AUDIT_VALUE, PS_VALUE, audit_steps, backup_path};
use crate::install::host::{Host, SERVICE_NAME, UNINSTALL_KEY};
use crate::install::paths::{full_path, is_inside, same_path, unsafe_root_reason};
use crate::install::plan::{Plan, Step};
use serde_json::{Map, Value, json};
use std::path::{Path, PathBuf};

pub const DEFAULT_LOCAL_PORT: u16 = 8700;
pub const DEFAULT_EXTERNAL_PORT: u16 = 8701;

/// The service description: the same sentence as `DESCRIPTION` in `server/app/winsvc/__init__.py`.
pub fn service_description(local_port: u16, external_port: u16) -> String {
    format!("MCP 상태 감시와 RDP 접속·행동 감사 (127.0.0.1:{local_port} / 0.0.0.0:{external_port})")
}

/// An argument error that starts with the option it is about (`--data-root: …`).
pub(crate) fn argument(option: &str, why: &str) -> ArgError {
    ArgError(format!("{option}: {why}"))
}

/// A JSON file of an earlier install, or `None` when it is missing, unreadable (an admin-only
/// data root seen without admin rights) or not JSON (PowerShell's `Read-JsonFile`).
pub(crate) fn read_json(path: &Path) -> Option<Value> {
    let bytes = std::fs::read(path).ok()?;
    let text = String::from_utf8(bytes).ok()?;
    serde_json::from_str(text.trim_start_matches('\u{feff}')).ok()
}

/// The owners an existing data root or a folder above it may have: SYSTEM, Administrators and the
/// account that installs.
pub(crate) fn owners(h: &dyn Host) -> Vec<String> {
    vec![SYSTEM.to_string(), ADMINISTRATORS.to_string(), h.user_sid()]
}

pub(crate) fn env_folder(h: &dyn Host, option: &str, var: &str) -> Result<String, ArgError> {
    h.env()
        .get(var)
        .map(|v| format!(r"{v}\MCP Monitor"))
        .ok_or_else(|| argument(option, &format!("%{var}% 을(를) 알 수 없습니다")))
}

/// `%ProgramData%\MCP Monitor`.
pub(crate) fn default_data_root(h: &dyn Host) -> Result<String, ArgError> {
    env_folder(h, "--data-root", "ProgramData")
}

/// The data root checks of `install` and `audit-policy --enable` (C1, I3): not an unsafe
/// root; empty, missing or an earlier data root owned by [`owners`] with nothing others may change;
/// no folder above it others may swap. Without admin rights an admin-only data root cannot be
/// looked into: that is a note (`what` names what could not be read), not an error; the
/// `(secure-data-root)` step checks it again when it runs.
pub(crate) fn check_data_root(
    d: &Path,
    h: &dyn Host,
    what: &str,
) -> Result<Option<String>, ArgError> {
    let shown = d.display().to_string();
    if let Some(why) = unsafe_root_reason(&shown, h.env(), h.volumes()) {
        return Err(argument("--data-root", &why));
    }
    let owners = owners(h);
    let mut note = None;
    if !h.is_admin() && !data_root_readable(d) {
        note = Some(format!(
            "{shown} 은(는) 관리자만 읽을 수 있어 안을 확인하지 못했습니다(소유자·내용 검사, {what}). 관리자 권한으로 다시 실행하면 확인합니다."
        ));
    } else if let Some(why) = data_root_problem(d, &owners) {
        return Err(argument("--data-root", &why));
    }
    if let Some(why) = ancestor_problem(d, &owners, &read_security) {
        return Err(argument("--data-root", &why));
    }
    Ok(note)
}

/// The two registry values the audit steps set, as they are now (`null` when missing).
pub(crate) fn registry_record(h: &dyn Host) -> Map<String, Value> {
    [AUDIT_VALUE, PS_VALUE]
        .into_iter()
        .map(|k| {
            (
                k.to_string(),
                h.registry_dword(k).map_or(Value::Null, Value::from),
            )
        })
        .collect()
}

/// `a` is a newer dotted version than `b` (`1.10.0` > `1.9.0`). A version that is not all
/// numbers is never newer (it cannot block an install).
pub fn is_newer(a: &str, b: &str) -> bool {
    fn parse(v: &str) -> Option<Vec<u64>> {
        v.split('.')
            .map(|p| {
                (!p.is_empty() && p.bytes().all(|c| c.is_ascii_digit()))
                    .then(|| p.parse().ok())
                    .flatten()
            })
            .collect()
    }
    let (Some(mut a), Some(mut b)) = (parse(a), parse(b)) else {
        return false;
    };
    let n = a.len().max(b.len());
    a.resize(n, 0);
    b.resize(n, 0);
    a > b
}

/// What the service's binPath says about an earlier install (ruling F13): only when it runs one
/// of our programs (`<I>\bin\monitor\mcp-monitor-server.exe`, 1.0.0's
/// `<I>\bin\monitor\mcp-monitor.exe`, or `<I>\runtime\python.exe`).
#[derive(Debug, Default, PartialEq)]
pub struct ServiceFolders {
    pub install_dir: Option<PathBuf>,
    pub data_root: Option<PathBuf>,
    pub local_port: Option<u16>,
    pub external_port: Option<u16>,
}

pub fn service_folders(bin_path: &str) -> Option<ServiceFolders> {
    if bin_path.trim().is_empty() {
        return None;
    }
    let argv = crate::winutil::command_line_to_argv(bin_path);
    let exe = Path::new(argv.first()?);
    let name_is = |p: Option<&Path>, want: &str| {
        p.and_then(Path::file_name)
            .is_some_and(|n| n.to_string_lossy().eq_ignore_ascii_case(want))
    };
    let parent = exe.parent();
    let install_dir = if (name_is(Some(exe), "mcp-monitor-server.exe")
        || name_is(Some(exe), "mcp-monitor.exe"))
        && name_is(parent, "monitor")
        && name_is(parent.and_then(Path::parent), "bin")
    {
        parent.and_then(Path::parent).and_then(Path::parent)
    } else if name_is(Some(exe), "python.exe") && name_is(parent, "runtime") {
        parent.and_then(Path::parent)
    } else {
        None
    }?;
    let value = |name: &str| {
        argv.windows(2)
            .find(|w| w[0] == name)
            .map(|w| w[1].clone())
            .filter(|v| !v.starts_with("--"))
    };
    let port = |name: &str| {
        value(name)
            .and_then(|v| v.parse::<u16>().ok())
            .filter(|p| *p != 0)
    };
    Some(ServiceFolders {
        install_dir: Some(install_dir.to_path_buf()),
        data_root: value("--root").map(PathBuf::from),
        local_port: port("--local-port"),
        external_port: port("--external-port"),
    })
}

/// A port recorded in an earlier install's JSON (`None`: missing or not a port).
pub(crate) fn recorded_port(v: Option<&Value>, key: &str) -> Option<u16> {
    v?.get(key)?
        .as_u64()
        .and_then(|p| u16::try_from(p).ok())
        .filter(|p| *p != 0)
}

fn same_ports(port: u16) -> ArgError {
    argument(
        "--local-port",
        &format!("--local-port와 --external-port가 같습니다({port})."),
    )
}

/// The install folder checks: not an unsafe root (the service runs it as SYSTEM, and the upgrade
/// replaces it whole), not a file, empty or an earlier install (`bundle.json`), without server
/// data folders (they would go with `<I>.old`, F14), and no folder above it others may swap (Y15).
fn check_install_dir(i: &Path, h: &dyn Host) -> Result<(), ArgError> {
    let shown = i.display().to_string();
    let fail = |why: String| Err(argument("--install-dir", &why));
    if let Some(why) = unsafe_root_reason(&shown, h.env(), h.volumes()) {
        return fail(why);
    }
    if i.is_file() {
        return fail(format!("{shown} 이(가) 파일입니다."));
    }
    if i.is_dir() {
        let not_empty = match std::fs::read_dir(i) {
            Ok(mut entries) => entries.next().is_some(),
            Err(e) => return fail(format!("{shown} 을(를) 확인하지 못했습니다: {e}")),
        };
        if not_empty && !i.join("bundle.json").is_file() {
            return fail(format!(
                "{shown} 이(가) 비어 있지 않고 MCP Monitor 설치 폴더(bundle.json)도 아닙니다."
            ));
        }
        if let Some(folder) = ["logs", "data", "scripts"]
            .into_iter()
            .find(|f| i.join(f).exists())
        {
            return fail(format!(
                "{shown} 안에 {folder} 폴더가 있습니다. 업그레이드하면 이전 설치 폴더와 함께 지워지므로 옮기거나 지운 뒤 다시 실행하세요(데이터는 --data-root 폴더에 둡니다)."
            ));
        }
    }
    if let Some(why) = ancestor_problem(i, &owners(h), &read_security) {
        return fail(why);
    }
    Ok(())
}

fn lossy(p: &Path) -> String {
    p.to_string_lossy().into_owned()
}

/// Plan 5's install plan with the desktop steps (Y15–Y19). Folders (Y15, F13): `I` = `--install-dir`
/// → the Apps & features entry → the service's binPath → `%ProgramFiles%\MCP Monitor`; `D` =
/// `--data-root` → `<I>\install.json` → the service's binPath → `%ProgramData%\MCP Monitor`. Ports:
/// arguments → `install.json` → `install-state.json` → binPath → 8700/8701. The firewall rule stays
/// when an earlier install opened it.
pub fn build_install_plan(a: &InstallArgs, h: &dyn Host) -> Result<Plan, ArgError> {
    if let (Some(local), Some(external)) = (a.local_port, a.external_port)
        && local == external
    {
        return Err(same_ports(local));
    }
    let payload = h.payload();
    let service = h.service_exists();
    let from_service = service
        .then(|| h.service_bin_path())
        .flatten()
        .and_then(|b| service_folders(&b))
        .unwrap_or_default();
    let installed = h.installed();

    let i_raw = match (&a.install_dir, &installed, &from_service.install_dir) {
        (Some(p), _, _) => lossy(p),
        (None, Some(x), _) => lossy(&x.install_location),
        (None, None, Some(p)) => lossy(p),
        (None, None, None) => env_folder(h, "--install-dir", "ProgramFiles")?,
    };
    let i = full_path(&i_raw).map_err(|e| argument("--install-dir", &e))?;
    check_install_dir(&i, h)?;
    let inst = i.display().to_string();
    let (staging, old) = (format!("{inst}.staging"), format!("{inst}.old"));

    // 1.0.0 (PowerShell) installs have no Apps & features entry: their bundle.json tells.
    let bundle = read_json(&i.join("bundle.json"));
    let installed_version = installed.as_ref().map(|x| x.version.clone()).or_else(|| {
        bundle
            .as_ref()?
            .get("version")?
            .as_str()
            .map(str::to_string)
    });
    if let Some(v) = &installed_version
        && is_newer(v, &payload.version)
    {
        return Err(argument(
            "--install-dir",
            &format!(
                "설치된 버전 {v}이 이 실행 파일({})보다 새롭습니다. 낮은 버전으로는 설치할 수 없습니다(같은 버전은 복구 설치). 설치된 버전 이상의 mcp-monitor.exe로 실행하세요.",
                payload.version
            ),
        ));
    }

    let info = read_json(&i.join("install.json"));
    let d_raw = match (
        &a.data_root,
        info.as_ref().and_then(|v| v.get("data_root")?.as_str()),
        &from_service.data_root,
    ) {
        (Some(p), _, _) => lossy(p),
        (None, Some(p), _) => p.to_string(),
        (None, None, Some(p)) => lossy(p),
        (None, None, None) => default_data_root(h)?,
    };
    let d = full_path(&d_raw).map_err(|e| argument("--data-root", &e))?;
    for other in [inst.as_str(), staging.as_str(), old.as_str()] {
        let other = Path::new(other);
        if same_path(&d, other) || is_inside(&d, other) || is_inside(other, &d) {
            return Err(argument(
                "--data-root",
                &format!(
                    "{}는 {} 와(과) 겹치지 않는 폴더여야 합니다.",
                    d.display(),
                    other.display()
                ),
            ));
        }
    }
    let mut notes = Vec::new();
    if let Some(note) = check_data_root(&d, h, "이전 install-state.json")? {
        notes.push(note);
    }
    let data = d.display().to_string();

    // Read only after the data root passed its checks.
    let state = read_json(&d.join("data").join("install-state.json"));
    let audit_state = read_json(&d.join("data").join("audit-policy-state.json"));
    let local_port = a
        .local_port
        .or_else(|| recorded_port(info.as_ref(), "local_port"))
        .or_else(|| recorded_port(state.as_ref(), "local_port"))
        .or(from_service.local_port)
        .unwrap_or(DEFAULT_LOCAL_PORT);
    let external_port = a
        .external_port
        .or_else(|| recorded_port(info.as_ref(), "external_port"))
        .or_else(|| recorded_port(state.as_ref(), "external_port"))
        .or(from_service.external_port)
        .unwrap_or(DEFAULT_EXTERNAL_PORT);
    if local_port == external_port {
        return Err(same_ports(local_port));
    }
    let had_firewall = state.as_ref().and_then(|s| s.get("firewall")?.as_bool()) == Some(true);
    let firewall = a.open_firewall || had_firewall;
    let old_external = recorded_port(state.as_ref(), "external_port")
        .or_else(|| recorded_port(info.as_ref(), "external_port"));

    // The values before our first install (or `audit-policy --enable`): a reinstall keeps them
    // (it would otherwise record our own 1s).
    let mut registry_before = [&state, &audit_state]
        .into_iter()
        .find_map(|s| s.as_ref()?.get("registry_before")?.as_object().cloned())
        .unwrap_or_default();
    if !a.skip_audit_policy {
        for (k, v) in registry_record(h) {
            registry_before.entry(k).or_insert(v);
        }
    }
    let backup = backup_path(&data);
    let audit_backup = if !a.skip_audit_policy || Path::new(&backup).exists() {
        Value::from(backup)
    } else {
        state
            .as_ref()
            .and_then(|s| s.get("audit_backup").cloned())
            .unwrap_or(Value::Null)
    };

    let s = |v: &[&str]| v.iter().map(|x| x.to_string()).collect::<Vec<String>>();
    let mut steps = vec![
        Step::new("require_admin", "(admin)", vec![]),
        Step::new("check_os", "(check-os)", vec![inst.clone()]),
        Step::new(
            "stage_payload",
            "(stage)",
            vec![staging.clone(), inst.clone()],
        ),
        Step::new("stop_existing", "sc.exe", s(&["stop", SERVICE_NAME]))
            .ok(&[0, 1062])
            .when("service_exists"),
        Step::new("stop_apps", "(stop-apps)", vec![inst.clone()]),
        Step::new(
            "swap_install_dir",
            "(swap)",
            vec![staging, inst.clone(), old.clone()],
        ),
        Step::new("secure_data_root", "(secure-data-root)", vec![data.clone()]),
    ];
    if !a.skip_audit_policy {
        steps.extend(audit_steps(&data));
    }
    let bin_path = format!(
        r#""{inst}\bin\monitor\mcp-monitor-server.exe" service --root "{data}" --local-port {local_port} --external-port {external_port}"#
    );
    let mode = if service { "config" } else { "create" };
    steps.push(Step::new(
        "service_install",
        "sc.exe",
        s(&[
            mode,
            SERVICE_NAME,
            "binPath=",
            &bin_path,
            "start=",
            "delayed-auto",
            "DisplayName=",
            "MCP Monitor",
            "obj=",
            "LocalSystem",
        ]),
    ));
    steps.push(Step::new(
        "service_description",
        "sc.exe",
        s(&[
            "description",
            SERVICE_NAME,
            &service_description(local_port, external_port),
        ]),
    ));
    steps.push(Step::new(
        "service_failure",
        "sc.exe",
        s(&[
            "failure",
            SERVICE_NAME,
            "reset=",
            "86400",
            "actions=",
            "restart/5000/restart/10000/restart/60000",
        ]),
    ));
    steps.push(Step::new(
        "service_failureflag",
        "sc.exe",
        s(&["failureflag", SERVICE_NAME, "1"]),
    ));
    if let Some(old_port) = old_external.filter(|p| had_firewall && *p != external_port) {
        steps.push(
            Step::new(
                "firewall_delete_old",
                "netsh",
                s(&[
                    "advfirewall",
                    "firewall",
                    "delete",
                    "rule",
                    &format!("name=MCP Monitor ({old_port})"),
                ]),
            )
            .ok(&[0, 1]),
        );
    }
    if firewall {
        steps.push(
            Step::new(
                "firewall",
                "netsh",
                s(&[
                    "advfirewall",
                    "firewall",
                    "add",
                    "rule",
                    &format!("name=MCP Monitor ({external_port})"),
                    "dir=in",
                    "action=allow",
                    "protocol=TCP",
                    &format!("localport={external_port}"),
                    "profile=domain,private",
                ]),
            )
            .when("firewall_rule_missing"),
        );
    }
    let install_state = json!({
        "installed_at": null,
        "version": payload.version,
        "layout": payload.layout,
        "install_dir": inst,
        "data_root": data,
        "local_port": local_port,
        "external_port": external_port,
        "firewall": firewall,
        "skip_audit_policy": a.skip_audit_policy,
        "registry_before": registry_before,
        "audit_backup": audit_backup,
        "installer": "desktop",
    });
    steps.push(Step::new(
        "install_state",
        "(write-state)",
        vec![
            format!(r"{data}\data\install-state.json"),
            install_state.to_string(),
        ],
    ));
    let install_info = json!({
        "version": payload.version,
        "local_port": local_port,
        "external_port": external_port,
        "data_root": data,
    });
    steps.push(Step::new(
        "install_info",
        "(write-json)",
        vec![format!(r"{inst}\install.json"), install_info.to_string()],
    ));
    let exe = format!(r"{inst}\mcp-monitor.exe");
    steps.push(Step::new(
        "uninstall_entry",
        "(registry-set)",
        vec![
            UNINSTALL_KEY.to_string(),
            "DisplayName=REG_SZ:MCP Monitor".into(),
            format!("DisplayVersion=REG_SZ:{}", payload.version),
            "Publisher=REG_SZ:MCP Monitor".into(),
            format!("InstallLocation=REG_SZ:{inst}"),
            format!(r#"DisplayIcon=REG_SZ:"{exe}",0"#),
            format!(r#"UninstallString=REG_SZ:"{exe}" uninstall --interactive"#),
            format!(r#"QuietUninstallString=REG_SZ:"{exe}" uninstall"#),
            "NoModify=REG_DWORD:1".into(),
            "NoRepair=REG_DWORD:1".into(),
            format!("EstimatedSize=REG_DWORD:{}", payload.size_kb),
        ],
    ));
    let program_data = h
        .env()
        .get("ProgramData")
        .ok_or_else(|| argument("--data-root", "%ProgramData% 을(를) 알 수 없습니다"))?;
    steps.push(Step::new(
        "start_menu_shortcut",
        "(shortcut)",
        vec![
            format!(r"{program_data}\Microsoft\Windows\Start Menu\Programs\MCP Monitor.lnk"),
            exe,
            String::new(),
            "MCP Monitor".into(),
        ],
    ));
    steps.push(Step::new("service_start", "sc.exe", s(&["start", SERVICE_NAME])).ok(&[0, 1056]));
    steps.push(Step::new(
        "wait_ready",
        "(wait)",
        vec![
            format!("http://127.0.0.1:{local_port}/api/channel"),
            "30".into(),
        ],
    ));
    steps.push(Step::new("cleanup_old", "(remove-old)", vec![old]).when("old_exists"));

    Ok(Plan {
        script: "install".into(),
        version: Some(payload.version),
        layout: Some(payload.layout),
        install_dir: Some(inst),
        data_root: Some(data),
        service_mode: Some(if service { "update" } else { "create" }.into()),
        steps,
        notes,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::audit::{AUDIT_VALUE, PS_VALUE};
    use crate::install::host::{FakeHost, Installed};
    use crate::install::plan::{Plan, Step};
    use crate::install::testutil::*;
    use regex::Regex;
    use serde_json::{Value, json};
    use std::{fs, path::PathBuf};

    const DEFAULT_IDS: [&str; 25] = [
        "require_admin",
        "check_os",
        "stage_payload",
        "stop_existing",
        "stop_apps",
        "swap_install_dir",
        "secure_data_root",
        "audit_backup",
        "audit_policy_success",
        "audit_policy_failure",
        "registry_cmdline",
        "registry_scriptblock",
        "security_log_size",
        "powershell_log_size",
        "service_install",
        "service_description",
        "service_failure",
        "service_failureflag",
        "install_state",
        "install_info",
        "uninstall_entry",
        "start_menu_shortcut",
        "service_start",
        "wait_ready",
        "cleanup_old",
    ];

    fn args(s: &Scratch) -> InstallArgs {
        InstallArgs {
            install_dir: Some(s.path().join("inst")),
            data_root: Some(s.path().join("data")),
            ..Default::default()
        }
    }
    fn dirs(s: &Scratch) -> (String, String) {
        (
            s.path().join("inst").display().to_string(),
            s.path().join("data").display().to_string(),
        )
    }
    fn ids(p: &Plan) -> Vec<&str> {
        p.steps.iter().map(|x| x.id.as_str()).collect()
    }
    fn step<'a>(p: &'a Plan, id: &str) -> &'a Step {
        p.steps
            .iter()
            .find(|x| x.id == id)
            .unwrap_or_else(|| panic!("no step {id}"))
    }
    fn after<'a>(s: &'a Step, key: &str) -> &'a str {
        &s.args[s.args.iter().position(|a| a == key).unwrap() + 1]
    }
    fn state(p: &Plan) -> Value {
        serde_json::from_str(&step(p, "install_state").args[1]).unwrap()
    }

    #[test]
    fn install_plan_default() {
        let s = Scratch::new();
        let p = build_install_plan(&args(&s), &FakeHost::new()).unwrap();
        let (inst, data) = dirs(&s);
        assert_eq!(ids(&p), DEFAULT_IDS);
        assert_eq!(
            (
                p.script.as_str(),
                p.version.as_deref(),
                p.layout.as_deref(),
                p.service_mode.as_deref()
            ),
            (
                "install",
                Some("1.1.0"),
                Some("pyinstaller"),
                Some("create")
            )
        );
        assert_eq!(
            (p.install_dir.as_deref(), p.data_root.as_deref()),
            (Some(inst.as_str()), Some(data.as_str()))
        );
        let svc = step(&p, "service_install");
        assert_eq!(svc.args[..2], ["create", "mcp-monitor"]);
        assert_eq!(
            (
                after(svc, "start="),
                after(svc, "obj="),
                after(svc, "DisplayName=")
            ),
            ("delayed-auto", "LocalSystem", "MCP Monitor")
        );
        assert_eq!(
            after(svc, "binPath="),
            format!(
                r#""{inst}\bin\monitor\mcp-monitor-server.exe" service --root "{data}" --local-port 8700 --external-port 8701"#
            )
        );
        assert_eq!(
            step(&p, "service_failure").args,
            [
                "failure",
                "mcp-monitor",
                "reset=",
                "86400",
                "actions=",
                "restart/5000/restart/10000/restart/60000"
            ]
        );
        assert_eq!(
            step(&p, "service_failureflag").args,
            ["failureflag", "mcp-monitor", "1"]
        );
        let guid = Regex::new(r"\{0CCE92[0-9A-F]{2}-69AE-11D9-BED3-505054503030\}").unwrap();
        let subs = step(&p, "audit_policy_success")
            .args
            .iter()
            .find(|a| a.starts_with("/subcategory:"))
            .unwrap();
        assert_eq!(guid.find_iter(subs).count(), 5);
        assert!(
            p.steps
                .iter()
                .all(|x| x.cmd != "robocopy" && x.cmd != "icacls")
        );
        assert!(p.notes.is_empty());
    }

    #[test]
    fn install_plan_details() {
        let s = Scratch::new();
        let p = build_install_plan(&args(&s), &FakeHost::new()).unwrap();
        let (inst, data) = dirs(&s);
        let stop = step(&p, "stop_existing");
        assert_eq!(
            (
                stop.cmd.as_str(),
                stop.args.clone(),
                stop.ok.clone(),
                stop.when.as_deref()
            ),
            (
                "sc.exe",
                vec!["stop".to_string(), "mcp-monitor".into()],
                vec![0, 1062],
                Some("service_exists")
            )
        );
        assert_eq!(
            (
                step(&p, "stage_payload").cmd.as_str(),
                step(&p, "stage_payload").args.clone()
            ),
            ("(stage)", vec![format!("{inst}.staging"), inst.clone()])
        );
        assert_eq!(step(&p, "stop_apps").args, std::slice::from_ref(&inst));
        assert_eq!(
            step(&p, "swap_install_dir").args,
            [
                format!("{inst}.staging"),
                inst.clone(),
                format!("{inst}.old")
            ]
        );
        assert_eq!(
            (
                step(&p, "secure_data_root").cmd.as_str(),
                step(&p, "secure_data_root").args.clone()
            ),
            ("(secure-data-root)", vec![data.clone()])
        );
        let backup = step(&p, "audit_backup");
        assert_eq!(
            backup.args,
            [
                "/backup".to_string(),
                format!(r"/file:{data}\data\auditpol-backup.csv")
            ]
        );
        assert_eq!(backup.when.as_deref(), Some("no_backup_yet"));
        assert_eq!(
            step(&p, "audit_policy_failure").args,
            [
                "/set",
                "/subcategory:{0CCE9215-69AE-11D9-BED3-505054503030},{0CCE921C-69AE-11D9-BED3-505054503030}",
                "/failure:enable"
            ]
        );
        assert_eq!(
            step(&p, "registry_cmdline").args,
            [
                "add",
                r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit",
                "/v",
                "ProcessCreationIncludeCmdLine_Enabled",
                "/t",
                "REG_DWORD",
                "/d",
                "1",
                "/f"
            ]
        );
        assert_eq!(
            step(&p, "registry_scriptblock").args,
            [
                "add",
                r"HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging",
                "/v",
                "EnableScriptBlockLogging",
                "/t",
                "REG_DWORD",
                "/d",
                "1",
                "/f"
            ]
        );
        assert_eq!(
            step(&p, "security_log_size").args,
            ["sl", "Security", "/ms:268435456"]
        );
        assert_eq!(
            step(&p, "powershell_log_size").args,
            [
                "sl",
                "Microsoft-Windows-PowerShell/Operational",
                "/ms:67108864"
            ]
        );
        assert!(!ids(&p).contains(&"firewall") && !ids(&p).contains(&"firewall_delete_old"));
        assert_eq!(step(&p, "service_start").ok, [0, 1056]);
        assert_eq!(
            step(&p, "wait_ready").args,
            ["http://127.0.0.1:8700/api/channel", "30"]
        );
        let st = step(&p, "install_state");
        assert_eq!(
            (st.cmd.as_str(), st.args[0].clone()),
            ("(write-state)", format!(r"{data}\data\install-state.json"))
        );
        let mut v = state(&p);
        assert!(v["installed_at"].is_null());
        let keys: Vec<String> = v["registry_before"]
            .as_object()
            .unwrap()
            .keys()
            .cloned()
            .collect();
        assert_eq!(keys, [AUDIT_VALUE, PS_VALUE]);
        let o = v.as_object_mut().unwrap();
        o.remove("registry_before");
        o.remove("installed_at");
        assert_eq!(
            v,
            json!({"version": "1.1.0", "layout": "pyinstaller", "install_dir": &inst, "data_root": &data,
                              "local_port": 8700, "external_port": 8701, "firewall": false, "skip_audit_policy": false,
                              "audit_backup": format!(r"{data}\data\auditpol-backup.csv"), "installer": "desktop"})
        );
        let info = step(&p, "install_info");
        assert_eq!(
            (info.cmd.as_str(), info.args[0].clone()),
            ("(write-json)", format!(r"{inst}\install.json"))
        );
        assert_eq!(
            serde_json::from_str::<Value>(&info.args[1]).unwrap(),
            json!({"version": "1.1.0", "local_port": 8700, "external_port": 8701, "data_root": &data})
        );
        let un = step(&p, "uninstall_entry");
        assert_eq!(
            (un.cmd.as_str(), un.args[0].as_str()),
            ("(registry-set)", UNINSTALL_KEY)
        );
        for want in [
            "DisplayName=REG_SZ:MCP Monitor".to_string(),
            "DisplayVersion=REG_SZ:1.1.0".into(),
            "Publisher=REG_SZ:MCP Monitor".into(),
            format!("InstallLocation=REG_SZ:{inst}"),
            format!(r#"DisplayIcon=REG_SZ:"{inst}\mcp-monitor.exe",0"#),
            format!(r#"UninstallString=REG_SZ:"{inst}\mcp-monitor.exe" uninstall --interactive"#),
            format!(r#"QuietUninstallString=REG_SZ:"{inst}\mcp-monitor.exe" uninstall"#),
            "NoModify=REG_DWORD:1".into(),
            "NoRepair=REG_DWORD:1".into(),
            "EstimatedSize=REG_DWORD:60000".into(),
        ] {
            assert!(un.args.contains(&want), "{want}");
        }
        let programs = format!(
            r"{}\Microsoft\Windows\Start Menu\Programs",
            std::env::var("ProgramData").unwrap()
        );
        assert_eq!(
            step(&p, "start_menu_shortcut").args,
            [
                format!(r"{programs}\MCP Monitor.lnk"),
                format!(r"{inst}\mcp-monitor.exe"),
                String::new(),
                "MCP Monitor".into()
            ]
        );
        let old = step(&p, "cleanup_old");
        assert_eq!(
            (old.cmd.as_str(), old.args.clone(), old.when.as_deref()),
            (
                "(remove-old)",
                vec![format!("{inst}.old")],
                Some("old_exists")
            )
        );
    }

    #[test]
    fn description_matches_the_service_host() {
        let src = fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../server/app/winsvc/__init__.py"
        ))
        .unwrap();
        let line = src
            .lines()
            .find(|l| l.starts_with("DESCRIPTION = "))
            .unwrap();
        let text = line.trim_start_matches("DESCRIPTION = ").trim_matches('"');
        assert_eq!(service_description(8700, 8701), text);
        assert_eq!(
            service_description(9700, 9701),
            text.replace("8700", "9700").replace("8701", "9701")
        );
    }

    #[test]
    fn install_plan_open_firewall_and_skip_audit() {
        let s = Scratch::new();
        let mut a = args(&s);
        a.open_firewall = true;
        a.skip_audit_policy = true;
        a.external_port = Some(9701);
        let p = build_install_plan(&a, &FakeHost::new()).unwrap();
        let ids = ids(&p);
        for gone in crate::install::audit::AUDIT_STEPS {
            assert!(!ids.contains(&gone), "{gone}");
        }
        let fw = step(&p, "firewall");
        assert_eq!(
            fw.args,
            [
                "advfirewall",
                "firewall",
                "add",
                "rule",
                "name=MCP Monitor (9701)",
                "dir=in",
                "action=allow",
                "protocol=TCP",
                "localport=9701",
                "profile=domain,private"
            ]
        );
        assert_eq!(fw.when.as_deref(), Some("firewall_rule_missing"));
        assert_eq!(
            ids.iter().position(|i| *i == "firewall"),
            ids.iter()
                .position(|i| *i == "service_failureflag")
                .map(|i| i + 1)
        );
        let v = state(&p);
        assert_eq!(
            (
                v["firewall"].as_bool(),
                v["external_port"].as_u64(),
                v["skip_audit_policy"].as_bool()
            ),
            (Some(true), Some(9701), Some(true))
        );
        assert_eq!(v["registry_before"], json!({}));
        assert!(v["audit_backup"].is_null());
    }

    #[test]
    fn install_plan_ports_and_korean_paths() {
        let s = Scratch::new();
        let a = InstallArgs {
            install_dir: Some(s.path().join("설치 폴더")),
            data_root: Some(s.path().join("데이터")),
            local_port: Some(9700),
            external_port: Some(9701),
            ..Default::default()
        };
        let p = build_install_plan(&a, &FakeHost::new()).unwrap();
        let (inst, data) = (
            s.path().join("설치 폴더").display().to_string(),
            s.path().join("데이터").display().to_string(),
        );
        assert_eq!(
            after(step(&p, "service_install"), "binPath="),
            format!(
                r#""{inst}\bin\monitor\mcp-monitor-server.exe" service --root "{data}" --local-port 9700 --external-port 9701"#
            )
        );
        assert_eq!(
            step(&p, "service_description").args[2],
            service_description(9700, 9701)
        );
        assert_eq!(
            step(&p, "wait_ready").args[0],
            "http://127.0.0.1:9700/api/channel"
        );
    }

    #[test]
    fn upgrade_plan_stages_before_stopping_and_cleans_up_after_ready() {
        let s = Scratch::new();
        fs::create_dir_all(s.path().join("inst")).unwrap();
        fs::write(
            s.path().join("inst/bundle.json"),
            r#"{"layout":"pyinstaller","version":"1.0.9","agent":"desktop"}"#,
        )
        .unwrap();
        let mut h = FakeHost::new();
        h.service = true;
        h.installed = Some(Installed {
            version: "1.0.9".into(),
            install_location: s.path().join("inst"),
        });
        let p = build_install_plan(&args(&s), &h).unwrap();
        assert_eq!(p.service_mode.as_deref(), Some("update"));
        assert_eq!(step(&p, "service_install").args[0], "config");
        let all = ids(&p);
        let at = |id: &str| all.iter().position(|x| *x == id).unwrap();
        assert!(
            at("stage_payload") < at("stop_existing")
                && at("stop_existing") < at("stop_apps")
                && at("stop_apps") < at("swap_install_dir")
        );
        assert!(
            at("swap_install_dir") < at("service_install")
                && at("service_start") < at("wait_ready")
                && at("wait_ready") < at("cleanup_old")
        );
    }

    #[test]
    fn downgrade_is_refused() {
        let s = Scratch::new();
        let mut h = FakeHost::new();
        h.service = true;
        h.installed = Some(Installed {
            version: "1.2.0".into(),
            install_location: s.path().join("inst"),
        });
        let e = build_install_plan(&args(&s), &h).unwrap_err();
        assert!(e.0.contains("1.2.0") && e.0.contains("1.1.0"), "{}", e.0);
        h.installed = Some(Installed {
            version: "1.1.0".into(),
            install_location: s.path().join("inst"),
        });
        assert!(build_install_plan(&args(&s), &h).is_ok()); // the same version: a repair
    }

    fn earlier_install(s: &Scratch, state: Value) {
        let (_, data) = dirs(s);
        fs::create_dir_all(s.path().join("inst")).unwrap();
        fs::write(s.path().join("inst/bundle.json"), "{}").unwrap();
        fs::write(s.path().join("inst/install.json"), json!({"version": "1.1.0", "local_port": 9700, "external_port": 9701, "data_root": data}).to_string()).unwrap();
        fs::create_dir_all(s.path().join("data/data")).unwrap();
        fs::write(s.path().join("data/data/mcp-monitor-data-root.json"), "{}").unwrap();
        fs::write(
            s.path().join("data/data/install-state.json"),
            state.to_string(),
        )
        .unwrap();
    }

    #[test]
    fn reinstall_reuses_previous_ports_and_firewall() {
        let s = Scratch::new();
        earlier_install(
            &s,
            json!({"version": "1.1.0", "local_port": 9700, "external_port": 9701, "firewall": true, "registry_before": {}, "audit_backup": null}),
        );
        let a = InstallArgs {
            install_dir: Some(s.path().join("inst")),
            ..Default::default()
        };
        let p = build_install_plan(&a, &FakeHost::new()).unwrap();
        assert_eq!(p.data_root.as_deref(), Some(dirs(&s).1.as_str()));
        assert!(
            after(step(&p, "service_install"), "binPath=")
                .ends_with("--local-port 9700 --external-port 9701")
        );
        assert_eq!(step(&p, "firewall").args[4], "name=MCP Monitor (9701)");
        assert!(!ids(&p).contains(&"firewall_delete_old"));
        let b = InstallArgs {
            local_port: Some(9800),
            ..a
        };
        assert!(
            after(
                step(
                    &build_install_plan(&b, &FakeHost::new()).unwrap(),
                    "service_install"
                ),
                "binPath="
            )
            .ends_with("--local-port 9800 --external-port 9701")
        );
    }

    #[test]
    fn reinstall_with_another_external_port_removes_the_old_rule() {
        let s = Scratch::new();
        earlier_install(
            &s,
            json!({"version": "1.1.0", "local_port": 9700, "external_port": 9701, "firewall": true, "registry_before": {}, "audit_backup": null}),
        );
        let a = InstallArgs {
            install_dir: Some(s.path().join("inst")),
            external_port: Some(9801),
            ..Default::default()
        };
        let p = build_install_plan(&a, &FakeHost::new()).unwrap();
        let del = step(&p, "firewall_delete_old");
        assert_eq!(
            (del.cmd.as_str(), del.args.clone(), del.ok.clone()),
            (
                "netsh",
                [
                    "advfirewall",
                    "firewall",
                    "delete",
                    "rule",
                    "name=MCP Monitor (9701)"
                ]
                .map(String::from)
                .to_vec(),
                vec![0, 1]
            )
        );
        let all = ids(&p);
        assert_eq!(
            all.iter()
                .position(|x| *x == "firewall_delete_old")
                .unwrap()
                + 1,
            all.iter().position(|x| *x == "firewall").unwrap()
        );
        assert_eq!(step(&p, "firewall").args[4], "name=MCP Monitor (9801)");
    }

    #[test]
    fn reinstall_keeps_the_first_registry_values_and_backup() {
        let s = Scratch::new();
        let data = s.path().join("data");
        fs::create_dir_all(data.join("data")).unwrap();
        fs::write(data.join("data/auditpol-backup.csv"), "x").unwrap();
        fs::write(data.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        fs::write(data.join("data/install-state.json"), json!({"registry_before": {AUDIT_VALUE: null, PS_VALUE: 0},
            "audit_backup": data.join("data/auditpol-backup.csv"), "version": "1.0.0", "external_port": 8701}).to_string()).unwrap();
        let mut h = FakeHost::new();
        h.dwords.insert(AUDIT_VALUE.into(), 1); // our own values by now
        h.dwords.insert(PS_VALUE.into(), 1);
        let p = build_install_plan(&args(&s), &h).unwrap();
        assert_eq!(
            state(&p)["registry_before"],
            json!({AUDIT_VALUE: null, PS_VALUE: 0})
        );
        assert_eq!(
            step(&p, "audit_backup").when.as_deref(),
            Some("no_backup_yet")
        );
    }

    #[test]
    fn upgrade_from_a_powershell_install_keeps_its_state() {
        let s = Scratch::new();
        let (inst, data) = dirs(&s);
        fs::create_dir_all(s.path().join("inst/bin/agent")).unwrap();
        fs::write(s.path().join("inst/bundle.json"), r#"{"layout":"pyinstaller","version":"1.0.0","python":"3.15.2","built_at":"x","commit":"y"}"#).unwrap();
        fs::create_dir_all(s.path().join("data/data")).unwrap();
        fs::write(
            s.path().join("data/data/mcp-monitor-data-root.json"),
            r#"{"product":"mcp-monitor","created_by":"install"}"#,
        )
        .unwrap();
        fs::write(s.path().join("data/data/install-state.json"), json!({"installed_at": "2026-11-07T10:00:00+09:00", "version": "1.0.0",
            "layout": "pyinstaller", "install_dir": &inst, "data_root": &data, "local_port": 8800, "external_port": 8801, "firewall": false,
            "registry_before": {AUDIT_VALUE: null, PS_VALUE: null}, "audit_backup": format!(r"{data}\data\auditpol-backup.csv")}).to_string()).unwrap();
        let mut h = FakeHost::new();
        h.service = true; // 1.0.0 had no Apps & features entry
        let p = build_install_plan(&args(&s), &h).unwrap();
        assert_eq!(p.service_mode.as_deref(), Some("update"));
        assert!(
            after(step(&p, "service_install"), "binPath=")
                .ends_with("--local-port 8800 --external-port 8801")
        );
        let v = state(&p);
        assert_eq!(
            v["registry_before"],
            json!({AUDIT_VALUE: null, PS_VALUE: null})
        );
        assert_eq!(v["installer"], "desktop");
    }

    #[test]
    fn install_argument_errors() {
        let cases = [
            "same_ports",
            "foreign_install_dir",
            "install_dir_is_a_file",
            "data_root_inside_install",
            "data_root_contains_install",
            "data_root_is_the_staging_dir",
            "drive_root_install_dir",
            "install_dir_below_a_writable_folder",
            "foreign_data_root",
        ];
        for case in cases {
            let s = Scratch::new();
            let mut a = args(&s);
            let inst = s.path().join("inst");
            match case {
                "same_ports" => {
                    a.local_port = Some(8800);
                    a.external_port = Some(8800);
                }
                "foreign_install_dir" => {
                    fs::create_dir(&inst).unwrap();
                    fs::write(inst.join("keep.txt"), "x").unwrap();
                }
                "install_dir_is_a_file" => fs::write(&inst, "x").unwrap(),
                "data_root_inside_install" => a.data_root = Some(inst.join("var")),
                "data_root_contains_install" => a.data_root = Some(s.path().to_path_buf()),
                "data_root_is_the_staging_dir" => a.data_root = Some(s.path().join("inst.staging")),
                "drive_root_install_dir" => {
                    a.install_dir = Some(PathBuf::from(format!(
                        "{}\\",
                        std::env::var("SystemDrive").unwrap()
                    )))
                }
                "install_dir_below_a_writable_folder" => {
                    let w = s.path().join("w");
                    fs::create_dir(&w).unwrap();
                    grant(&w, "(OI)(CI)M");
                    a.install_dir = Some(w.join("MCP Monitor"));
                }
                _ => {
                    let d = s.path().join("data");
                    fs::create_dir_all(d.join("scripts")).unwrap();
                    fs::write(d.join("scripts/a.ps1"), "x").unwrap();
                }
            }
            let e = build_install_plan(&a, &FakeHost::new()).unwrap_err();
            let want = if case.contains("data_root") {
                "--data-root"
            } else if case == "same_ports" {
                "--local-port"
            } else {
                "--install-dir"
            };
            assert!(e.0.starts_with(want), "{case}: {}", e.0);
        }
    }

    #[test]
    fn install_accepts_an_earlier_install_dir() {
        let s = Scratch::new();
        let inst = s.path().join("inst");
        fs::create_dir(&inst).unwrap();
        fs::write(inst.join("bundle.json"), "{}").unwrap();
        fs::write(inst.join("old.txt"), "x").unwrap();
        assert!(
            !build_install_plan(&args(&s), &FakeHost::new())
                .unwrap()
                .steps
                .is_empty()
        );
    }

    #[test]
    fn dry_run_without_admin_plans_over_an_installed_data_root() {
        if crate::winutil::skip_when_elevated(
            "dry_run_without_admin_plans_over_an_installed_data_root",
            "an administrator can read the locked data root, so there is no note",
        ) {
            return;
        }
        let s = Scratch::new();
        let root = s.path().join("data");
        fs::create_dir_all(root.join("data")).unwrap();
        fs::write(root.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        icacls(
            &root,
            &[
                "/inheritance:r",
                "/grant:r",
                "*S-1-5-18:(OI)(CI)F",
                "*S-1-5-32-544:(OI)(CI)F",
            ],
        );
        let mut a = args(&s);
        a.dry_run = true;
        let p = build_install_plan(&a, &FakeHost::new());
        icacls(&root, &["/reset", "/T", "/C", "/Q"]);
        let p = p.unwrap();
        assert_eq!(p.notes.len(), 1);
        assert!(
            p.notes[0].contains("관리자 권한으로 다시 실행하면 확인합니다"),
            "{}",
            p.notes[0]
        );
        assert_eq!(
            step(&p, "secure_data_root").args,
            [root.display().to_string()]
        );
    }

    // --- additions beyond the plan text -----------------------------------------------------------

    /// The other path forms of `test_install_refuses_unsafe_data_root_paths` and
    /// `test_install_refuses_device_unc_and_linked_paths` (F17), every overlap in the other case
    /// (F04), and an install folder holding server data folders (F14).
    #[test]
    fn install_argument_errors_cover_the_powershell_path_forms_in_any_case() {
        let env = |k: &str| std::env::var(k).unwrap();
        for case in [
            "same_as_install_other_case",
            "inside_install_other_case",
            "old_dir_other_case",
            "contains_install_other_case",
            "drive_root_lower_case",
            "other_drive_root",
            "program_data",
            "users",
            "inside_windows",
            "device",
            "dot_device",
            "admin_share",
            "link_in_path",
        ] {
            for option in ["--install-dir", "--data-root"] {
                let s = Scratch::new();
                let inst = s.path().join("inst");
                let unc = |p: &Path| {
                    let t = p.display().to_string();
                    format!(r"\\localhost\{}$\{}", &t[..1], &t[3..])
                };
                let bad: Option<String> = match case {
                    "same_as_install_other_case" => {
                        (option == "--data-root").then(|| swap_case(&inst))
                    }
                    "inside_install_other_case" => {
                        (option == "--data-root").then(|| format!(r"{}\var", swap_case(&inst)))
                    }
                    "old_dir_other_case" => {
                        (option == "--data-root").then(|| swap_case(&s.path().join("inst.old")))
                    }
                    "contains_install_other_case" => {
                        (option == "--data-root").then(|| swap_case(s.path()))
                    }
                    "drive_root_lower_case" => {
                        Some(format!("{}\\", env("SystemDrive").to_lowercase()))
                    }
                    "other_drive_root" => Some(r"Q:\".into()),
                    "program_data" => Some(env("ProgramData")),
                    "users" => Some(
                        Path::new(&env("PUBLIC"))
                            .parent()
                            .unwrap()
                            .display()
                            .to_string(),
                    ),
                    "inside_windows" => Some(format!(r"{}\Temp\mcp", env("SystemRoot"))),
                    "device" => Some(format!(r"\\?\{}", s.path().join("x").display())),
                    "dot_device" => Some(format!(r"\\.\{}", s.path().join("x").display())),
                    "admin_share" => Some(unc(&s.path().join("x"))),
                    _ => {
                        junction(&s.path().join("link"), &s.path().join("real"));
                        Some(s.path().join("link").join("x").display().to_string())
                    }
                };
                let Some(bad) = bad else { continue };
                let mut a = args(&s);
                if option == "--install-dir" {
                    a.install_dir = Some(bad.clone().into())
                } else {
                    a.data_root = Some(bad.clone().into())
                }
                let mut h = FakeHost::new();
                h.letters.retain(|l| *l != 'Q');
                let e = build_install_plan(&a, &h).unwrap_err();
                assert!(e.0.starts_with(option), "{case} {option} {bad}: {}", e.0);
            }
        }
        for folder in ["logs", "data", "scripts"] {
            let s = Scratch::new();
            fs::create_dir_all(s.path().join("inst").join(folder)).unwrap();
            fs::write(s.path().join("inst/bundle.json"), "{}").unwrap();
            let e = build_install_plan(&args(&s), &FakeHost::new()).unwrap_err();
            assert!(
                e.0.starts_with("--install-dir") && e.0.contains(folder),
                "{folder}: {}",
                e.0
            );
        }
    }

    #[test]
    fn ports_given_by_the_state_must_differ_too() {
        let s = Scratch::new();
        earlier_install(&s, json!({"external_port": 9701, "firewall": false}));
        let a = InstallArgs {
            install_dir: Some(s.path().join("inst")),
            local_port: Some(9701),
            ..Default::default()
        };
        let e = build_install_plan(&a, &FakeHost::new()).unwrap_err();
        assert!(
            e.0.starts_with("--local-port") && e.0.contains("9701"),
            "{}",
            e.0
        );
    }

    /// F13 (a): a 1.0.0 install made with -InstallDir/-DataRoot has no Apps & features entry and no
    /// install.json: its folders and ports come from the service's binPath, not the defaults.
    #[test]
    fn folders_and_ports_come_from_the_service_of_an_earlier_install() {
        let s = Scratch::new();
        let (inst, data) = dirs(&s);
        fs::create_dir_all(s.path().join("inst")).unwrap();
        fs::write(
            s.path().join("inst/bundle.json"),
            r#"{"layout":"pyinstaller","version":"1.0.0"}"#,
        )
        .unwrap();
        let mut h = FakeHost::new();
        h.service = true;
        h.bin_path = Some(format!(
            r#""{inst}\bin\monitor\mcp-monitor.exe" service --root "{data}" --local-port 8800 --external-port 8801"#
        ));
        let p = build_install_plan(&InstallArgs::default(), &h).unwrap();
        assert_eq!(
            (p.install_dir.as_deref(), p.data_root.as_deref()),
            (Some(inst.as_str()), Some(data.as_str()))
        );
        assert!(
            after(step(&p, "service_install"), "binPath=")
                .ends_with("--local-port 8800 --external-port 8801")
        );
        // Arguments still win; a stopped-and-gone service (no binPath) means the defaults.
        let a = InstallArgs {
            local_port: Some(9900),
            ..Default::default()
        };
        assert!(
            after(
                step(&build_install_plan(&a, &h).unwrap(), "service_install"),
                "binPath="
            )
            .ends_with("--local-port 9900 --external-port 8801")
        );
    }

    #[test]
    fn service_folders_are_read_only_from_our_own_programs() {
        let f = service_folders(r#""D:\M M\bin\monitor\mcp-monitor-server.exe" service --root "E:\d d" --local-port 9700 --external-port 9701"#).unwrap();
        assert_eq!(
            (
                f.install_dir.unwrap(),
                f.data_root.unwrap(),
                f.local_port,
                f.external_port
            ),
            (
                PathBuf::from(r"D:\M M"),
                PathBuf::from(r"E:\d d"),
                Some(9700),
                Some(9701)
            )
        );
        let r = service_folders(r#""C:\Program Files\MCP Monitor\runtime\python.exe" -m app service --root "C:\ProgramData\MCP Monitor" --local-port 8700 --external-port 8701"#).unwrap();
        assert_eq!(
            r.install_dir.unwrap(),
            PathBuf::from(r"C:\Program Files\MCP Monitor")
        );
        for foreign in [
            r#""C:\evil\x.exe" service --root "C:\x" --local-port 1"#,
            r#""C:\a\monitor\mcp-monitor.exe" service --root "C:\x""#,
            "",
        ] {
            assert_eq!(service_folders(foreign), None, "{foreign}");
        }
        let odd = service_folders(
            r#""C:\M\bin\monitor\mcp-monitor.exe" service --local-port 0 --external-port x --root"#,
        )
        .unwrap();
        assert_eq!(
            (
                odd.install_dir.unwrap(),
                odd.data_root,
                odd.local_port,
                odd.external_port
            ),
            (PathBuf::from(r"C:\M"), None, None, None)
        );
    }

    #[test]
    fn versions_compare_by_number() {
        assert!(
            is_newer("1.2.0", "1.1.0")
                && is_newer("1.10.0", "1.9.0")
                && is_newer("2", "1.9.9")
                && is_newer("1.1.0.1", "1.1.0")
        );
        assert!(
            !is_newer("1.1.0", "1.1.0")
                && !is_newer("1.0.9", "1.1.0")
                && !is_newer("x", "1.1.0")
                && !is_newer("", "1.1.0")
        );
    }
}
