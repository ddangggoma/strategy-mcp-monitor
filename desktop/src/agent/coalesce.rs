//! Debounces raw WinEvents into what the monitor logs as `activity.window` lines (Python
//! `mcp_agent.coalesce`, same rules and numbers).
//!
//! Alt-Tab bursts keep only the last foreground window, a busy window's title changes merge into
//! its last title, and repeats of what was already sent are dropped. Times `t` are monotonic
//! seconds ([`super::time::monotonic`]).

use std::collections::VecDeque;

/// Windows whose last sent title is remembered.
pub const TITLE_MEMORY: usize = 256;
pub const FG_MERGE_SEC: f64 = 0.3;
pub const TITLE_MERGE_SEC: f64 = 1.0;
pub const DUP_SEC: f64 = 0.3;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Kind {
    Foreground,
    Minimize,
    Restore,
    Title,
}

impl Kind {
    /// The event `type` the server expects.
    pub fn as_str(self) -> &'static str {
        match self {
            Kind::Foreground => "foreground",
            Kind::Minimize => "minimize",
            Kind::Restore => "restore",
            Kind::Title => "title",
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct RawWinEvent {
    /// Monotonic seconds.
    pub t: f64,
    pub kind: Kind,
    pub hwnd: isize,
    pub pid: u32,
    pub exe: Option<String>,
    pub title: String,
    /// Wall time, milliseconds since 1970-01-01 UTC.
    pub at_ms: i64,
}

/// Not thread-safe: the pump holds a lock around `add` and `drain`.
pub struct WindowEventCoalescer {
    fg_merge: f64,
    title_merge: f64,
    dup: f64,
    foregrounds: Vec<RawWinEvent>,
    /// Pending title per window, in first-insertion order (a newer title keeps the slot, like a
    /// Python dict assignment).
    titles: Vec<RawWinEvent>,
    others: Vec<RawWinEvent>,
    /// (hwnd, minimize|restore) → last `t`.
    seen: Vec<((isize, Kind), f64)>,
    /// The foreground window as of the last `add`.
    current: Option<isize>,
    sent_fg: Option<(isize, String)>,
    /// Least recently sent first.
    sent_titles: VecDeque<(isize, String)>,
}

impl Default for WindowEventCoalescer {
    fn default() -> Self {
        WindowEventCoalescer::new()
    }
}

impl WindowEventCoalescer {
    pub fn new() -> WindowEventCoalescer {
        WindowEventCoalescer::with(FG_MERGE_SEC, TITLE_MERGE_SEC, DUP_SEC)
    }

    pub fn with(fg_merge_sec: f64, title_merge_sec: f64, dup_sec: f64) -> WindowEventCoalescer {
        WindowEventCoalescer {
            fg_merge: fg_merge_sec,
            title_merge: title_merge_sec,
            dup: dup_sec,
            foregrounds: Vec::new(),
            titles: Vec::new(),
            others: Vec::new(),
            seen: Vec::new(),
            current: None,
            sent_fg: None,
            sent_titles: VecDeque::new(),
        }
    }

    pub fn add(&mut self, e: RawWinEvent) {
        match e.kind {
            Kind::Foreground => {
                self.current = Some(e.hwnd);
                match self.foregrounds.last_mut() {
                    Some(last) if e.t - last.t < self.fg_merge => *last = e,
                    _ => self.foregrounds.push(e),
                }
            }
            Kind::Title => {
                if Some(e.hwnd) == self.current {
                    match self.titles.iter_mut().find(|p| p.hwnd == e.hwnd) {
                        Some(pending) => *pending = e,
                        None => self.titles.push(e),
                    }
                }
            }
            Kind::Minimize | Kind::Restore => {
                let key = (e.hwnd, e.kind);
                let last = match self.seen.iter_mut().find(|(k, _)| *k == key) {
                    Some((_, t)) => Some(std::mem::replace(t, e.t)),
                    None => {
                        self.seen.push((key, e.t));
                        None
                    }
                };
                if last.is_none_or(|last| e.t - last >= self.dup) {
                    self.others.push(e);
                }
            }
        }
    }

    /// The events that are ready at monotonic `now`, oldest first, without repeats of what was
    /// already sent.
    pub fn drain(&mut self, now: f64) -> Vec<RawWinEvent> {
        let fg_merge = self.fg_merge;
        let (mut ready, waiting): (Vec<_>, Vec<_>) = std::mem::take(&mut self.foregrounds)
            .into_iter()
            .partition(|e| e.t + fg_merge <= now);
        self.foregrounds = waiting;
        let title_merge = self.title_merge;
        let (titles, waiting): (Vec<_>, Vec<_>) = std::mem::take(&mut self.titles)
            .into_iter()
            .partition(|e| e.t + title_merge <= now);
        self.titles = waiting;
        ready.extend(titles);
        ready.append(&mut self.others);
        let dup = self.dup;
        self.seen.retain(|(_, t)| t + dup > now);

        ready.sort_by(|a, b| a.t.total_cmp(&b.t)); // stable, like Python's sorted
        let mut out = Vec::with_capacity(ready.len());
        for e in ready {
            match e.kind {
                Kind::Foreground => {
                    if self
                        .sent_fg
                        .as_ref()
                        .is_some_and(|(h, t)| *h == e.hwnd && *t == e.title)
                    {
                        continue;
                    }
                    self.sent_fg = Some((e.hwnd, e.title.clone()));
                    self.remember_title(e.hwnd, &e.title);
                }
                Kind::Title => {
                    if self
                        .sent_titles
                        .iter()
                        .any(|(h, t)| *h == e.hwnd && *t == e.title)
                    {
                        continue;
                    }
                    self.remember_title(e.hwnd, &e.title);
                }
                Kind::Minimize | Kind::Restore => {}
            }
            out.push(e);
        }
        out
    }

    fn remember_title(&mut self, hwnd: isize, title: &str) {
        self.sent_titles.retain(|(h, _)| *h != hwnd);
        self.sent_titles.push_back((hwnd, title.to_string()));
        while self.sent_titles.len() > TITLE_MEMORY {
            self.sent_titles.pop_front();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const AT: i64 = 1_793_768_397_000; // 2026-11-04T04:59:57Z = 13:59:57 KST

    fn raw(t: f64, kind: Kind, hwnd: isize, title: &str) -> RawWinEvent {
        RawWinEvent {
            t,
            kind,
            hwnd,
            pid: 10,
            exe: Some("a.exe".into()),
            title: title.into(),
            at_ms: AT + (t * 1000.0) as i64,
        }
    }
    fn fg(t: f64, hwnd: isize, title: &str) -> RawWinEvent {
        raw(t, Kind::Foreground, hwnd, title)
    }
    fn titles(v: &[RawWinEvent]) -> Vec<&str> {
        v.iter().map(|e| e.title.as_str()).collect()
    }

    #[test]
    fn foreground_burst_keeps_the_last() {
        let mut c = WindowEventCoalescer::new();
        c.add(fg(0.0, 1, "A"));
        c.add(fg(0.1, 2, "B"));
        c.add(fg(0.2, 3, "C"));
        assert!(c.drain(0.4).is_empty());
        assert_eq!(titles(&c.drain(0.5)), ["C"]);
    }

    #[test]
    fn refocusing_the_same_window_and_title_is_dropped() {
        let mut c = WindowEventCoalescer::new();
        c.add(fg(0.0, 1, "A"));
        assert_eq!(c.drain(1.0).len(), 1);
        c.add(fg(2.0, 1, "A"));
        assert!(c.drain(3.0).is_empty());
        c.add(fg(4.0, 1, "A2"));
        assert_eq!(titles(&c.drain(5.0)), ["A2"]);
    }

    #[test]
    fn title_changes_merge_for_the_foreground_window_only() {
        let mut c = WindowEventCoalescer::new();
        c.add(fg(0.0, 1, "doc"));
        c.drain(1.0);
        for (i, t) in ["doc*", "doc**", "doc***"].iter().enumerate() {
            c.add(raw(1.0 + i as f64 * 0.2, Kind::Title, 1, t));
        }
        c.add(raw(1.1, Kind::Title, 9, "background"));
        assert!(c.drain(2.3).is_empty());
        let out = c.drain(2.4);
        assert_eq!(
            out.iter()
                .map(|e| (e.kind, e.title.as_str()))
                .collect::<Vec<_>>(),
            [(Kind::Title, "doc***")]
        );
    }

    #[test]
    fn minimize_restore_pass_through_with_dedupe_and_order() {
        let mut c = WindowEventCoalescer::new();
        c.add(fg(0.0, 1, "A"));
        c.add(raw(0.5, Kind::Minimize, 1, "A"));
        c.add(raw(0.6, Kind::Minimize, 1, "A"));
        c.add(raw(0.9, Kind::Restore, 1, "A"));
        assert_eq!(
            c.drain(1.0).iter().map(|e| e.kind).collect::<Vec<_>>(),
            [Kind::Foreground, Kind::Minimize, Kind::Restore]
        );
    }

    #[test]
    fn foreground_switches_further_apart_than_the_merge_window_are_all_kept() {
        let mut c = WindowEventCoalescer::new();
        c.add(fg(0.0, 1, "A"));
        c.add(fg(0.5, 2, "B"));
        assert_eq!(titles(&c.drain(0.6)), ["A"]);
        assert_eq!(titles(&c.drain(0.8)), ["B"]);
    }

    #[test]
    fn a_title_equal_to_the_last_one_sent_for_that_window_is_dropped() {
        let mut c = WindowEventCoalescer::new();
        c.add(fg(0.0, 1, "doc"));
        c.drain(1.0);
        c.add(raw(2.0, Kind::Title, 1, "doc"));
        assert!(c.drain(4.0).is_empty());
        c.add(raw(5.0, Kind::Title, 1, "doc*"));
        c.add(raw(5.5, Kind::Title, 1, "doc"));
        assert!(c.drain(7.0).is_empty());
    }

    #[test]
    fn title_of_a_window_that_lost_the_foreground_is_dropped() {
        let mut c = WindowEventCoalescer::new();
        c.add(fg(0.0, 1, "one"));
        c.add(fg(1.0, 2, "two"));
        c.add(raw(1.1, Kind::Title, 1, "one*"));
        assert_eq!(
            c.drain(5.0)
                .iter()
                .map(|e| (e.kind, e.title.as_str()))
                .collect::<Vec<_>>(),
            [(Kind::Foreground, "one"), (Kind::Foreground, "two")]
        );
    }

    #[test]
    fn minimize_dedupe_is_per_window_and_expires() {
        let mut c = WindowEventCoalescer::new();
        c.add(raw(0.0, Kind::Minimize, 1, ""));
        c.add(raw(0.1, Kind::Minimize, 2, ""));
        c.add(raw(0.2, Kind::Restore, 1, ""));
        c.add(raw(0.4, Kind::Minimize, 1, ""));
        assert_eq!(
            c.drain(0.4)
                .iter()
                .map(|e| (e.kind, e.hwnd))
                .collect::<Vec<_>>(),
            [
                (Kind::Minimize, 1),
                (Kind::Minimize, 2),
                (Kind::Restore, 1),
                (Kind::Minimize, 1)
            ]
        );
    }

    // --- beyond the plan ---------------------------------------------------------------------

    #[test]
    fn kinds_are_the_server_types() {
        assert_eq!(
            [Kind::Foreground, Kind::Minimize, Kind::Restore, Kind::Title].map(Kind::as_str),
            ["foreground", "minimize", "restore", "title"]
        );
    }

    #[test]
    fn the_title_memory_forgets_the_least_recently_sent_window() {
        let mut c = WindowEventCoalescer::new();
        for hwnd in 0..=TITLE_MEMORY as isize {
            c.add(fg(hwnd as f64, hwnd, "same"));
        }
        assert_eq!(c.drain(1000.0).len(), TITLE_MEMORY + 1);
        // A title of window w without w's own foreground event being sent: w's foreground is
        // merged away by the next window's within 0.3 s.
        let title_alone = |c: &mut WindowEventCoalescer, t: f64, w: isize, other: isize| {
            c.add(fg(t, w, "z"));
            c.add(raw(t + 0.05, Kind::Title, w, "same"));
            c.add(fg(t + 0.1, other, &format!("other{other}")));
            c.drain(t + 10.0)
        };
        // window 0 was forgotten (257 windows were sent) ...
        assert_eq!(
            titles(&title_alone(&mut c, 2000.0, 0, 500)),
            ["same", "other500"]
        );
        // ... window 256 is still remembered with that title
        assert_eq!(titles(&title_alone(&mut c, 3000.0, 256, 501)), ["other501"]);
    }

    #[test]
    fn custom_merge_windows_are_used() {
        let mut c = WindowEventCoalescer::with(1.0, 2.0, 1.0);
        c.add(fg(0.0, 1, "A"));
        c.add(fg(0.9, 2, "B"));
        assert!(c.drain(1.8).is_empty());
        assert_eq!(titles(&c.drain(1.95)), ["B"]);
        c.add(raw(2.0, Kind::Minimize, 2, "B"));
        c.add(raw(2.9, Kind::Minimize, 2, "B"));
        assert_eq!(c.drain(3.0).len(), 1);
    }
}
