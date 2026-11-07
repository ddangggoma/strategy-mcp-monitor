//! `audit-policy --enable | --restore <file>` (Plan 5's PowerShell audit-policy script) and the
//! audit steps `install` shares with it: the same subcategory GUIDs, registry values and log
//! sizes.

use crate::cli::{ArgError, AuditArgs};
use crate::install::host::Host;
use crate::install::install_plan::{
    argument, check_data_root, default_data_root, read_json, registry_record,
};
use crate::install::paths::full_path;
use crate::install::plan::{Plan, Step, StepError};
use serde_json::{Value, json};
use std::path::Path;

pub const AUDIT_KEY: &str = r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit";
pub const PS_LOG_KEY: &str =
    r"HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging";
pub const AUDIT_VALUE: &str = r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit\ProcessCreationIncludeCmdLine_Enabled";
pub const PS_VALUE: &str = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging\EnableScriptBlockLogging";

/// Process Creation, Logon, Logoff, Other Logon/Logoff Events, Audit Policy Change (by GUID, so
/// Korean Windows reads them the same, W30).
pub const SUCCESS_GUIDS: [&str; 5] = [
    "{0CCE922B-69AE-11D9-BED3-505054503030}",
    "{0CCE9215-69AE-11D9-BED3-505054503030}",
    "{0CCE9216-69AE-11D9-BED3-505054503030}",
    "{0CCE921C-69AE-11D9-BED3-505054503030}",
    "{0CCE922F-69AE-11D9-BED3-505054503030}",
];
/// Logon, Other Logon/Logoff Events.
pub const FAILURE_GUIDS: [&str; 2] = [
    "{0CCE9215-69AE-11D9-BED3-505054503030}",
    "{0CCE921C-69AE-11D9-BED3-505054503030}",
];

pub const AUDIT_STEPS: [&str; 7] = [
    "audit_backup",
    "audit_policy_success",
    "audit_policy_failure",
    "registry_cmdline",
    "registry_scriptblock",
    "security_log_size",
    "powershell_log_size",
];

fn strings(v: &[&str]) -> Vec<String> {
    v.iter().map(|s| s.to_string()).collect()
}

/// `<D>\data\auditpol-backup.csv`: the policy before our first change (made once).
pub fn backup_path(data_root: &str) -> String {
    format!(r"{data_root}\data\auditpol-backup.csv")
}

/// The audit steps of `install` and `audit-policy --enable`, in [`AUDIT_STEPS`] order.
pub fn audit_steps(data_root: &str) -> Vec<Step> {
    let reg_add = |key: &str, name: &str| {
        strings(&["add", key, "/v", name, "/t", "REG_DWORD", "/d", "1", "/f"])
    };
    vec![
        Step::new(
            "audit_backup",
            "auditpol",
            vec![
                "/backup".into(),
                format!("/file:{}", backup_path(data_root)),
            ],
        )
        .when("no_backup_yet"),
        Step::new(
            "audit_policy_success",
            "auditpol",
            vec![
                "/set".into(),
                format!("/subcategory:{}", SUCCESS_GUIDS.join(",")),
                "/success:enable".into(),
            ],
        ),
        Step::new(
            "audit_policy_failure",
            "auditpol",
            vec![
                "/set".into(),
                format!("/subcategory:{}", FAILURE_GUIDS.join(",")),
                "/failure:enable".into(),
            ],
        ),
        Step::new(
            "registry_cmdline",
            "reg",
            reg_add(AUDIT_KEY, "ProcessCreationIncludeCmdLine_Enabled"),
        ),
        Step::new(
            "registry_scriptblock",
            "reg",
            reg_add(PS_LOG_KEY, "EnableScriptBlockLogging"),
        ),
        Step::new(
            "security_log_size",
            "wevtutil",
            strings(&["sl", "Security", "/ms:268435456"]),
        ),
        Step::new(
            "powershell_log_size",
            "wevtutil",
            strings(&[
                "sl",
                "Microsoft-Windows-PowerShell/Operational",
                "/ms:67108864",
            ]),
        ),
    ]
}

