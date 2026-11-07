#![allow(dead_code)]
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

pub fn exe() -> Command {
    Command::new(env!("CARGO_BIN_EXE_mcp-monitor"))
}

pub fn run(args: &[&str]) -> Output {
    exe().args(args).output().unwrap()
}

/// %LOCALAPPDATA%\mcp-monitor-install-tests\<random>: parents only this account, SYSTEM and Administrators can change.
pub struct Scratch(pub PathBuf);
impl Scratch {
    pub fn new() -> Scratch {
        // Tests that use a scratch folder may change files and ACLs: never from an elevated shell.
        mcp_monitor::winutil::assert_not_elevated();
        let mut b = [0u8; 6];
        getrandom::fill(&mut b).unwrap();
        let p = PathBuf::from(std::env::var("LOCALAPPDATA").unwrap())
            .join("mcp-monitor-install-tests")
            .join(hex::encode(b));
        std::fs::create_dir_all(&p).unwrap();
        Scratch(p)
    }
    pub fn join(&self, p: &str) -> PathBuf {
        self.0.join(p)
    }
    pub fn path(&self) -> &Path {
        &self.0
    }
}
impl Drop for Scratch {
    fn drop(&mut self) {
        if std::fs::remove_dir_all(&self.0).is_err() {
            let icacls = mcp_monitor::winutil::system_tool("icacls.exe");
            let _ = Command::new(icacls)
                .arg(&self.0)
                .args(["/reset", "/T", "/C", "/Q"])
                .output();
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
}
