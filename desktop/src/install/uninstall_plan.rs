//! `uninstall [--dry-run]`: the uninstall plan (Plan 5's PowerShell uninstall script with the
//! desktop steps, Y19–Y21). Data stays unless `--remove-data`, and then only a data root with
//! our marker. Nothing here changes anything.

use crate::cli::{ArgError, UninstallArgs};
use crate::install::acl::data_root_readable;
use crate::install::audit::{backup_path, recorded_registry_entries};
use crate::install::host::{Host, SERVICE_NAME, UNINSTALL_KEY};
use crate::install::install_plan::{
    DEFAULT_EXTERNAL_PORT, argument, default_data_root, env_folder, read_json, recorded_port,
    service_folders,
};
use crate::install::paths::{full_path, is_inside, same_path, unsafe_root_reason};
use crate::install::plan::{Plan, Step};
use serde_json::Value;
use std::path::Path;

fn lossy(p: &Path) -> String {
    p.to_string_lossy().into_owned()
}

/// A non-empty string field of an earlier install's JSON.
fn text(v: Option<&Value>, key: &str) -> Option<String> {
    v?.get(key)?
        .as_str()
        .filter(|s| !s.is_empty())
        .map(str::to_string)
}

/// Plan 5's uninstall plan with the desktop steps. Folders (F13 b): `D0` = `--data-root` or
/// `%ProgramData%\MCP Monitor`; `I` = `--install-dir` → the Apps & features entry →
/// `<D0>\data\install-state.json`'s `install_dir` → the service's binPath →
/// `%ProgramFiles%\MCP Monitor`; `D` = `--data-root` → `<I>\install.json`'s `data_root` → the
/// binPath's `--root` → `D0`. The earlier install's state is read from `D`.
pub fn build_uninstall_plan(a: &UninstallArgs, h: &dyn Host) -> Result<Plan, ArgError> {
    let from_service = h
        .service_exists()
        .then(|| h.service_bin_path())
        .flatten()
        .and_then(|b| service_folders(&b))
        .unwrap_or_default();
    let d0_raw = match &a.data_root {
        Some(p) => lossy(p),
        None => default_data_root(h)?,
    };
    let d0 = full_path(&d0_raw).map_err(|e| argument("--data-root", &e))?;
    let state0 = read_json(&d0.join("data").join("install-state.json"));

    let i_raw = match (
        &a.install_dir,
        h.installed()
            .map(|x| lossy(&x.install_location))
            .filter(|p| !p.is_empty()),
        text(state0.as_ref(), "install_dir"),
        &from_service.install_dir,
    ) {
        (Some(p), ..) => lossy(p),
        (None, Some(p), ..) => p,
        (None, None, Some(p), _) => p,
        (None, None, None, Some(p)) => lossy(p),
        (None, None, None, None) => env_folder(h, "--install-dir", "ProgramFiles")?,
    };
    let i = full_path(&i_raw).map_err(|e| argument("--install-dir", &e))?;
    let inst = i.display().to_string();
    // remove_install_dir deletes this folder whole.
    if let Some(why) = unsafe_root_reason(&inst, h.env(), h.volumes()) {
        return Err(argument("--install-dir", &why));
    }

    let info = read_json(&i.join("install.json"));
    let d = match (
        &a.data_root,
        text(info.as_ref(), "data_root"),
        &from_service.data_root,
    ) {
        (Some(_), ..) => d0,
        (None, Some(p), _) => full_path(&p).map_err(|e| argument("--data-root", &e))?,
        (None, None, Some(p)) => full_path(&lossy(p)).map_err(|e| argument("--data-root", &e))?,
        (None, None, None) => d0,
    };
    let data = d.display().to_string();
    if a.remove_data
        && let Some(why) = unsafe_root_reason(&data, h.env(), h.volumes())
    {
        return Err(argument(
            "--data-root",
            &format!("{why} --remove-data는 이 폴더를 지우지 않습니다."),
        ));
    }
    // Removing the install folder would take a data root inside it along (Plan 5 I3).
    if !a.remove_data && (same_path(&d, &i) || is_inside(&d, &i)) {
        return Err(argument(
            "--data-root",
            &format!(
                "{data}가 설치 폴더({inst}) 안에 있어 데이터를 남길 수 없습니다(--remove-data로 함께 지우기)."
            ),
        ));
    }

    let mut notes = Vec::new();
    if !h.is_admin() && !data_root_readable(&d) {
        notes.push(format!(
            "{data} 은(는) 관리자만 읽을 수 있어 이전 설치 상태(외부 포트, 감사 정책 백업, 레지스트리 기록)를 확인하지 못했습니다. 관리자 권한으로 다시 실행하면 확인합니다."
        ));
    }
    let state = read_json(&d.join("data").join("install-state.json"));
    let external_port = recorded_port(state.as_ref(), "external_port")
        .or_else(|| recorded_port(info.as_ref(), "external_port"))
        .or(from_service.external_port)
        .unwrap_or(DEFAULT_EXTERNAL_PORT);
    let audit_backup = text(state.as_ref(), "audit_backup").unwrap_or_else(|| backup_path(&data));
    let program_data = h
        .env()
        .get("ProgramData")
        .ok_or_else(|| argument("--data-root", "%ProgramData% 을(를) 알 수 없습니다"))?;

    let s = |v: &[&str]| v.iter().map(|x| x.to_string()).collect::<Vec<String>>();
    let mut steps = vec![
        Step::new("require_admin", "(admin)", vec![]),
        Step::new("stop_service", "sc.exe", s(&["stop", SERVICE_NAME])).ok(&[0, 1060, 1062]),
        Step::new("delete_service", "sc.exe", s(&["delete", SERVICE_NAME])).ok(&[0, 1060]),
        Step::new("stop_apps", "(stop-apps)", vec![inst.clone()]),
        Step::new(
            "firewall_delete",
            "netsh",
            s(&[
                "advfirewall",
                "firewall",
                "delete",
                "rule",
                &format!("name=MCP Monitor ({external_port})"),
            ]),
        )
        .ok(&[0, 1]),
    ];
    if a.restore_audit_policy {
        steps.push(
            Step::new(
                "restore_audit_policy",
                "auditpol",
                vec!["/restore".into(), format!("/file:{audit_backup}")],
            )
            .when("audit_backup_exists"),
        );
        steps.push(Step::new(
            "restore_registry",
            "(reg-restore)",
            recorded_registry_entries(&d),
        ));
    }
    steps.push(Step::new(
        "remove_uninstall_entry",
        "(registry-delete)",
        vec![UNINSTALL_KEY.to_string()],
    ));
    steps.push(Step::new(
        "remove_shortcut",
        "(remove)",
        vec![format!(
            r"{program_data}\Microsoft\Windows\Start Menu\Programs\MCP Monitor.lnk"
        )],
    ));
    steps.push(Step::new(
        "remove_run_values",
        "(run-values-remove)",
        vec![inst.clone()],
    ));
    steps.push(
        Step::new("remove_install_dir", "(remove-install)", vec![inst.clone()])
            .when("install_dir_is_bundle"),
    );
    // Review item 8: a failed upgrade (Y15) can leave the earlier install (`<I>.old`) and a
    // staging folder (`<I>.staging`) next to it; each goes only when it is ours.
    steps.push(
        Step::new(
            "remove_old_install",
            "(remove-old)",
            vec![format!("{inst}.old")],
        )
        .when("old_is_ours"),
    );
    steps.push(
        Step::new(
            "remove_staging",
            "(remove-staging)",
            vec![format!("{inst}.staging")],
        )
        .when("staging_is_ours"),
    );
    if a.remove_data {
        let users = h
            .env()
            .get("PUBLIC")
            .and_then(|p| Path::new(&p).parent().map(Path::to_path_buf))
            .filter(|p| !p.as_os_str().is_empty())
            .ok_or_else(|| {
                argument(
                    "--remove-data",
                    "%PUBLIC% 을(를) 알 수 없어 사용자 프로필 폴더를 찾지 못했습니다",
                )
            })?;
        steps.push(
            Step::new("remove_data", "(remove)", vec![data.clone()]).when("data_root_is_ours"),
        );
        steps.push(Step::new(
            "remove_webview_profiles",
            "(remove-glob)",
            vec![format!(r"{}\*\AppData\Local\mcp-monitor", users.display())],
        ));
    }

    Ok(Plan {
        script: "uninstall".into(),
        version: text(state.as_ref(), "version"),
        layout: text(state.as_ref(), "layout"),
        install_dir: Some(inst),
        data_root: Some(data),
        service_mode: None,
        steps,
        notes,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::audit::{AUDIT_VALUE, PS_VALUE};
    use crate::install::host::{FakeHost, Installed};
    use crate::install::testutil::*;
    use serde_json::json;
    use std::{fs, path::PathBuf};

    fn base(s: &Scratch) -> UninstallArgs {
        UninstallArgs {
            install_dir: Some(s.path().join("i")),
            data_root: Some(s.path().join("d")),
            ..Default::default()
        }
    }
    fn ids(p: &Plan) -> Vec<&str> {
        p.steps.iter().map(|x| x.id.as_str()).collect()
    }
    fn step<'a>(p: &'a Plan, id: &str) -> &'a Step {
        p.steps.iter().find(|x| x.id == id).unwrap()
    }

    #[test]
    fn uninstall_plan_keeps_data_by_default() {
        let s = Scratch::new();
        assert_eq!(
            ids(&build_uninstall_plan(&base(&s), &FakeHost::new()).unwrap()),
            [
                "require_admin",
                "stop_service",
                "delete_service",
                "stop_apps",
                "firewall_delete",
                "remove_uninstall_entry",
                "remove_shortcut",
                "remove_run_values",
                "remove_install_dir",
                "remove_old_install",
                "remove_staging"
            ]
        );
        let full = UninstallArgs {
            remove_data: true,
            restore_audit_policy: true,
            ..base(&s)
        };
        assert_eq!(
            ids(&build_uninstall_plan(&full, &FakeHost::new()).unwrap()),
            [
                "require_admin",
                "stop_service",
                "delete_service",
                "stop_apps",
                "firewall_delete",
                "restore_audit_policy",
                "restore_registry",
                "remove_uninstall_entry",
                "remove_shortcut",
                "remove_run_values",
                "remove_install_dir",
                "remove_old_install",
                "remove_staging",
                "remove_data",
                "remove_webview_profiles"
            ]
        );
    }

    #[test]
    fn uninstall_plan_details_without_state() {
        let s = Scratch::new();
        let (inst, data) = (
            s.path().join("i").display().to_string(),
            s.path().join("d").display().to_string(),
        );
        let p = build_uninstall_plan(
            &UninstallArgs {
                remove_data: true,
                restore_audit_policy: true,
                ..base(&s)
            },
            &FakeHost::new(),
        )
        .unwrap();
        assert_eq!(
            (
                p.script.as_str(),
                p.install_dir.as_deref(),
                p.data_root.as_deref(),
                p.version.as_deref()
            ),
            ("uninstall", Some(inst.as_str()), Some(data.as_str()), None)
        );
        assert_eq!(step(&p, "stop_service").ok, [0, 1060, 1062]);
        assert_eq!(
            (
                step(&p, "delete_service").args.clone(),
                step(&p, "delete_service").ok.clone()
            ),
            (
                vec!["delete".to_string(), "mcp-monitor".into()],
                vec![0, 1060]
            )
        );
        let fw = step(&p, "firewall_delete");
        assert_eq!(
            (fw.args.clone(), fw.ok.clone()),
            (
                [
                    "advfirewall",
                    "firewall",
                    "delete",
                    "rule",
                    "name=MCP Monitor (8701)"
                ]
                .map(String::from)
                .to_vec(),
                vec![0, 1]
            )
        );
        assert_eq!(
            step(&p, "restore_audit_policy").args,
            [
                "/restore".to_string(),
                format!(r"/file:{data}\data\auditpol-backup.csv")
            ]
        );
        assert!(step(&p, "restore_registry").args.is_empty());
        assert_eq!(
            (
                step(&p, "remove_install_dir").cmd.as_str(),
                step(&p, "remove_install_dir").when.as_deref()
            ),
            ("(remove-install)", Some("install_dir_is_bundle"))
        );
        // Review item 8: what a failed upgrade left next to the install folder goes too, each only
        // when it is ours (checked again just before).
        let old = step(&p, "remove_old_install");
        assert_eq!(
            (old.cmd.as_str(), old.args.clone(), old.when.as_deref()),
            (
                "(remove-old)",
                vec![format!("{inst}.old")],
                Some("old_is_ours")
            )
        );
        let staging = step(&p, "remove_staging");
        assert_eq!(
            (
                staging.cmd.as_str(),
                staging.args.clone(),
                staging.when.as_deref()
            ),
            (
                "(remove-staging)",
                vec![format!("{inst}.staging")],
                Some("staging_is_ours")
            )
        );
        assert_eq!(step(&p, "remove_data").args, std::slice::from_ref(&data));
        assert_eq!(
            step(&p, "remove_data").when.as_deref(),
            Some("data_root_is_ours")
        );
        let profiles = &step(&p, "remove_webview_profiles").args;
        assert!(
            profiles.len() == 1 && profiles[0].ends_with(r"\*\AppData\Local\mcp-monitor"),
            "{profiles:?}"
        );
        assert_eq!(step(&p, "remove_uninstall_entry").args, [UNINSTALL_KEY]);
    }

    #[test]
    fn uninstall_plan_reads_the_install_state() {
        let s = Scratch::new();
        let data = s.path().join("d");
        fs::create_dir_all(data.join("data")).unwrap();
        let backup = data
            .join("data/auditpol-backup.csv")
            .display()
            .to_string()
            .replace('/', "\\");
        fs::write(data.join("data/install-state.json"), json!({"version": "1.0.0", "layout": "pyinstaller", "external_port": 9701, "firewall": true,
            "registry_before": {AUDIT_VALUE: null, PS_VALUE: 0}, "audit_backup": &backup}).to_string()).unwrap();
        let p = build_uninstall_plan(
            &UninstallArgs {
                remove_data: true,
                restore_audit_policy: true,
                ..base(&s)
            },
            &FakeHost::new(),
        )
        .unwrap();
        assert_eq!(
            (p.version.as_deref(), p.layout.as_deref()),
            (Some("1.0.0"), Some("pyinstaller"))
        );
        assert_eq!(
            step(&p, "firewall_delete").args[4],
            "name=MCP Monitor (9701)"
        );
        assert_eq!(
            step(&p, "restore_audit_policy").args,
            ["/restore".to_string(), format!("/file:{backup}")]
        );
        assert_eq!(
            step(&p, "restore_registry").args,
            [format!("{AUDIT_VALUE}=null"), format!("{PS_VALUE}=0")]
        );
    }

    #[test]
    fn uninstall_reads_the_install_dir_from_apps_and_features() {
        let s = Scratch::new();
        let mut h = FakeHost::new();
        h.installed = Some(Installed {
            version: "1.0.0".into(),
            install_location: s.path().join("elsewhere"),
        });
        let p = build_uninstall_plan(
            &UninstallArgs {
                data_root: Some(s.path().join("d")),
                ..Default::default()
            },
            &h,
        )
        .unwrap();
        assert_eq!(
            p.install_dir.as_deref(),
            Some(s.path().join("elsewhere").display().to_string().as_str())
        );
    }

    #[test]
    fn uninstall_refuses_to_remove_unsafe_roots() {
        let s = Scratch::new();
        let e = std::env::var;
        let cases = [
            UninstallArgs {
                data_root: Some(format!("{}\\", e("SystemDrive").unwrap()).into()),
                remove_data: true,
                ..base(&s)
            },
            UninstallArgs {
                data_root: Some(e("ProgramData").unwrap().into()),
                remove_data: true,
                ..base(&s)
            },
            UninstallArgs {
                data_root: Some(
                    PathBuf::from(e("PUBLIC").unwrap())
                        .parent()
                        .unwrap()
                        .to_path_buf(),
                ),
                remove_data: true,
                ..base(&s)
            },
            UninstallArgs {
                data_root: Some(s.path().join("i").join("var")),
                ..base(&s)
            },
        ];
        for a in cases {
            assert!(build_uninstall_plan(&a, &FakeHost::new()).is_err(), "{a:?}");
        }
    }

    #[test]
    fn uninstall_refuses_device_unc_and_linked_paths() {
        let s = Scratch::new();
        let marked = s.path().join("real").join("marked");
        fs::create_dir_all(marked.join("data")).unwrap();
        fs::write(marked.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        junction(&s.path().join("link"), &s.path().join("real"));
        let m = marked.display().to_string();
        let bad = [
            format!(r"\\?\{m}"),
            format!(r"\\localhost\{}$\{}", &m[..1], &m[3..]),
            s.path().join("link").join("marked").display().to_string(),
        ];
        for b in &bad {
            assert!(
                build_uninstall_plan(
                    &UninstallArgs {
                        data_root: Some(b.into()),
                        remove_data: true,
                        ..base(&s)
                    },
                    &FakeHost::new()
                )
                .is_err(),
                "{b}"
            );
            assert!(
                build_uninstall_plan(
                    &UninstallArgs {
                        install_dir: Some(b.into()),
                        ..base(&s)
                    },
                    &FakeHost::new()
                )
                .is_err(),
                "{b}"
            );
        }
        assert!(marked.join("data/mcp-monitor-data-root.json").is_file());
    }

    // --- additions beyond the plan text -----------------------------------------------------------

    /// Carry from Task 5: removing the install folder would take a data root inside it along, so
    /// without `--remove-data` that is an argument error, in any case of the path (F04), also when
    /// the data root comes from `install.json`. With `--remove-data` it is allowed.
    #[test]
    fn a_data_root_inside_the_install_dir_needs_remove_data() {
        let s = Scratch::new();
        let inst = s.path().join("i");
        for d in [
            inst.join("var"),
            inst.clone(),
            PathBuf::from(swap_case(&inst.join("var"))),
            PathBuf::from(swap_case(&inst)),
        ] {
            let e = build_uninstall_plan(
                &UninstallArgs {
                    data_root: Some(d.clone()),
                    ..base(&s)
                },
                &FakeHost::new(),
            )
            .unwrap_err();
            assert!(
                e.0.starts_with("--data-root: ")
                    && e.0.ends_with(
                        "안에 있어 데이터를 남길 수 없습니다(--remove-data로 함께 지우기)."
                    ),
                "{}: {}",
                d.display(),
                e.0
            );
            let p = build_uninstall_plan(
                &UninstallArgs {
                    data_root: Some(d.clone()),
                    remove_data: true,
                    ..base(&s)
                },
                &FakeHost::new(),
            )
            .unwrap();
            assert_eq!(step(&p, "remove_data").args, [d.display().to_string()]);
        }
        fs::create_dir_all(&inst).unwrap();
        fs::write(
            inst.join("install.json"),
            json!({"data_root": inst.join("var")}).to_string(),
        )
        .unwrap();
        let a = UninstallArgs {
            install_dir: Some(inst.clone()),
            ..Default::default()
        };
        assert!(
            build_uninstall_plan(&a, &FakeHost::new())
                .unwrap_err()
                .0
                .starts_with("--data-root: ")
        );
        // A data root next to (not inside) the install folder, or one whose name only starts alike.
        for d in [s.path().join("d"), s.path().join("i2")] {
            assert!(
                build_uninstall_plan(
                    &UninstallArgs {
                        data_root: Some(d),
                        ..base(&s)
                    },
                    &FakeHost::new()
                )
                .is_ok()
            );
        }
    }

    /// The messages name the option; an unsafe data root says it is not deleted.
    #[test]
    fn unsafe_roots_name_their_option() {
        let s = Scratch::new();
        let pd = std::env::var("ProgramData").unwrap();
        let e = build_uninstall_plan(
            &UninstallArgs {
                data_root: Some(swap_case(Path::new(&pd)).into()),
                remove_data: true,
                ..base(&s)
            },
            &FakeHost::new(),
        )
        .unwrap_err();
        assert!(
            e.0.starts_with("--data-root: ")
                && e.0.ends_with(" --remove-data는 이 폴더를 지우지 않습니다."),
            "{}",
            e.0
        );
        // Without --remove-data the data root is not deleted, so it is not checked.
        assert!(
            build_uninstall_plan(
                &UninstallArgs {
                    data_root: Some(pd.clone().into()),
                    ..base(&s)
                },
                &FakeHost::new()
            )
            .is_ok()
        );
        let drive = format!("{}\\", std::env::var("SystemDrive").unwrap().to_lowercase());
        let e = build_uninstall_plan(
            &UninstallArgs {
                install_dir: Some(drive.into()),
                ..base(&s)
            },
            &FakeHost::new(),
        )
        .unwrap_err();
        assert!(e.0.starts_with("--install-dir: "), "{}", e.0);
    }

    /// F13 (b): `D0` = `--data-root` or the default; `I` from the Apps & features entry, else
    /// `D0`'s install state, else the service, else the default; then `D` from `<I>\install.json`,
    /// else the service, else `D0`. The state is read from that `D`.
    #[test]
    fn folders_resolve_from_d0_to_the_install_dir_to_the_data_root() {
        let s = Scratch::new();
        let (d0, inst, d) = (
            s.path().join("d0"),
            s.path().join("inst"),
            s.path().join("d"),
        );
        fs::create_dir_all(d0.join("data")).unwrap();
        fs::write(
            d0.join("data/install-state.json"),
            json!({"install_dir": &inst, "version": "0.9.0", "external_port": 1111}).to_string(),
        )
        .unwrap();
        fs::create_dir_all(&inst).unwrap();
        fs::write(
            inst.join("install.json"),
            json!({"data_root": &d}).to_string(),
        )
        .unwrap();
        fs::create_dir_all(d.join("data")).unwrap();
        fs::write(
            d.join("data/install-state.json"),
            json!({"version": "1.0.0", "external_port": 9701}).to_string(),
        )
        .unwrap();
        let p = build_uninstall_plan(
            &UninstallArgs {
                data_root: Some(d0.clone()),
                ..Default::default()
            },
            &FakeHost::new(),
        )
        .unwrap();
        // --data-root names D0 but install.json names D: --data-root wins.
        assert_eq!(
            (p.install_dir.as_deref(), p.data_root.as_deref()),
            (
                Some(inst.display().to_string().as_str()),
                Some(d0.display().to_string().as_str())
            )
        );
        assert_eq!(
            step(&p, "firewall_delete").args[4],
            "name=MCP Monitor (1111)"
        );
        // Without --data-root: D0 is the default (%ProgramData%\MCP Monitor of this host).
        let mut h = FakeHost::new();
        h.env.0.insert(
            "ProgramData".into(),
            s.path().join("pd").display().to_string(),
        );
        fs::create_dir_all(s.path().join("pd/MCP Monitor/data")).unwrap();
        fs::write(
            s.path().join("pd/MCP Monitor/data/install-state.json"),
            json!({"install_dir": &inst}).to_string(),
        )
        .unwrap();
        let p = build_uninstall_plan(&UninstallArgs::default(), &h).unwrap();
        assert_eq!(
            (
                p.install_dir.as_deref(),
                p.data_root.as_deref(),
                p.version.as_deref()
            ),
            (
                Some(inst.display().to_string().as_str()),
                Some(d.display().to_string().as_str()),
                Some("1.0.0")
            )
        );
        assert_eq!(
            step(&p, "firewall_delete").args[4],
            "name=MCP Monitor (9701)"
        );
        // Apps & features wins over the state; the service's binPath over the defaults.
        h.installed = Some(Installed {
            version: "1.0.0".into(),
            install_location: s.path().join("arp"),
        });
        assert_eq!(
            build_uninstall_plan(&UninstallArgs::default(), &h)
                .unwrap()
                .install_dir,
            Some(s.path().join("arp").display().to_string())
        );
        let mut h = FakeHost::new();
        h.env.0.insert(
            "ProgramData".into(),
            s.path().join("empty-pd").display().to_string(),
        );
        h.service = true;
        h.bin_path = Some(format!(
            r#""{}\bin\monitor\mcp-monitor.exe" service --root "{}" --local-port 8800 --external-port 8801"#,
            s.path().join("svc-i").display(),
            s.path().join("svc-d").display()
        ));
        let p = build_uninstall_plan(&UninstallArgs::default(), &h).unwrap();
        assert_eq!(
            (p.install_dir.clone(), p.data_root.clone()),
            (
                Some(s.path().join("svc-i").display().to_string()),
                Some(s.path().join("svc-d").display().to_string())
            )
        );
        assert_eq!(
            step(&p, "firewall_delete").args[4],
            "name=MCP Monitor (8801)"
        );
        // Nothing anywhere: %ProgramFiles%\MCP Monitor and %ProgramData%\MCP Monitor.
        let p = build_uninstall_plan(&UninstallArgs::default(), &FakeHost::new()).unwrap();
        let env = |k: &str| std::env::var(k).unwrap();
        assert_eq!(
            (p.install_dir, p.data_root),
            (
                Some(format!(r"{}\MCP Monitor", env("ProgramFiles"))),
                Some(format!(r"{}\MCP Monitor", env("ProgramData")))
            )
        );
    }

    /// F15 / Plan 5 T483: without install-state.json the registry values come from an earlier
    /// `audit-policy --enable` (audit-policy-state.json); install-state.json wins when both exist.
    #[test]
    fn restore_registry_falls_back_to_the_audit_policy_state() {
        let s = Scratch::new();
        let data = s.path().join("d");
        fs::create_dir_all(data.join("data")).unwrap();
        fs::write(
            data.join("data/audit-policy-state.json"),
            json!({"registry_before": {AUDIT_VALUE: null, PS_VALUE: 0}}).to_string(),
        )
        .unwrap();
        let a = UninstallArgs {
            restore_audit_policy: true,
            ..base(&s)
        };
        assert_eq!(
            step(
                &build_uninstall_plan(&a, &FakeHost::new()).unwrap(),
                "restore_registry"
            )
            .args,
            [format!("{AUDIT_VALUE}=null"), format!("{PS_VALUE}=0")]
        );
        fs::write(
            data.join("data/install-state.json"),
            json!({"registry_before": {AUDIT_VALUE: 1, PS_VALUE: null}}).to_string(),
        )
        .unwrap();
        assert_eq!(
            step(
                &build_uninstall_plan(&a, &FakeHost::new()).unwrap(),
                "restore_registry"
            )
            .args,
            [format!("{AUDIT_VALUE}=1"), format!("{PS_VALUE}=null")]
        );
    }

    #[test]
    fn uninstall_targets_this_pcs_shortcut_and_every_profile() {
        let s = Scratch::new();
        let p = build_uninstall_plan(
            &UninstallArgs {
                remove_data: true,
                ..base(&s)
            },
            &FakeHost::new(),
        )
        .unwrap();
        let env = |k: &str| std::env::var(k).unwrap();
        let inst = s.path().join("i").display().to_string();
        assert_eq!(
            (
                step(&p, "remove_shortcut").cmd.as_str(),
                step(&p, "remove_shortcut").args.clone()
            ),
            (
                "(remove)",
                vec![format!(
                    r"{}\Microsoft\Windows\Start Menu\Programs\MCP Monitor.lnk",
                    env("ProgramData")
                )]
            )
        );
        assert_eq!(
            (
                step(&p, "remove_run_values").cmd.as_str(),
                step(&p, "remove_run_values").args.clone()
            ),
            ("(run-values-remove)", vec![inst.clone()])
        );
        assert_eq!(
            (
                step(&p, "stop_apps").cmd.as_str(),
                step(&p, "stop_apps").args.clone()
            ),
            ("(stop-apps)", vec![inst.clone()])
        );
        assert_eq!(step(&p, "remove_install_dir").args, [inst]);
        assert_eq!(
            (
                step(&p, "remove_uninstall_entry").cmd.as_str(),
                step(&p, "stop_service").args.clone()
            ),
            (
                "(registry-delete)",
                vec!["stop".to_string(), "mcp-monitor".into()]
            )
        );
        let users = Path::new(&env("PUBLIC"))
            .parent()
            .unwrap()
            .display()
            .to_string();
        assert_eq!(
            step(&p, "remove_webview_profiles").args,
            [format!(r"{users}\*\AppData\Local\mcp-monitor")]
        );
        assert_eq!(step(&p, "remove_webview_profiles").cmd, "(remove-glob)");
        assert!(p.service_mode.is_none() && p.notes.is_empty());
    }

    #[test]
    fn dry_run_without_admin_notes_an_unreadable_install_state() {
        if crate::winutil::skip_when_elevated(
            "dry_run_without_admin_notes_an_unreadable_install_state",
            "an administrator can read the locked data root, so there is no note",
        ) {
            return;
        }
        let s = Scratch::new();
        let root = s.path().join("d");
        fs::create_dir_all(root.join("data")).unwrap();
        fs::write(
            root.join("data/install-state.json"),
            json!({"external_port": 9701}).to_string(),
        )
        .unwrap();
        lock_to_admins(&root);
        let p = build_uninstall_plan(&base(&s), &FakeHost::new());
        icacls(&root, &["/reset", "/T", "/C", "/Q"]);
        let p = p.unwrap();
        assert_eq!(p.notes.len(), 1, "{:?}", p.notes);
        assert!(
            p.notes[0].contains("관리자 권한으로 다시 실행하면 확인합니다"),
            "{}",
            p.notes[0]
        );
        assert_eq!(
            step(&p, "firewall_delete").args[4],
            "name=MCP Monitor (8701)"
        );
    }
}
