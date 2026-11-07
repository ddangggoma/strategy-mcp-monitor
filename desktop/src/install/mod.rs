//! Installer building blocks (Task 5+): the path and ACL guards ported from Plan 5's
//! `install.ps1`, `uninstall.ps1` and `audit-policy.ps1` with the same rules (Y18).

pub mod acl;
pub mod paths;
#[cfg(test)]
pub mod testutil;
