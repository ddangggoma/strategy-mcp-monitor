//! Moves coalesced window events and idle transitions from the hook thread to the sender (Python
//! `mcp_agent.pump`): a step every 0.25 s, a flush every second, the idle time every 5 s.

use super::client::ClientError;
use super::coalesce::{RawWinEvent, WindowEventCoalescer};
use super::idle::IdleTracker;
use super::runner::{Log, log_stderr};
use super::sender::{EventSender, Item};
use super::time;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};

pub const STEP_SEC: f64 = 0.25;
pub const FLUSH_SEC: f64 = 1.0;
/// How often the session's idle time is read (Python `idle_every_sec`, F10).
pub const IDLE_EVERY_SEC: f64 = 5.0;

pub type IdleSource = Arc<dyn Fn() -> Option<f64> + Send + Sync>;

struct IdleState {
    tracker: IdleTracker,
    last_check: Option<f64>,
}

pub struct EventPump {
    coalescer: Mutex<WindowEventCoalescer>,
    sender: Arc<Mutex<EventSender>>,
    idle: Mutex<IdleState>,
    idle_seconds: IdleSource,
    idle_every: f64,
    log: Log,
}

/// A lock that survives a panic of an earlier holder (the pump outlives one bad step).
fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

fn panic_text(p: &(dyn std::any::Any + Send)) -> String {
    p.downcast_ref::<&str>()
        .map(|s| s.to_string())
        .or_else(|| p.downcast_ref::<String>().cloned())
        .unwrap_or_else(|| "a panic".into())
}

impl EventPump {
    pub fn new(
        coalescer: WindowEventCoalescer,
        sender: Arc<Mutex<EventSender>>,
        idle: IdleTracker,
        idle_seconds: IdleSource,
        idle_every_sec: f64,
    ) -> EventPump {
        EventPump {
            coalescer: Mutex::new(coalescer),
            sender,
            idle: Mutex::new(IdleState {
                tracker: idle,
                last_check: None,
            }),
            idle_seconds,
            idle_every: idle_every_sec,
            log: log_stderr(),
        }
    }

    pub fn with_log(mut self, log: Log) -> EventPump {
        self.log = log;
        self
    }

    /// Called on the hook thread: only a lock and a push.
    pub fn on_raw(&self, e: RawWinEvent) {
        lock(&self.coalescer).add(e);
    }

    /// Moves what the coalescer has ready at monotonic `mono` into the sender, and every
    /// `idle_every_sec` an idle transition (an idle source that cannot tell is tried again next
    /// time).
    pub fn step(&self, mono: f64, wall_ms: i64) {
        let ready = lock(&self.coalescer).drain(mono);
        if !ready.is_empty() {
            let mut sender = lock(&self.sender);
            for e in ready {
                sender.add(Item::Win(e));
            }
        }
        let mut idle = lock(&self.idle);
        if idle
            .last_check
            .is_some_and(|last| mono - last < self.idle_every)
        {
            return;
        }
        idle.last_check = Some(mono);
        let Some(idle_sec) = (self.idle_seconds)().filter(|s| s.is_finite() && *s >= 0.0) else {
            return; // e.g. no input info on a disconnected desktop
        };
        if let Some(change) = idle.tracker.update(idle_sec, wall_ms) {
            lock(&self.sender).add(Item::Idle(change));
        }
    }

