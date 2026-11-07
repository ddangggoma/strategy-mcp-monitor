#![cfg_attr(not(test), windows_subsystem = "windows")]

fn main() {
    std::process::exit(mcp_monitor::run(std::env::args_os().skip(1).collect()))
}
