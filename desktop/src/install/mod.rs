//! Installer building blocks: the path and ACL guards ported from Plan 5's `install.ps1`,
//! `uninstall.ps1` and `audit-policy.ps1` with the same rules (Y18, Task 5), and the
//! "plan (step list) → run" path of the installer modes (Task 6+).

pub mod acl;
pub mod audit;
pub mod exec;
pub mod host;
pub mod install_plan;
pub mod paths;
pub mod plan;
pub mod procs;
pub mod registry;
pub mod shortcut;
pub mod stage;
#[cfg(test)]
pub mod testutil;