/// A recorded registry value as `(reg-restore)` takes it: `null`, a number, or the text as is
/// (anything else is refused when the step runs).
fn entry_value(v: &Value) -> String {
    match v {
        Value::Null => "null".into(),
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

/// The `(reg-restore)` entries (`<value>=<before>`) recorded below data root `d`: by install
/// (`install-state.json`), else by an earlier `audit-policy --enable` (`audit-policy-state.json`)
/// (F15). None recorded (or unreadable): empty.
pub(crate) fn recorded_registry_entries(d: &Path) -> Vec<String> {
    ["install-state.json", "audit-policy-state.json"]
        .into_iter()
        .find_map(|name| {
            read_json(&d.join("data").join(name))?
                .get("registry_before")?
                .as_object()
                .cloned()
        })
        .map(|m| {
            m.iter()
                .map(|(k, v)| format!("{k}={}", entry_value(v)))
                .collect()
        })
        .unwrap_or_default()
}

/// The `audit-policy` plan. `--enable`: the data root as `install` makes it, the registry values
/// recorded once before anything changes, then [`AUDIT_STEPS`]. `--restore <f>`: `auditpol /restore`
/// and the registry values recorded by install (`install-state.json`) or by an earlier `--enable`
/// (`audit-policy-state.json`).
pub fn build_audit_plan(a: &AuditArgs, h: &dyn Host) -> Result<Plan, ArgError> {
    if a.enable == a.restore.is_some() {
        return Err(ArgError(
            "audit-policy에는 --enable 또는 --restore <파일> 중 하나만 지정합니다".into(),
        ));
    }
    let raw = match &a.data_root {
        Some(p) => p.to_string_lossy().into_owned(),
        None => default_data_root(h)?,
    };
    let d = full_path(&raw).map_err(|e| argument("--data-root", &e))?;
    let data = d.display().to_string();
    let audit_state = d.join("data").join("audit-policy-state.json");
    let mut notes = Vec::new();
    let mut steps = vec![Step::new("require_admin", "(admin)", vec![])];
    if a.enable {
        if let Some(note) = check_data_root(&d, h, "이전 레지스트리 기록")? {
            notes.push(note);
        }
        steps.push(Step::new(
            "secure_data_root",
            "(secure-data-root)",
            vec![data.clone()],
        ));
        let record = json!({
            "registry_before": registry_record(h),
            "audit_backup": backup_path(&data),
            "recorded_at": null,
        });
        steps.push(
            Step::new(
                "record_registry",
                "(write-json)",
                vec![audit_state.display().to_string(), record.to_string()],
            )
            .when("no_registry_record_yet"),
        );
        steps.extend(audit_steps(&data));
    } else {
        let restore = a.restore.as_deref().unwrap_or(Path::new(""));
        let file = full_path(&restore.to_string_lossy()).map_err(|e| argument("--restore", &e))?;
        if !file.is_file() {
            return Err(argument(
                "--restore",
                &format!("백업 파일 {} 이(가) 없습니다.", file.display()),
            ));
        }
        let entries = recorded_registry_entries(&d);
        steps.push(Step::new(
            "restore_audit_policy",
            "auditpol",
            vec!["/restore".into(), format!("/file:{}", file.display())],
        ));
        steps.push(Step::new("restore_registry", "(reg-restore)", entries));
    }
    let payload = h.payload();
    Ok(Plan {
        script: "audit-policy".into(),
        version: Some(payload.version),
        layout: Some(payload.layout),
        install_dir: None,
        data_root: Some(data),
        service_mode: None,
        steps,
        notes,
    })
}

/// `Restore-RegistryValues`' check: only the two values install sets, and only `null` (delete) or
/// a DWORD in ASCII digits (`[0-9]{1,10}` that fits a `u32`, F30). Returns `(key, name, value)`.
pub fn validate_registry_restore(
    entries: &[String],
) -> Result<Vec<(String, String, Option<u32>)>, String> {
    entries
        .iter()
        .map(|entry| {
            let unknown = || format!("알 수 없는 레지스트리 값 {entry}");
            let (full, value) = entry.rsplit_once('=').ok_or_else(unknown)?;
            let known = [AUDIT_VALUE, PS_VALUE]
                .into_iter()
                .find(|k| k.eq_ignore_ascii_case(full))
                .ok_or_else(unknown)?;
            let value = if value == "null" {
                None
            } else if (1..=10).contains(&value.len()) && value.bytes().all(|b| b.is_ascii_digit()) {
                Some(value.parse::<u32>().map_err(|_| unknown())?)
            } else {
                return Err(unknown());
            };
            let (key, name) = known.rsplit_once('\\').expect("a known value has a key");
            Ok((key.to_string(), name.to_string(), value))
        })
        .collect()
}

/// Runs a System32 tool with arguments and returns its exit code.
pub type NativeRun<'a> = dyn FnMut(&str, &[String]) -> Result<i32, StepError> + 'a;

/// `(reg-restore)`: every entry checked first, then `reg delete` (ok 0 or 1: already gone) for
/// `null` and `reg add … REG_DWORD` (ok 0) for a number. No entries: one line, nothing run.
pub fn restore_registry(
    entries: &[String],
    native: &mut NativeRun,
    say: &mut dyn FnMut(&str),
) -> Result<i32, StepError> {
    if entries.is_empty() {
        say("  되돌릴 레지스트리 값이 없습니다(install-state.json 없음).");
        return Ok(0);
    }
    let values = validate_registry_restore(entries).map_err(StepError::Failed)?;
    for (key, name, value) in values {
        let (args, ok): (Vec<String>, &[i32]) = match value {
            None => (strings(&["delete", &key, "/v", &name, "/f"]), &[0, 1]),
            Some(v) => (
                strings(&[
                    "add",
                    &key,
                    "/v",
                    &name,
                    "/t",
                    "REG_DWORD",
                    "/d",
                    &v.to_string(),
                    "/f",
                ]),
                &[0],
            ),
        };
        let code = native("reg", &args)?;
        if !ok.contains(&code) {
            return Err(StepError::Failed(format!(
                "reg ({key}\\{name}) 종료 코드 {code}"
            )));
        }
    }
    Ok(0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cli::{AuditArgs, InstallArgs};
    use crate::install::host::FakeHost;
    use crate::install::install_plan::build_install_plan;
    use crate::install::testutil::*;
    use serde_json::{Value, json};
    use std::fs;

    fn ids(p: &Plan) -> Vec<&str> {
        p.steps.iter().map(|x| x.id.as_str()).collect()
    }
    fn step<'a>(p: &'a Plan, id: &str) -> &'a Step {
        p.steps.iter().find(|x| x.id == id).unwrap()
    }

    #[test]
    fn audit_policy_enable_matches_install() {
        let s = Scratch::new();
        let data = s.path().join("d");
        let enable = build_audit_plan(
            &AuditArgs {
                enable: true,
                data_root: Some(data.clone()),
                ..Default::default()
            },
            &FakeHost::new(),
        )
        .unwrap();
        let install = build_install_plan(
            &InstallArgs {
                install_dir: Some(s.path().join("i")),
                data_root: Some(data),
                ..Default::default()
            },
            &FakeHost::new(),
        )
        .unwrap();
        let mut want = vec!["require_admin", "secure_data_root", "record_registry"];
        want.extend(AUDIT_STEPS);
        assert_eq!(ids(&enable), want);
        assert_eq!(enable.script, "audit-policy");
        for id in AUDIT_STEPS.iter().chain(["secure_data_root"].iter()) {
            assert_eq!(step(&enable, id), step(&install, id), "{id}");
        }
    }

    #[test]
    fn audit_policy_enable_records_the_registry_before_it_changes() {
        let s = Scratch::new();
        let data = s.path().join("d");
        let p = build_audit_plan(
            &AuditArgs {
                enable: true,
                data_root: Some(data.clone()),
                ..Default::default()
            },
            &FakeHost::new(),
        )
        .unwrap();
        let rec = step(&p, "record_registry");
        assert_eq!(
            (rec.cmd.as_str(), rec.when.as_deref()),
            ("(write-json)", Some("no_registry_record_yet"))
        );
        assert_eq!(
            rec.args[0],
            format!(r"{}\data\audit-policy-state.json", data.display())
        );
        let v: Value = serde_json::from_str(&rec.args[1]).unwrap();
        assert_eq!(v["registry_before"].as_object().unwrap().len(), 2);
        assert_eq!(
            v["audit_backup"],
            format!(r"{}\data\auditpol-backup.csv", data.display())
        );
    }

    #[test]
    fn audit_policy_restore_plan_reads_the_recorded_values() {
        let s = Scratch::new();
        let data = s.path().join("d");
        fs::create_dir_all(data.join("data")).unwrap();
        fs::write(
            data.join("data/audit-policy-state.json"),
            json!({"registry_before": {AUDIT_VALUE: null, PS_VALUE: 0}}).to_string(),
        )
        .unwrap();
        let backup = s.path().join("백업.csv");
        fs::write(&backup, "x").unwrap();
        let p = build_audit_plan(
            &AuditArgs {
                restore: Some(backup.clone()),
                data_root: Some(data),
                ..Default::default()
            },
            &FakeHost::new(),
        )
        .unwrap();
        assert_eq!(
            ids(&p),
            ["require_admin", "restore_audit_policy", "restore_registry"]
        );
        assert_eq!(
            step(&p, "restore_audit_policy").args,
            [
                "/restore".to_string(),
                format!("/file:{}", backup.display())
            ]
        );
        assert_eq!(
            step(&p, "restore_registry").args,
            [format!("{AUDIT_VALUE}=null"), format!("{PS_VALUE}=0")]
        );
    }

    #[test]
    fn audit_policy_argument_errors() {
        let s = Scratch::new();
        let foreign = s.path().join("foreign");
        fs::create_dir_all(foreign.join("x")).unwrap();
        let bad = [
            AuditArgs::default(),
            AuditArgs {
                enable: true,
                restore: Some(s.path().join("x.csv")),
                ..Default::default()
            },
            AuditArgs {
                restore: Some(s.path().join("missing.csv")),
                ..Default::default()
            },
            AuditArgs {
                enable: true,
                data_root: Some(format!("{}\\", std::env::var("SystemDrive").unwrap()).into()),
                ..Default::default()
            },
            AuditArgs {
                enable: true,
                data_root: Some(foreign),
                ..Default::default()
            },
        ];
        for a in bad {
            assert!(build_audit_plan(&a, &FakeHost::new()).is_err(), "{a:?}");
        }
    }

    #[test]
    fn restore_registry_refuses_values_install_never_set() {
        for bad in [
            r"HKLM\SOFTWARE\Evil\Run=1".to_string(),
            format!("{AUDIT_VALUE}=1 /f"),
            format!("{PS_VALUE}=-1"),
        ] {
            assert!(
                validate_registry_restore(std::slice::from_ref(&bad))
                    .unwrap_err()
                    .starts_with("알 수 없는 레지스트리 값"),
                "{bad}"
            );
        }
        let ok =
            validate_registry_restore(&[format!("{AUDIT_VALUE}=null"), format!("{PS_VALUE}=0")])
                .unwrap();
        assert_eq!(
            ok[1],
            (
                r"HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging"
                    .to_string(),
                "EnableScriptBlockLogging".to_string(),
                Some(0)
            )
        );
        assert_eq!(ok[0].2, None);
    }

    // --- additions beyond the plan text -----------------------------------------------------------

    #[test]
    fn audit_constants_are_plan_5s() {
        assert_eq!(
            SUCCESS_GUIDS,
            [
                "{0CCE922B-69AE-11D9-BED3-505054503030}",
                "{0CCE9215-69AE-11D9-BED3-505054503030}",
                "{0CCE9216-69AE-11D9-BED3-505054503030}",
                "{0CCE921C-69AE-11D9-BED3-505054503030}",
                "{0CCE922F-69AE-11D9-BED3-505054503030}",
            ]
        );
        assert_eq!(
            FAILURE_GUIDS,
            [
                "{0CCE9215-69AE-11D9-BED3-505054503030}",
                "{0CCE921C-69AE-11D9-BED3-505054503030}"
            ]
        );
        let steps = audit_steps(r"D:\데이터 폴더");
        assert_eq!(
            steps.iter().map(|s| s.id.as_str()).collect::<Vec<_>>(),
            AUDIT_STEPS
        );
        assert_eq!(
            steps[1].args,
            [
                "/set".to_string(),
                format!("/subcategory:{}", SUCCESS_GUIDS.join(",")),
                "/success:enable".into()
            ]
        );
        assert_eq!(
            steps[0].args[1],
            r"/file:D:\데이터 폴더\data\auditpol-backup.csv"
        );
        assert!(steps.iter().all(|s| s.ok == [0]));
        assert_eq!(
            steps.iter().map(|s| s.cmd.as_str()).collect::<Vec<_>>(),
            [
                "auditpol", "auditpol", "auditpol", "reg", "reg", "wevtutil", "wevtutil"
            ]
        );
    }

    #[test]
    fn audit_policy_plans_show_the_payload_and_no_install_dir() {
        let s = Scratch::new();
        let p = build_audit_plan(
            &AuditArgs {
                enable: true,
                data_root: Some(s.path().join("d")),
                ..Default::default()
            },
            &FakeHost::new(),
        )
        .unwrap();
        assert_eq!(
            (
                p.version.as_deref(),
                p.layout.as_deref(),
                p.install_dir.as_deref(),
                p.service_mode.as_deref()
            ),
            (Some("1.1.0"), Some("pyinstaller"), None, None)
        );
        assert_eq!(p.data_root, Some(s.path().join("d").display().to_string()));
        assert!(p.notes.is_empty());
        let v: Value = serde_json::from_str(&step(&p, "record_registry").args[1]).unwrap();
        assert!(
            v["recorded_at"].is_null(),
            "the executor stamps it when it runs (F15)"
        );
    }

    #[test]
    fn audit_policy_enable_records_the_current_registry_values() {
        let s = Scratch::new();
        let mut h = FakeHost::new();
        h.dwords.insert(PS_VALUE.into(), 0);
        let p = build_audit_plan(
            &AuditArgs {
                enable: true,
                data_root: Some(s.path().join("d")),
                ..Default::default()
            },
            &h,
        )
        .unwrap();
        let v: Value = serde_json::from_str(&step(&p, "record_registry").args[1]).unwrap();
        assert_eq!(
            v["registry_before"],
            json!({AUDIT_VALUE: null, PS_VALUE: 0})
        );
    }

    #[test]
    fn audit_policy_restore_prefers_the_install_state() {
        let s = Scratch::new();
        let data = s.path().join("d");
        fs::create_dir_all(data.join("data")).unwrap();
        fs::write(
            data.join("data/install-state.json"),
            json!({"registry_before": {AUDIT_VALUE: 1, PS_VALUE: null}}).to_string(),
        )
        .unwrap();
        fs::write(
            data.join("data/audit-policy-state.json"),
            json!({"registry_before": {AUDIT_VALUE: null, PS_VALUE: 0}}).to_string(),
        )
        .unwrap();
        let backup = s.path().join("b.csv");
        fs::write(&backup, "x").unwrap();
        let a = AuditArgs {
            restore: Some(backup.clone()),
            data_root: Some(data.clone()),
            ..Default::default()
        };
        let p = build_audit_plan(&a, &FakeHost::new()).unwrap();
        assert_eq!(
            step(&p, "restore_registry").args,
            [format!("{AUDIT_VALUE}=1"), format!("{PS_VALUE}=null")]
        );
        fs::remove_dir_all(data.join("data")).unwrap();
        let p = build_audit_plan(&a, &FakeHost::new()).unwrap();
        assert!(step(&p, "restore_registry").args.is_empty());
    }

    /// F17: the path forms of `test_install_refuses_device_unc_and_linked_paths` and the unsafe roots
    /// for `audit-policy --enable`; every error names `--data-root` (or `--restore`).
    #[test]
    fn audit_policy_enable_refuses_unsafe_data_roots() {
        let s = Scratch::new();
        junction(&s.path().join("link"), &s.path().join("real"));
        let x = s.path().join("x").display().to_string();
        let env = |k: &str| std::env::var(k).unwrap();
        let mut h = FakeHost::new();
        h.letters.retain(|l| *l != 'Q');
        for bad in [
            format!(r"\\?\{x}"),
            format!(r"\\.\{x}"),
            format!(r"\\localhost\{}$\{}", &x[..1], &x[3..]),
            s.path().join("link").join("x").display().to_string(),
            r"Q:\".into(),
            env("ProgramData"),
            env("ProgramData").to_uppercase(),
            format!(r"{}\Temp\mcp", env("SystemRoot")),
        ] {
            let e = build_audit_plan(
                &AuditArgs {
                    enable: true,
                    data_root: Some(bad.clone().into()),
                    ..Default::default()
                },
                &h,
            )
            .unwrap_err();
            assert!(e.0.starts_with("--data-root"), "{bad}: {}", e.0);
        }
        let e = build_audit_plan(
            &AuditArgs {
                restore: Some(s.path().join("missing.csv")),
                ..Default::default()
            },
            &h,
        )
        .unwrap_err();
        assert!(e.0.starts_with("--restore"), "{}", e.0);
    }

    /// Plan 5's `test_install_refuses_a_data_root_below_a_folder_others_may_rename`,
    /// `test_existing_data_root_others_may_delete_or_rechmod_is_refused` and
    /// `test_existing_data_root_with_harmless_extra_rights_is_accepted` ran both dry runs: the
    /// rules are tested in `acl`; here `install` and `audit-policy --enable` apply them alike, as a
    /// `--data-root` error that names the folder and the SID, and accept what does no harm.
    #[test]
    fn install_and_audit_policy_refuse_a_data_root_others_may_change_alike() {
        use crate::install::acl::{AUTHENTICATED_USERS, EVERYONE};
        let plans = |s: &Scratch, d: &Path| {
            [
                build_install_plan(
                    &InstallArgs {
                        install_dir: Some(s.path().join("i")),
                        data_root: Some(d.to_path_buf()),
                        ..Default::default()
                    },
                    &FakeHost::new(),
                ),
                build_audit_plan(
                    &AuditArgs {
                        enable: true,
                        data_root: Some(d.to_path_buf()),
                        ..Default::default()
                    },
                    &FakeHost::new(),
                ),
            ]
        };
        // A folder above the data root others may rename; inherit-only rights do not count.
        let s = Scratch::new();
        let apps = s.path().join("apps");
        fs::create_dir(&apps).unwrap();
        let root = apps.join("MCP Monitor");
        grant(&apps, "(OI)(CI)M");
        for p in plans(&s, &root) {
            let e = p.unwrap_err().0;
            assert!(
                e.starts_with("--data-root")
                    && e.contains(&apps.display().to_string())
                    && e.contains(AUTHENTICATED_USERS),
                "{e}"
            );
        }
        icacls(&apps, &["/remove:g", &format!("*{AUTHENTICATED_USERS}")]);
        grant(&apps, "(OI)(CI)(IO)M");
        for p in plans(&s, &root) {
            assert_eq!(
                step(&p.unwrap(), "secure_data_root").args,
                [root.display().to_string()]
            );
        }
        // An existing data root others may re-permission: refused, with the advice to delete it.
        let s = Scratch::new();
        let root = s.path().join("MCP Monitor");
        fs::create_dir_all(root.join("data")).unwrap();
        fs::write(root.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        grant(&root, "(WDAC)");
        for p in plans(&s, &root) {
            let e = p.unwrap_err().0;
            assert!(
                e.starts_with("--data-root")
                    && e.contains(AUTHENTICATED_USERS)
                    && e.contains("지우고"),
                "{e}"
            );
        }
        // Read and execute for others, and inherit-only rights, take nothing over.
        let s = Scratch::new();
        let root = s.path().join("MCP Monitor");
        fs::create_dir(&root).unwrap();
        grant(&root, "(OI)(CI)RX");
        icacls(&root, &["/grant", &format!("*{EVERYONE}:(OI)(CI)(IO)RX")]);
        for p in plans(&s, &root) {
            assert_eq!(
                step(&p.unwrap(), "secure_data_root").args,
                [root.display().to_string()]
            );
        }
    }

    #[test]
    fn audit_policy_dry_run_without_admin_plans_over_an_installed_data_root() {
        if crate::winutil::skip_when_elevated(
            "audit_policy_dry_run_without_admin_plans_over_an_installed_data_root",
            "an administrator can read the locked data root, so there is no note",
        ) {
            return;
        }
        let s = Scratch::new();
        let root = s.path().join("MCP Monitor");
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
        let p = build_audit_plan(
            &AuditArgs {
                enable: true,
                data_root: Some(root.clone()),
                dry_run: true,
                ..Default::default()
            },
            &FakeHost::new(),
        );
        icacls(&root, &["/reset", "/T", "/C", "/Q"]);
        let p = p.unwrap();
        assert_eq!(p.notes.len(), 1);
        assert!(
            p.notes[0].contains("이전 레지스트리 기록")
                && p.notes[0].contains("관리자 권한으로 다시 실행하면 확인합니다"),
            "{}",
            p.notes[0]
        );
        assert_eq!(
            step(&p, "secure_data_root").args,
            [root.display().to_string()]
        );
        let p = build_audit_plan(
            &AuditArgs {
                enable: true,
                data_root: Some(root),
                ..Default::default()
            },
            &FakeHost::new(),
        )
        .unwrap();
        assert!(p.notes.is_empty());
    }

    #[test]
    fn restore_registry_numbers_are_ascii_digits_that_fit_a_dword() {
        for bad in [
            format!("{PS_VALUE}=٣"),
            format!("{PS_VALUE}=4294967296"),
            format!("{PS_VALUE}=12345678901"),
            format!("{PS_VALUE}="),
            PS_VALUE.to_string(),
            format!("{PS_VALUE}=+1"),
            format!("{AUDIT_VALUE}=null=1"),
        ] {
            assert!(
                validate_registry_restore(std::slice::from_ref(&bad)).is_err(),
                "{bad}"
            );
        }
        let ok = validate_registry_restore(&[
            format!("{PS_VALUE}=4294967295"),
            format!("{}=7", AUDIT_VALUE.to_lowercase()),
        ])
        .unwrap();
        assert_eq!(ok[0].2, Some(u32::MAX));
        assert_eq!(
            (ok[1].0.as_str(), ok[1].1.as_str(), ok[1].2),
            (
                r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit",
                "ProcessCreationIncludeCmdLine_Enabled",
                Some(7)
            )
        );
    }

    #[test]
    fn restore_registry_runs_reg_like_powershell() {
        let mut calls: Vec<(String, Vec<String>)> = vec![];
        let mut said: Vec<String> = vec![];
        let mut codes = vec![1, 0].into_iter();
        let entries = [format!("{AUDIT_VALUE}=null"), format!("{PS_VALUE}=0")];
        let r = restore_registry(
            &entries,
            &mut |cmd, args| {
                calls.push((cmd.into(), args.to_vec()));
                Ok(codes.next().unwrap())
            },
            &mut |m| said.push(m.into()),
        );
        assert_eq!(r, Ok(0));
        assert_eq!(
            calls,
            [
                (
                    "reg".to_string(),
                    [
                        "delete",
                        r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit",
                        "/v",
                        "ProcessCreationIncludeCmdLine_Enabled",
                        "/f"
                    ]
                    .map(String::from)
                    .to_vec()
                ),
                (
                    "reg".to_string(),
                    [
                        "add",
                        r"HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging",
                        "/v",
                        "EnableScriptBlockLogging",
                        "/t",
                        "REG_DWORD",
                        "/d",
                        "0",
                        "/f"
                    ]
                    .map(String::from)
                    .to_vec()
                ),
            ]
        );
        assert!(said.is_empty());
        // `reg add` accepts only 0; `reg delete` also 1 (the value was already gone).
        let r = restore_registry(&[format!("{PS_VALUE}=1")], &mut |_, _| Ok(1), &mut |_| {});
        assert_eq!(
            r,
            Err(StepError::Failed(format!("reg ({PS_VALUE}) 종료 코드 1")))
        );
        // Nothing to restore: a line, no reg call.
        let mut ran = false;
        assert_eq!(
            restore_registry(
                &[],
                &mut |_, _| {
                    ran = true;
                    Ok(0)
                },
                &mut |m| said.push(m.into())
            ),
            Ok(0)
        );
        assert!(!ran);
        assert_eq!(
            said,
            ["  되돌릴 레지스트리 값이 없습니다(install-state.json 없음)."]
        );
        // A bad entry stops before any reg runs.
        let r = restore_registry(
            &[format!("{PS_VALUE}=0"), r"HKLM\x\y=1".into()],
            &mut |_, _| {
                ran = true;
                Ok(0)
            },
            &mut |_| {},
        );
        assert!(
            matches!(r, Err(StepError::Failed(m)) if m.starts_with("알 수 없는 레지스트리 값"))
        );
        assert!(!ran);
    }
}
