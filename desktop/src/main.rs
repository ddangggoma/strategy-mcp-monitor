#![cfg_attr(not(test), windows_subsystem = "windows")]

fn main() {
    mcp_monitor::winutil::harden_dll_search();
    mcp_monitor::winutil::attach_parent_console();
    std::process::exit(mcp_monitor::run(std::env::args_os().skip(1).collect()));
}
