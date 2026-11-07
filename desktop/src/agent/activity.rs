//! Window hooks + event pump, started by the runner's `on_hello` when the server wants window
//! events (Python `__main__.WindowActivity`).
//!
//! Lenient HELLO numbers, as Python's `int()` / `float()` read them (F29):
//! - `events_max`: an integer, a number (cut to an integer), a decimal integer string (spaces
//!   around allowed) or a boolean (1/0); anything else, or not above 0 → 200.
//! - `idle_threshold_sec`: a number, a numeric string or a boolean; anything else, not finite or
//!   not above 0 → 300.
//! - `window_events`: [`super::runner::wants_window_events`].

use super::client::ServerClient;
use super::coalesce::WindowEventCoalescer;
use super::hooks::{HookHandler, HookThread, OnEvent, RealWin};
use super::idle::IdleTracker;
use super::pump::{EventPump, IDLE_EVERY_SEC, IdleSource};
use super::runner::{Log, idle_seconds, log_stderr, wants_window_events};
use super::sender::{BUFFER_MAX, EventSender};
use serde_json::Value;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

pub const DEFAULT_EVENTS_MAX: usize = 200;
pub const DEFAULT_IDLE_THRESHOLD_SEC: f64 = 300.0;
/// How long `stop` waits for the pump thread (busy with a post).
pub const PUMP_JOIN_SEC: u64 = 5;

/// Makes the hook thread from the callback that feeds the pump.
pub type HookFactory = Box<dyn FnOnce(OnEvent) -> HookThread + Send>;

/// HELLO `events_max` (Python `int(...)`), or `None`.
fn int_of(v: &Value) -> Option<i64> {
    match v {
        Value::Number(n) => n
            .as_i64()
            .or_else(|| n.as_f64().filter(|f| f.is_finite()).map(|f| f as i64)),
        Value::String(s) => s.trim().parse::<i64>().ok(),
        Value::Bool(b) => Some(i64::from(*b)),
        _ => None,
    }
}

/// HELLO `idle_threshold_sec` (Python `float(...)`), or `None`.
fn float_of(v: &Value) -> Option<f64> {
    match v {
        Value::Number(n) => n.as_f64(),
        Value::String(s) => s.trim().parse::<f64>().ok(),
        Value::Bool(b) => Some(if *b { 1.0 } else { 0.0 }),
        _ => None,
    }
}

pub fn events_max(hello: &Value) -> usize {
    match hello.get("events_max").and_then(int_of) {
        Some(n) if n > 0 => usize::try_from(n).unwrap_or(usize::MAX),
        _ => DEFAULT_EVENTS_MAX,
    }
}

pub fn idle_threshold_sec(hello: &Value) -> f64 {
    match hello.get("idle_threshold_sec").and_then(float_of) {
        Some(s) if s.is_finite() && s > 0.0 => s,
        _ => DEFAULT_IDLE_THRESHOLD_SEC,
    }
}

struct Running {
    hooks: HookThread,
    stop: Arc<AtomicBool>,
    thread: JoinHandle<()>,
    done: Receiver<()>,
    sender: Arc<Mutex<EventSender>>,
}

pub struct WindowActivity {
    client: Arc<ServerClient>,
    hooks: Option<HookFactory>,
    idle_source: IdleSource,
    log: Log,
    running: Option<Running>,
}

impl WindowActivity {
    pub fn new(client: Arc<ServerClient>) -> WindowActivity {
        WindowActivity {
            client,
            hooks: Some(Box::new(|on_event| {
                HookThread::start(HookHandler::new(on_event, Arc::new(RealWin)))
            })),
            idle_source: Arc::new(idle_seconds),
            log: log_stderr(),
            running: None,
        }
    }

    /// Tests: the hook thread comes from `factory`.
    pub fn with_hooks(mut self, factory: HookFactory) -> WindowActivity {
        self.hooks = Some(factory);
        self
    }

    /// Tests: no hook thread at all.
    pub fn with_no_hooks(self) -> WindowActivity {
        self.with_hooks(Box::new(|_| HookThread::not_started()))
    }

    pub fn with_idle_source(mut self, f: IdleSource) -> WindowActivity {
        self.idle_source = f;
        self
    }

    pub fn with_log(mut self, log: Log) -> WindowActivity {
        self.log = log;
        self
    }

    /// The pump thread is alive.
    pub fn running(&self) -> bool {
        self.running
            .as_ref()
            .is_some_and(|r| !r.thread.is_finished())
    }

    /// Events waiting in the sender (0 when not started).
    pub fn pending(&self) -> usize {
        self.running.as_ref().map_or(0, |r| {
            r.sender.lock().unwrap_or_else(|e| e.into_inner()).pending()
        })
    }