    /// Steps every 0.25 s and flushes every second until `stop` is set (the waits end at once
    /// when the thread is unparked) or the token is rejected. Anything else (a panic in a step)
    /// is logged and the pump goes on.
    pub fn run(&self, stop: Arc<AtomicBool>) {
        let mut next_flush = time::monotonic() + FLUSH_SEC;
        loop {
            let until = Instant::now() + Duration::from_secs_f64(STEP_SEC);
            while !stop.load(Ordering::SeqCst) {
                let now = Instant::now();
                if now >= until {
                    break;
                }
                std::thread::park_timeout(until - now);
            }
            if stop.load(Ordering::SeqCst) {
                return;
            }
            let mono = time::monotonic();
            let outcome = catch_unwind(AssertUnwindSafe(|| -> Result<(), ClientError> {
                self.step(mono, time::now_ms());
                if mono >= next_flush {
                    next_flush = mono + FLUSH_SEC;
                    lock(&self.sender).flush()?;
                }
                Ok(())
            }));
            match outcome {
                Ok(Ok(())) => {}
                Ok(Err(e)) if e.is_rejected() => return, // the runner sees it too and exits
                Ok(Err(e)) => (self.log)(&format!("event pump: {e}")),
                Err(p) => (self.log)(&format!("event pump: {}", panic_text(p.as_ref()))),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::coalesce::Kind;
    use crate::agent::sender::Poster;
    use serde_json::Value;

    const AT: i64 = 1_793_768_397_000;

    /// Records the posted bodies; `fail` decides each post's outcome by its index.
    struct Recording {
        bodies: Mutex<Vec<Value>>,
        fail: Box<dyn Fn(usize) -> Option<ClientError> + Send + Sync>,
    }
    impl Recording {
        fn new(
            fail: impl Fn(usize) -> Option<ClientError> + Send + Sync + 'static,
        ) -> Arc<Recording> {
            Arc::new(Recording {
                bodies: Mutex::new(Vec::new()),
                fail: Box::new(fail),
            })
        }
        fn events(&self) -> Vec<Value> {
            lock(&self.bodies)
                .iter()
                .flat_map(|b| b["events"].as_array().unwrap().clone())
                .collect()
        }
    }
    impl Poster for Recording {
        fn post(
            &self,
            _path: &str,
            body: Option<&Value>,
            _verified_only: bool,
        ) -> Result<Option<Value>, ClientError> {
            let n = {
                let mut b = lock(&self.bodies);
                b.push(body.cloned().unwrap());
                b.len() - 1
            };
            match (self.fail)(n) {
                Some(e) => Err(e),
                None => Ok(None),
            }
        }
    }

    fn fg(t: f64, title: &str) -> RawWinEvent {
        RawWinEvent {
            t,
            kind: Kind::Foreground,
            hwnd: 1,
            pid: 10,
            exe: Some("a.exe".into()),
            title: title.into(),
            at_ms: AT,
        }
    }
    fn sender_of(p: &Arc<Recording>) -> Arc<Mutex<EventSender>> {
        Arc::new(Mutex::new(EventSender::new(p.clone(), 200, 2000)))
    }
    fn kinds(s: &Arc<Mutex<EventSender>>, p: &Arc<Recording>) -> Vec<String> {
        lock(s).flush().unwrap();
        p.events()
            .iter()
            .map(|e| e["type"].as_str().unwrap().to_string())
            .collect()
    }
    fn pump(s: &Arc<Mutex<EventSender>>, idle: IdleSource) -> EventPump {
        EventPump::new(
            WindowEventCoalescer::new(),
            s.clone(),
            IdleTracker::new(300.0),
            idle,
            IDLE_EVERY_SEC,
        )
    }
    fn logs() -> (Log, Arc<Mutex<Vec<String>>>) {
        let lines = Arc::new(Mutex::new(Vec::new()));
        let l = lines.clone();
        (Arc::new(move |s: &str| lock(&l).push(s.to_string())), lines)
    }
    fn wait_until(f: impl Fn() -> bool) {
        let end = Instant::now() + Duration::from_secs(5);
        while !f() {
            assert!(Instant::now() < end, "condition not met within 5 s");
            std::thread::sleep(Duration::from_millis(20));
        }
    }

    #[test]
    fn pump_moves_coalesced_events_and_idle_into_the_sender() {
        let p = Recording::new(|_| None);
        let s = sender_of(&p);
        let pump = pump(&s, Arc::new(|| Some(301.0)));
        pump.on_raw(fg(0.0, "A"));
        pump.step(0.1, AT);
        assert_eq!(kinds(&s, &p), ["idle"]);
        pump.step(0.5, AT);
        assert_eq!(kinds(&s, &p), ["idle", "foreground"]);
    }

    #[test]
    fn pump_checks_idle_every_5_s_and_survives_a_failing_idle_source() {
        let values = Arc::new(Mutex::new(vec![Some(10.0), None, Some(301.0), Some(2.0)]));
        let v = values.clone();
        let p = Recording::new(|_| None);
        let s = sender_of(&p);
        let pump = pump(&s, Arc::new(move || lock(&v).remove(0)));
        for mono in [0.0, 1.0, 4.9, 5.0, 9.9, 10.0, 15.0] {
            pump.step(mono, AT);
        }
        assert_eq!(kinds(&s, &p), ["idle", "active"]);
        assert!(lock(&values).is_empty());
    }

    #[test]
    fn pump_run_steps_and_flushes_until_stopped() {
        let p = Recording::new(|_| None);
        let s = sender_of(&p);
        let pump = Arc::new(pump(&s, Arc::new(|| Some(0.0))));
        let stop = Arc::new(AtomicBool::new(false));
        let (pp, st) = (pump.clone(), stop.clone());
        let t = std::thread::spawn(move || pp.run(st));
        pump.on_raw(fg(time::monotonic(), "A"));
        wait_until(|| !p.events().is_empty());
        let asked = Instant::now();
        stop.store(true, Ordering::SeqCst);
        t.thread().unpark();
        t.join().unwrap();
        assert!(
            asked.elapsed() < Duration::from_millis(200),
            "{:?}",
            asked.elapsed()
        );
        assert_eq!(
            p.events()
                .iter()
                .map(|e| e["title"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["A"]
        );
    }

    #[test]
    fn pump_run_ends_when_the_token_is_rejected() {
        let p = Recording::new(|_| Some(ClientError::Rejected("403".into())));
        let s = sender_of(&p);
        let pump = Arc::new(pump(&s, Arc::new(|| Some(999.0)))); // an idle event to send
        let pp = pump.clone();
        let t = std::thread::spawn(move || pp.run(Arc::new(AtomicBool::new(false))));
        wait_until(|| t.is_finished());
        t.join().unwrap();
        assert_eq!(lock(&p.bodies).len(), 1);
        assert_eq!(lock(&s).pending(), 1);
    }

    #[test]
    fn pump_run_keeps_going_after_a_failing_step() {
        let p = Recording::new(|n| {
            if n == 0 {
                panic!("boom");
            }
            None
        });
        let s = sender_of(&p);
        let (log, lines) = logs();
        let pump = Arc::new(pump(&s, Arc::new(|| Some(999.0))).with_log(log));
        let stop = Arc::new(AtomicBool::new(false));
        let (pp, st) = (pump.clone(), stop.clone());
        let t = std::thread::spawn(move || pp.run(st));
        wait_until(|| lock(&p.bodies).len() >= 2);
        stop.store(true, Ordering::SeqCst);
        t.thread().unpark();
        t.join().unwrap();
        assert_eq!(lock(&lines).clone(), ["event pump: boom"]);
        assert_eq!(p.events()[1]["type"], "idle"); // the event survived the failed post
    }
}
