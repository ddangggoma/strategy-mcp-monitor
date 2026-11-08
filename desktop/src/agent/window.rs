//! The `--dialog print` notice window (Python `dialog.PrintWindow`): instead of showing anything it
//! appends `OPEN <id> <url>` / `CLOSE <id>` lines (UTF-8, `\n`) to the `--url-file`, for E2E and
//! integration tests.

use super::runner::NoticeWindow;
use std::io::Write;
use std::path::PathBuf;

pub struct PrintWindow {
    file: PathBuf,
    open: Option<i64>,
}

impl PrintWindow {
    /// Nothing is written (or created) until the first `open`.
    pub fn new(url_file: PathBuf) -> PrintWindow {
        PrintWindow {
            file: url_file,
            open: None,
        }
    }

    fn write(&self, line: &str) -> std::io::Result<()> {
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.file)?;
        f.write_all(format!("{line}\n").as_bytes())
    }
}

impl NoticeWindow for PrintWindow {
    fn open(&mut self, url: &str, display_id: i64) -> Result<(), String> {
        self.write(&format!("OPEN {display_id} {url}"))
            .map_err(|e| format!("{}: {e}", self.file.display()))?;
        self.open = Some(display_id);
        Ok(())
    }

    fn close(&mut self) {
        if let Some(id) = self.open.take() {
            let _ = self.write(&format!("CLOSE {id}"));
        }
    }

    fn closed_by_user(&mut self) -> bool {
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn writes_open_and_close_lines_only_for_an_open_window() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("agent-2.url");
        let mut w = PrintWindow::new(file.clone());
        w.close();
        assert!(!file.exists());
        w.open("http://127.0.0.1:8700/notice#d=7&t=메모", 7)
            .unwrap();
        w.close();
        w.close();
        w.open("http://127.0.0.1:8700/notice#d=8&t=b", 8).unwrap();
        assert!(!w.closed_by_user());
        assert_eq!(
            std::fs::read(&file).unwrap(),
            "OPEN 7 http://127.0.0.1:8700/notice#d=7&t=메모\nCLOSE 7\nOPEN 8 http://127.0.0.1:8700/notice#d=8&t=b\n"
                .as_bytes()
        );
    }

    #[test]
    fn a_file_that_cannot_be_written_is_an_open_error() {
        let dir = tempfile::tempdir().unwrap();
        let mut w = PrintWindow::new(dir.path().join("missing").join("agent.url"));
        assert!(w.open("http://127.0.0.1:8700/notice#d=7", 7).is_err());
        w.close();
    }
}
