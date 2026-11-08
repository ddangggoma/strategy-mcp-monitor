//! Buffers events and delivers them in batches to `POST /api/agent/events` (Python
//! `mcp_agent.sender`).
//!
//! Rules (F10):
//! - At most `buffer_max` events are kept; the oldest go first and are counted in `dropped`.
//! - `flush` sends batches of `events_max`. `Unavailable` stops it and keeps the rest (and the
//!   unreported count) for the next try; `Rejected` / `Unverified` go up with the events kept; a
//!   batch the server refuses (`Unexpected`, e.g. 422) is dropped and counted, not retried forever.
//! - The count of events dropped and not yet reported rides on the next batch as `dropped` and is
//!   reported once (the server logs `system collector.dropped`). When no event is left to carry it
//!   (the last batch was refused; at exit) it is sent alone as `{"events": [], "dropped": n}`; a
//!   refused lone count is not resent.
//! - Window titles go only to a server that proved itself since the last outage: every post is
//!   `verified_only` (Plan 4 I1).

use super::client::{ClientError, ServerClient};
use super::coalesce::RawWinEvent;
use super::redact::redact_notice_tokens;
use super::runner::{Log, log_stderr};
use super::time::kst_iso;
use serde_json::{Map, Value, json};
use std::collections::VecDeque;
use std::sync::Arc;

pub const EVENTS_PATH: &str = "/api/agent/events";
/// The server's `WindowEventIn` limits, in characters.
pub const TITLE_MAX: usize = 512;
pub const EXE_MAX: usize = 260;
pub const BUFFER_MAX: usize = 2000;

#[derive(Clone, Debug, PartialEq)]
pub enum Item {
    Win(RawWinEvent),
    /// An `idle` / `active` transition from [`super::idle::IdleTracker`].
    Idle(Value),
}

fn cut(s: &str, limit: usize) -> String {
    s.chars().take(limit).collect()
}

/// A window event in the server's shape; the title has its notice tokens redacted, then both
/// texts are cut to the server's limits.
pub fn to_event(e: &RawWinEvent) -> Value {
    json!({
        "type": e.kind.as_str(),
        "at": kst_iso(e.at_ms),
        "pid": e.pid,
        "exe": e.exe.as_deref().map(|x| cut(x, EXE_MAX)),
        "title": cut(&redact_notice_tokens(&e.title), TITLE_MAX),
    })
}

/// The `POST /api/agent/events` body; `dropped` only when there are any.
pub fn to_payload(items: &[Item], dropped: u64) -> Value {
    let events: Vec<Value> = items
        .iter()
        .map(|i| match i {
            Item::Win(e) => to_event(e),
            Item::Idle(v) => v.clone(),
        })
        .collect();
    let mut body = Map::new();
    body.insert("events".into(), Value::Array(events));
    if dropped > 0 {
        body.insert("dropped".into(), json!(dropped));
    }
    Value::Object(body)
}

pub trait Poster: Send + Sync {
    fn post(
        &self,
        path: &str,
        body: Option<&Value>,
        verified_only: bool,
    ) -> Result<Option<Value>, ClientError>;
}

impl Poster for ServerClient {
    fn post(
        &self,
        path: &str,
        body: Option<&Value>,
        verified_only: bool,
    ) -> Result<Option<Value>, ClientError> {
        ServerClient::post(self, path, body, verified_only)
    }
}

pub struct EventSender {
    poster: Arc<dyn Poster>,
    events_max: usize,
    buffer_max: usize,
    buffer: VecDeque<Item>,
    dropped: u64,
    /// Of `dropped`, accepted by the server.
    reported: u64,
    log: Log,
}

impl EventSender {
    pub fn new(poster: Arc<dyn Poster>, events_max: usize, buffer_max: usize) -> EventSender {
        EventSender {
            poster,
            events_max: events_max.max(1),
            buffer_max: buffer_max.max(1),
            buffer: VecDeque::new(),
            dropped: 0,
            reported: 0,
            log: log_stderr(),
        }
    }

    pub fn with_log(mut self, log: Log) -> EventSender {
        self.log = log;
        self
    }

    pub fn pending(&self) -> usize {
        self.buffer.len()
    }

    /// Events lost so far (buffer overflow and refused batches).
    pub fn dropped(&self) -> u64 {
        self.dropped
    }

    pub fn add(&mut self, item: Item) {
        while self.buffer.len() >= self.buffer_max {
            self.buffer.pop_front();
            self.dropped += 1;
        }
        self.buffer.push_back(item);
    }

