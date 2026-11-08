//! Clocks for the window events: wall time as the server's KST ISO strings (Python
//! `sender.iso`: `astimezone(KST).isoformat(timespec="milliseconds")`) and one process-wide
//! monotonic clock shared by the hook callback (event `t`) and the pump (`drain(now)`).

use std::sync::OnceLock;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

/// `at_ms` (milliseconds since 1970-01-01 UTC) as `YYYY-MM-DDTHH:MM:SS.mmm+09:00`.
pub fn kst_iso(at_ms: i64) -> String {
    let at = time::OffsetDateTime::from_unix_timestamp_nanos(i128::from(at_ms) * 1_000_000)
        .unwrap_or(time::OffsetDateTime::UNIX_EPOCH)
        .to_offset(time::macros::offset!(+9));
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:03}+09:00",
        at.year(),
        u8::from(at.month()),
        at.day(),
        at.hour(),
        at.minute(),
        at.second(),
        at.millisecond()
    )
}

/// Milliseconds since 1970-01-01 UTC (0 if the clock is before it).
pub fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| i64::try_from(d.as_millis()).unwrap_or(i64::MAX))
}

/// Seconds on a monotonic clock that starts at the first call in this process.
pub fn monotonic() -> f64 {
    static START: OnceLock<Instant> = OnceLock::new();
    START.get_or_init(Instant::now).elapsed().as_secs_f64()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn kst_iso_matches_the_python_agent() {
        assert_eq!(kst_iso(1_793_768_397_000), "2026-11-04T13:59:57.000+09:00");
        assert_eq!(kst_iso(1_793_804_400_123), "2026-11-05T00:00:00.123+09:00");
        assert_eq!(kst_iso(0), "1970-01-01T09:00:00.000+09:00");
        assert_eq!(kst_iso(-1), "1970-01-01T08:59:59.999+09:00");
    }

    #[test]
    fn clocks_move_forward() {
        let (a, wall) = (monotonic(), now_ms());
        assert!(monotonic() >= a);
        assert!(wall > 1_793_000_000_000 - 400 * 86_400_000, "{wall}");
    }
}
