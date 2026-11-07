//! Turns the session's idle seconds (`GetLastInputInfo`) into `idle` / `active` transitions
//! (Python `mcp_agent.idle`).

use super::time::kst_iso;
use serde_json::{Value, json};

pub struct IdleTracker {
    threshold: f64,
    idle: bool,
    last: f64,
}

impl IdleTracker {
    pub fn new(threshold_sec: f64) -> IdleTracker {
        IdleTracker {
            threshold: threshold_sec,
            idle: false,
            last: 0.0,
        }
    }

    /// `{"type": "idle"|"active", "at", "idle_sec": <whole seconds>}` when the state changes.
    pub fn update(&mut self, idle_sec: f64, at_ms: i64) -> Option<Value> {
        if !self.idle {
            if idle_sec >= self.threshold {
                self.idle = true;
                self.last = idle_sec;
                return Some(
                    json!({"type": "idle", "at": kst_iso(at_ms), "idle_sec": idle_sec as i64}),
                );
            }
            return None;
        }
        if idle_sec < self.last {
            // input arrived since the last sample
            self.idle = false;
            return Some(
                json!({"type": "active", "at": kst_iso(at_ms), "idle_sec": self.last as i64}),
            );
        }
        self.last = idle_sec;
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const AT: i64 = 1_793_768_397_000;

    #[test]
    fn idle_transitions_with_the_python_numbers() {
        let mut i = IdleTracker::new(300.0);
        assert!(i.update(10.0, AT).is_none() && i.update(299.0, AT).is_none());
        assert_eq!(
            i.update(300.0, AT),
            Some(json!({"type": "idle", "at": "2026-11-04T13:59:57.000+09:00", "idle_sec": 300}))
        );
        assert!(i.update(420.0, AT).is_none());
        assert_eq!(
            i.update(2.0, AT),
            Some(json!({"type": "active", "at": "2026-11-04T13:59:57.000+09:00", "idle_sec": 420}))
        );
        assert!(i.update(5.0, AT).is_none());
    }

    #[test]
    fn idle_accepts_float_seconds_and_reports_ints_in_kst() {
        let mut i = IdleTracker::new(300.0);
        let at = 1_793_804_400_123; // 2026-11-04T15:00:00.123Z
        assert_eq!(
            i.update(300.9, at),
            Some(json!({"type": "idle", "at": "2026-11-05T00:00:00.123+09:00", "idle_sec": 300}))
        );
        assert!(i.update(310.7, at).is_none());
        assert_eq!(
            i.update(0.2, at),
            Some(json!({"type": "active", "at": "2026-11-05T00:00:00.123+09:00", "idle_sec": 310}))
        );
    }
}