    /// Starts the hooks and the pump, unless the server does not want window events (e.g.
    /// `--activity off`). Only the first call does anything.
    pub fn on_hello(&mut self, hello: &Value) {
        if !wants_window_events(hello) {
            return;
        }
        let Some(factory) = self.hooks.take() else {
            return;
        };
        let sender = Arc::new(Mutex::new(
            EventSender::new(self.client.clone(), events_max(hello), BUFFER_MAX)
                .with_log(self.log.clone()),
        ));
        let pump = Arc::new(
            EventPump::new(
                WindowEventCoalescer::new(),
                sender.clone(),
                IdleTracker::new(idle_threshold_sec(hello)),
                self.idle_source.clone(),
                IDLE_EVERY_SEC,
            )
            .with_log(self.log.clone()),
        );
        let feed = pump.clone();
        let hooks = factory(Arc::new(move |e| feed.on_raw(e)));
        let stop = Arc::new(AtomicBool::new(false));
        let (done_tx, done) = mpsc::channel();
        let st = stop.clone();
        let spawned = std::thread::Builder::new()
            .name("agent-events".into())
            .spawn(move || {
                pump.run(st);
                let _ = done_tx.send(());
            });
        match spawned {
            Ok(thread) => {
                self.running = Some(Running {
                    hooks,
                    stop,
                    thread,
                    done,
                    sender,
                })
            }
            Err(e) => {
                hooks.stop();
                (self.log)(&format!("window events not started: {e}"));
            }
        }
    }