    /// Delivers what is buffered (see the module rules). Only `Rejected` / `Unverified` come back
    /// as an error.
    pub fn flush(&mut self) -> Result<(), ClientError> {
        while !self.buffer.is_empty() {
            let n = self.events_max.min(self.buffer.len());
            let batch: Vec<Item> = self.buffer.iter().take(n).cloned().collect();
            let unreported = self.dropped - self.reported;
            match self
                .poster
                .post(EVENTS_PATH, Some(&to_payload(&batch, unreported)), true)
            {
                Ok(_) => self.reported += unreported,
                Err(ClientError::Unavailable(_)) => return Ok(()),
                Err(ClientError::Unexpected(e)) => {
                    self.dropped += n as u64;
                    (self.log)(&format!("dropped {n} events: {e}"));
                }
                Err(e) => return Err(e),
            }
            self.buffer.drain(..n);
        }
        let unreported = self.dropped - self.reported;
        if unreported > 0 {
            match self
                .poster
                .post(EVENTS_PATH, Some(&to_payload(&[], unreported)), true)
            {
                Ok(_) => self.reported += unreported,
                Err(ClientError::Unavailable(_)) => {}
                Err(ClientError::Unexpected(e)) => {
                    (self.log)(&format!("dropped count not delivered: {e}"));
                    self.reported += unreported; // refused: not resent forever
                }
                Err(e) => return Err(e),
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::coalesce::{Kind, RawWinEvent};
    use crate::agent::idle::IdleTracker;
    use crate::agent::time::kst_iso;
    use serde_json::{Value, json};
    use std::sync::{Arc, Mutex};

    const AT: i64 = 1_793_768_397_000;

    struct Counting {
        outcomes: Mutex<Vec<Option<ClientError>>>,
        bodies: Mutex<Vec<Value>>,
        verified_only: Mutex<Vec<bool>>,
    }
    impl Counting {
        fn new(outcomes: Vec<Option<ClientError>>) -> Arc<Counting> {
            Arc::new(Counting {
                outcomes: Mutex::new(outcomes),
                bodies: Mutex::new(vec![]),
                verified_only: Mutex::new(vec![]),
            })
        }
        fn bodies(&self) -> Vec<Value> {
            self.bodies.lock().unwrap().clone()
        }
    }
    impl Poster for Counting {
        fn post(
            &self,
            _path: &str,
            body: Option<&Value>,
            verified_only: bool,
        ) -> Result<Option<Value>, ClientError> {
            self.bodies.lock().unwrap().push(body.cloned().unwrap());
            self.verified_only.lock().unwrap().push(verified_only);
            let mut o = self.outcomes.lock().unwrap();
            match if o.is_empty() { None } else { o.remove(0) } {
                Some(e) => Err(e),
                None => Ok(None),
            }
        }
    }
    fn idle(n: u64) -> Item {
        Item::Idle(json!({"type": "idle", "at": "2026-11-04T14:00:00.000+09:00", "idle_sec": n}))
    }
    fn idle_json(n: u64) -> Value {
        json!({"type": "idle", "at": "2026-11-04T14:00:00.000+09:00", "idle_sec": n})
    }
    fn down() -> Option<ClientError> {
        Some(ClientError::Unavailable("down".into()))
    }
    fn refused() -> Option<ClientError> {
        Some(ClientError::Unexpected(
            "POST /api/agent/events: unexpected status 422".into(),
        ))
    }
    fn logs() -> (Log, Arc<Mutex<Vec<String>>>) {
        let lines = Arc::new(Mutex::new(Vec::new()));
        let l = lines.clone();
        (
            Arc::new(move |s: &str| l.lock().unwrap().push(s.to_string())),
            lines,
        )
    }

    #[test]
    fn payload_matches_the_server_fixture() {
        let fixture: Value = serde_json::from_str(
            &std::fs::read_to_string(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/../server/tests/fixtures/agent-events.json"
            ))
            .unwrap(),
        )
        .unwrap();
        let exe = Some(r"C:\Windows\System32\notepad.exe".to_string());
        let ev = |t: f64, kind, title: &str| {
            Item::Win(RawWinEvent {
                t,
                kind,
                hwnd: 1,
                pid: 4321,
                exe: exe.clone(),
                title: title.into(),
                at_ms: AT + (t * 1000.0) as i64,
            })
        };
        let items = [
            ev(0.0, Kind::Foreground, "메모 - 메모장"),
            ev(1.5, Kind::Title, "*메모 - 메모장"),
            ev(2.0, Kind::Minimize, "*메모 - 메모장"),
            Item::Idle(
                json!({"type": "idle", "at": "2026-11-04T14:00:00.000+09:00", "idle_sec": 300}),
            ),
        ];
        assert_eq!(to_payload(&items, 0), fixture);
    }

    #[test]
    fn to_event_fits_the_server_limits_and_redacts_notice_tokens() {
        let e = RawWinEvent {
            t: 0.0,
            kind: Kind::Title,
            hwnd: 1,
            pid: 7,
            exe: Some("x".repeat(300)),
            title: format!("a?b{}", "t".repeat(600)),
            at_ms: AT,
        };
        let v = to_event(&e);
        assert_eq!(
            (v["type"].as_str(), v["pid"].as_u64(), v["at"].as_str()),
            (
                Some("title"),
                Some(7),
                Some("2026-11-04T13:59:57.000+09:00")
            )
        );
        assert_eq!(
            (
                v["title"].as_str().unwrap().chars().count(),
                v["exe"].as_str().unwrap().chars().count()
            ),
            (512, 260)
        );
        let n = RawWinEvent {
            title: "MCP Monitor — http://127.0.0.1:8700/notice#d=3&t=Xy-9_aBcDeF".into(),
            exe: None,
            ..e
        };
        let v = to_event(&n);
        assert_eq!(
            v["title"],
            "MCP Monitor — http://127.0.0.1:8700/notice#d=3&t=<redacted>"
        );
        assert!(v["exe"].is_null());
        assert_eq!(kst_iso(1_793_804_400_123), "2026-11-05T00:00:00.123+09:00");
    }

    #[test]
    fn idle_transitions_report_ints_in_kst() {
        let mut i = IdleTracker::new(300.0);
        assert!(i.update(10.0, AT).is_none() && i.update(299.0, AT).is_none());
        assert_eq!(
            i.update(300.9, AT),
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
    fn sender_batches_and_buffers_while_unavailable() {
        let c = Counting::new(vec![down()]);
        let mut s = EventSender::new(c.clone(), 2, 3);
        for n in 0..4 {
            s.add(idle(n));
        }
        s.flush().unwrap();
        assert_eq!((s.pending(), s.dropped()), (3, 1));
        s.flush().unwrap();
        let sent: Vec<Vec<u64>> = c.bodies()[1..]
            .iter()
            .map(|b| {
                b["events"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|e| e["idle_sec"].as_u64().unwrap())
                    .collect()
            })
            .collect();
        assert_eq!(sent, [vec![1, 2], vec![3]]);
        assert_eq!(s.pending(), 0);
        assert!(c.verified_only.lock().unwrap().iter().all(|v| *v)); // window titles only to a proven server
    }

    #[test]
    fn overflow_drops_ride_on_the_next_batch_once() {
        let c = Counting::new(vec![]);
        let mut s = EventSender::new(c.clone(), 2, 2);
        for n in 0..5 {
            s.add(idle(n));
        }
        s.flush().unwrap();
        assert_eq!(
            c.bodies()
                .iter()
                .map(|b| b.get("dropped").and_then(Value::as_u64))
                .collect::<Vec<_>>(),
            [Some(3)]
        );
        s.add(idle(9));
        s.flush().unwrap();
        assert!(c.bodies()[1].get("dropped").is_none());
    }

    #[test]
    fn a_refused_batch_is_counted_in_the_next_report_and_a_lone_count_is_sent_once() {
        let c = Counting::new(vec![refused()]);
        let mut s = EventSender::new(c.clone(), 5, 2000);
        s.add(idle(0));
        s.flush().unwrap();
        assert_eq!(
            c.bodies(),
            [
                json!({"events": [{"type": "idle", "at": "2026-11-04T14:00:00.000+09:00", "idle_sec": 0}]}),
                json!({"events": [], "dropped": 1})
            ]
        );
        s.flush().unwrap();
        assert_eq!(c.bodies().len(), 2);
    }

    #[test]
    fn an_empty_report_waits_while_the_server_is_unavailable() {
        let c = Counting::new(vec![refused(), down()]);
        let mut s = EventSender::new(c.clone(), 5, 2000);
        s.add(idle(0));
        s.flush().unwrap();
        s.flush().unwrap();
        assert_eq!(c.bodies().len(), 3);
        assert_eq!(c.bodies()[2], json!({"events": [], "dropped": 1}));
        s.flush().unwrap();
        assert_eq!(c.bodies().len(), 3);
    }

    #[test]
    fn a_rejected_token_goes_up_and_the_events_stay() {
        let c = Counting::new(vec![Some(ClientError::Rejected("401".into()))]);
        let mut s = EventSender::new(c, 5, 2000);
        s.add(idle(0));
        assert!(s.flush().unwrap_err().is_rejected());
        assert_eq!(s.pending(), 1);
    }

    // --- beyond the plan: the rest of the Python sender tests (F10) ----------------------------

    #[test]
    fn a_batch_the_server_refuses_is_dropped_not_retried_and_a_refused_lone_count_is_not_resent() {
        let c = Counting::new(vec![refused(), refused(), refused()]);
        let (log, lines) = logs();
        let mut s = EventSender::new(c.clone(), 2, 2000).with_log(log);
        for n in 0..3 {
            s.add(idle(n));
        }
        s.flush().unwrap();
        // two refused batches, then one try to report the count alone (refused too: not resent)
        assert_eq!((c.bodies().len(), s.pending(), s.dropped()), (3, 0, 3));
        assert_eq!(c.bodies()[2], json!({"events": [], "dropped": 3}));
        let lines = lines.lock().unwrap().clone();
        assert_eq!(
            lines,
            [
                "dropped 2 events: POST /api/agent/events: unexpected status 422",
                "dropped 1 events: POST /api/agent/events: unexpected status 422",
                "dropped count not delivered: POST /api/agent/events: unexpected status 422",
            ]
        );
        s.flush().unwrap();
        assert_eq!(c.bodies().len(), 3);
    }

    #[test]
    fn the_dropped_count_is_carried_across_an_outage() {
        let c = Counting::new(vec![down()]);
        let mut s = EventSender::new(c.clone(), 5, 1);
        s.add(idle(0));
        s.add(idle(1));
        s.flush().unwrap();
        assert_eq!(c.bodies()[0]["dropped"], 1);
        s.flush().unwrap();
        assert_eq!(
            c.bodies()[1],
            json!({"events": [idle_json(1)], "dropped": 1})
        );
        s.flush().unwrap();
        assert_eq!(c.bodies().len(), 2);
    }

    #[test]
    fn a_refused_batch_s_count_rides_on_the_next_batch() {
        let c = Counting::new(vec![refused()]);
        let (log, _) = logs();
        let mut s = EventSender::new(c.clone(), 1, 2000).with_log(log);
        s.add(idle(0));
        s.add(idle(1));
        s.flush().unwrap();
        assert_eq!(
            c.bodies()
                .iter()
                .map(|b| b.get("dropped").and_then(Value::as_u64))
                .collect::<Vec<_>>(),
            [None, Some(1)]
        );
        assert_eq!(s.dropped(), 1);
        s.add(idle(2));
        s.flush().unwrap();
        assert!(c.bodies()[2].get("dropped").is_none());
    }

    #[test]
    fn a_rejected_lone_count_goes_up_and_is_sent_again_later() {
        let c = Counting::new(vec![
            refused(),
            Some(ClientError::Unverified("bad proof".into())),
        ]);
        let (log, _) = logs();
        let mut s = EventSender::new(c.clone(), 5, 2000).with_log(log);
        s.add(idle(0));
        assert!(s.flush().unwrap_err().is_rejected());
        s.flush().unwrap();
        assert_eq!(c.bodies()[2], json!({"events": [], "dropped": 1}));
    }

    #[test]
    fn window_events_are_posted_in_the_server_shape_once() {
        let c = Counting::new(vec![]);
        let mut s = EventSender::new(c.clone(), 200, BUFFER_MAX);
        s.add(Item::Win(RawWinEvent {
            t: 0.0,
            kind: Kind::Foreground,
            hwnd: 1,
            pid: 10,
            exe: Some("a.exe".into()),
            title: "A".into(),
            at_ms: AT,
        }));
        s.flush().unwrap();
        s.flush().unwrap();
        assert_eq!(
            c.bodies(),
            [
                json!({"events": [{"type": "foreground", "at": "2026-11-04T13:59:57.000+09:00", "pid": 10, "exe": "a.exe", "title": "A"}]})
            ]
        );
    }

    #[test]
    fn payload_has_no_dropped_key_when_nothing_was_dropped() {
        assert_eq!(to_payload(&[idle(1)], 0), json!({"events": [idle_json(1)]}));
        assert_eq!(
            to_payload(&[idle(1)], 4),
            json!({"events": [idle_json(1)], "dropped": 4})
        );
    }

    #[test]
    fn texts_are_cut_by_characters_not_bytes() {
        let e = RawWinEvent {
            t: 0.0,
            kind: Kind::Restore,
            hwnd: 1,
            pid: 7,
            exe: Some("가".repeat(300)),
            title: "한".repeat(600),
            at_ms: AT,
        };
        let v = to_event(&e);
        assert_eq!(v["title"].as_str().unwrap(), "한".repeat(512));
        assert_eq!(v["exe"].as_str().unwrap(), "가".repeat(260));
    }
}