    /// Stops the hooks, then the pump, then delivers what is left once (a failure is only
    /// logged). Safe to call more than once.
    pub fn stop(&mut self) {
        self.hooks = None;
        let Some(r) = self.running.take() else {
            return;
        };
        r.hooks.stop();
        r.stop.store(true, Ordering::SeqCst);
        r.thread.thread().unpark();
        if r.done
            .recv_timeout(Duration::from_secs(PUMP_JOIN_SEC))
            .is_ok()
        {
            let _ = r.thread.join();
        }
        let flushed = r.sender.lock().unwrap_or_else(|e| e.into_inner()).flush();
        if let Err(e) = flushed {
            (self.log)(&format!("final event flush failed: {e}"));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::coalesce::{Kind, RawWinEvent};
    use crate::agent::testkit::*;
    use crate::agent::time;
    use serde_json::json;

    fn events_sent(fake: &FakeServer) -> Vec<Value> {
        fake.state()
            .requests
            .iter()
            .filter(|r| r.path == "/api/agent/events")
            .flat_map(|r| {
                r.body.clone().unwrap()["events"]
                    .as_array()
                    .unwrap()
                    .clone()
            })
            .collect()
    }

    #[test]
    fn activity_skips_hooks_when_the_server_does_not_want_window_events() {
        let fake = FakeServer::new();
        let mut a = WindowActivity::new(client(&fake)).with_idle_source(Arc::new(|| Some(0.0)));
        a.on_hello(&json!({"window_events": false}));
        assert!(!a.running());
        a.stop();
        assert!(fake.state().requests.is_empty());
    }

    #[test]
    fn activity_runs_the_pump_and_flushes_what_is_left_on_stop() {
        let fake = FakeServer::new();
        let c = client(&fake);
        c.next(0.0).unwrap(); // a proven answer: window events may go out
        let mut a = WindowActivity::new(c)
            .with_idle_source(Arc::new(|| Some(400.0)))
            .with_no_hooks();
        a.on_hello(&json!({"window_events": true, "events_max": 200, "idle_threshold_sec": 300}));
        assert!(a.running());
        wait_until(|| {
            fake.state()
                .requests
                .iter()
                .any(|r| r.path == "/api/agent/events")
        });
        a.stop();
        assert!(!a.running());
        let body = fake
            .state()
            .requests
            .iter()
            .find(|r| r.path == "/api/agent/events")
            .unwrap()
            .body
            .clone()
            .unwrap();
        assert_eq!(body["events"][0]["type"], "idle");
    }

    #[test]
    fn the_final_flush_sends_nothing_after_an_unproven_401() {
        let fake = FakeServer::new();
        let c = client(&fake);
        fake.state().key = None;
        fake.state()
            .status_for
            .insert("/api/agent/next".into(), 401);
        assert!(c.next(0.0).is_err());
        let mut a = WindowActivity::new(c)
            .with_idle_source(Arc::new(|| Some(400.0)))
            .with_no_hooks();
        a.on_hello(&json!({"window_events": true}));
        wait_until(|| a.pending() > 0); // F29: there is something the final flush could send
        a.stop();
        assert!(
            !fake
                .state()
                .requests
                .iter()
                .any(|r| r.path == "/api/agent/events")
        );
    }

    // --- beyond the plan --------------------------------------------------------------------

    #[test]
    fn hooked_window_events_reach_the_server_after_the_idle_one() {
        let fake = FakeServer::new();
        let c = client(&fake);
        c.next(0.0).unwrap();
        let fed: Arc<Mutex<Option<OnEvent>>> = Arc::new(Mutex::new(None));
        let f = fed.clone();
        let mut a = WindowActivity::new(c)
            .with_idle_source(Arc::new(|| Some(999.0)))
            .with_hooks(Box::new(move |on_event| {
                *f.lock().unwrap() = Some(on_event);
                HookThread::not_started()
            }));
        a.on_hello(&json!({"heartbeat_sec": 5, "events_max": 200, "idle_threshold_sec": 300}));
        let on_event = fed.lock().unwrap().clone().expect("hooks were made");
        on_event(RawWinEvent {
            t: time::monotonic(),
            kind: Kind::Foreground,
            hwnd: 1,
            pid: 10,
            exe: Some("a.exe".into()),
            title: "A".into(),
            at_ms: 1_793_768_397_000,
        });
        wait_until(|| events_sent(&fake).len() >= 2);
        a.stop();
        let sent = events_sent(&fake);
        assert_eq!(
            sent.iter()
                .map(|e| e["type"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["idle", "foreground"]
        );
        assert_eq!(
            sent[1],
            json!({"type": "foreground", "at": "2026-11-04T13:59:57.000+09:00", "pid": 10, "exe": "a.exe", "title": "A"})
        );
    }

    #[test]
    fn the_final_flush_sends_what_the_pump_could_not() {
        let fake = FakeServer::new();
        let c = client(&fake);
        c.next(0.0).unwrap();
        fake.state()
            .status_for
            .insert("/api/agent/events".into(), 503); // the pump cannot deliver
        let mut a = WindowActivity::new(c.clone())
            .with_idle_source(Arc::new(|| Some(999.0)))
            .with_no_hooks();
        a.on_hello(&json!({"window_events": true}));
        wait_until(|| {
            fake.state()
                .requests
                .iter()
                .any(|r| r.path == "/api/agent/events")
        });
        let refused = {
            let mut st = fake.state();
            st.status_for.remove("/api/agent/events");
            st.requests
                .iter()
                .filter(|r| r.path == "/api/agent/events")
                .count()
        };
        c.next(0.0).unwrap(); // the runner's long poll proves the server again after the outage
        a.stop();
        let posts = fake
            .state()
            .requests
            .iter()
            .filter(|r| r.path == "/api/agent/events")
            .count();
        assert!(posts > refused, "{posts} > {refused}");
        let last = fake
            .state()
            .requests
            .iter()
            .rfind(|r| r.path == "/api/agent/events")
            .unwrap()
            .body
            .clone()
            .unwrap();
        assert_eq!(last["events"][0]["type"], "idle");
    }

    #[test]
    fn a_failed_final_flush_is_logged() {
        let fake = FakeServer::new();
        let c = client(&fake);
        c.next(0.0).unwrap();
        let lines = Arc::new(Mutex::new(Vec::<String>::new()));
        let l = lines.clone();
        let mut a = WindowActivity::new(c.clone())
            .with_idle_source(Arc::new(|| Some(999.0)))
            .with_no_hooks()
            .with_log(Arc::new(move |s: &str| l.lock().unwrap().push(s.into())));
        fake.state()
            .status_for
            .insert("/api/agent/events".into(), 401);
        a.on_hello(&json!({"window_events": true}));
        wait_until(|| !a.running()); // the pump ends on the rejection
        c.next(0.0).unwrap(); // proven again, so the final flush really posts (and is refused)
        a.stop();
        assert_eq!(
            lines.lock().unwrap().clone(),
            ["final event flush failed: POST /api/agent/events: 401"]
        );
        a.stop(); // twice is harmless
    }

    #[test]
    fn hello_numbers_are_read_like_python() {
        assert_eq!(events_max(&json!({})), 200);
        assert_eq!(events_max(&json!({"events_max": 50})), 50);
        assert_eq!(events_max(&json!({"events_max": 7.9})), 7);
        assert_eq!(events_max(&json!({"events_max": " 7 "})), 7);
        assert_eq!(events_max(&json!({"events_max": true})), 1);
        for bad in [
            json!(0),
            json!(-3),
            json!("7.5"),
            json!(null),
            json!([1]),
            json!(false),
        ] {
            assert_eq!(events_max(&json!({ "events_max": bad })), 200, "{bad}");
        }
        assert_eq!(idle_threshold_sec(&json!({})), 300.0);
        assert_eq!(idle_threshold_sec(&json!({"idle_threshold_sec": 60})), 60.0);
        assert_eq!(
            idle_threshold_sec(&json!({"idle_threshold_sec": "0.5"})),
            0.5
        );
        for bad in [
            json!(0),
            json!(-1.0),
            json!("x"),
            json!(null),
            json!("nan"),
            json!("inf"),
        ] {
            assert_eq!(
                idle_threshold_sec(&json!({ "idle_threshold_sec": bad })),
                300.0,
                "{bad}"
            );
        }
    }
}
