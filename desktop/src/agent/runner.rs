//! hello → heartbeat thread → long-poll command loop (Python `mcp_agent.runner`). Exit codes:
//! 0 = told to exit, 3 = the server rejected our token, 4 = the server was unreachable for
//! `unreachable_exit_sec`, 5 = whatever answers is not our service (it could not prove the launch
//! key, Plan 4 I1).
//!
//! Only notice URLs of the configured server (`<server>/notice#…`) are ever opened. A command or
//! answer the agent cannot use is logged and skipped; it does not end the agent (M13). The token
//! (the URL fragment) is never logged.
//!
//! Lenient parsing, as Python's `int()` / `float()` / `bool()` read the server's JSON (F29):
//! - `display_id` of `show_notice`: an integer, a number (cut to an integer), a decimal string
//!   (`"7"`, spaces around allowed) or a boolean (1/0); anything else fails that command.
//! - `close_notice` closes only when its `display_id` equals the open one as a number (`7` or
//!   `7.0`; a string never matches).
//! - `heartbeat_sec`: a number, a numeric string (`"0.5"`) or a boolean; missing, not a number,
//!   not finite or not above 0 → 5 s.
//! - `window_events`: missing → on; otherwise Python truthiness (`null`, `false`, `0`, `""`, `[]`,
//!   `{}` → off).

use super::client::{ClientError, ServerClient};
use super::config::AgentConfig;
use crate::version::PRODUCT;
use serde_json::{Value, json};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

pub const EXIT_OK: i32 = 0;
pub const EXIT_REJECTED: i32 = 3;
pub const EXIT_UNREACHABLE: i32 = 4;
pub const EXIT_UNVERIFIED: i32 = 5;
/// Seconds between attempts while the server cannot be reached: 1, 2, 4, 8, 10, 10, …
pub const BACKOFF_SEC: [f64; 5] = [1.0, 2.0, 4.0, 8.0, 10.0];
pub const POLL_SEC: f64 = 25.0;
/// Check for a window the user closed at least this often.
pub const POLL_WHILE_SHOWN_SEC: f64 = 2.0;
pub const DEFAULT_HEARTBEAT_SEC: f64 = 5.0;
/// How long the end of `run` waits for the heartbeat thread (busy with a request).
pub const HEARTBEAT_JOIN_SEC: u64 = 5;

pub trait NoticeWindow: Send {
    fn open(&mut self, url: &str, display_id: i64) -> Result<(), String>;
    fn close(&mut self);
    /// True when the window went away without us closing it.
    fn closed_by_user(&mut self) -> bool;
}

pub struct Clock {
    pub monotonic: Arc<dyn Fn() -> f64 + Send + Sync>,
    pub sleep: Arc<dyn Fn(f64) + Send + Sync>,
}

impl Clock {
    pub fn real() -> Clock {
        let start = Instant::now();
        Clock {
            monotonic: Arc::new(move || start.elapsed().as_secs_f64()),
            sleep: Arc::new(|sec| {
                std::thread::sleep(Duration::try_from_secs_f64(sec).unwrap_or_default())
            }),
        }
    }
}

pub type Log = Arc<dyn Fn(&str) + Send + Sync>;

/// `mcp-monitor agent: <line>` on standard error; never fails (a closed pipe drops the line).
pub fn log_stderr() -> Log {
    Arc::new(|line: &str| {
        use std::io::Write;
        let _ = writeln!(std::io::stderr(), "mcp-monitor agent: {line}");
    })
}

/// Seconds since the last keyboard or mouse input in this session (`GetLastInputInfo`); `None`
/// when Windows cannot tell (that heartbeat is skipped, F10).
pub fn idle_seconds() -> Option<f64> {
    use windows::Win32::System::SystemInformation::GetTickCount64;
    use windows::Win32::UI::Input::KeyboardAndMouse::{GetLastInputInfo, LASTINPUTINFO};
    let mut info = LASTINPUTINFO {
        cbSize: std::mem::size_of::<LASTINPUTINFO>() as u32,
        dwTime: 0,
    };
    // SAFETY: `info` is a valid, sized LASTINPUTINFO for the duration of the call.
    if !unsafe { GetLastInputInfo(&mut info) }.as_bool() {
        return None;
    }
    // dwTime is the low 32 bits of the tick count; subtracting modulo 2^32 makes a wrap harmless.
    // SAFETY: plain call.
    let now = unsafe { GetTickCount64() } as u32;
    Some(f64::from(now.wrapping_sub(info.dwTime)) / 1000.0)
}

/// HELLO `window_events`: a missing key means on; otherwise Python truthiness.
pub fn wants_window_events(hello: &Value) -> bool {
    match hello.get("window_events") {
        None => true,
        Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64() != Some(0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

/// HELLO `heartbeat_sec`, or 5 s when it is not a usable positive number.
pub fn heartbeat_sec(hello: &Value) -> f64 {
    let sec = match hello.get("heartbeat_sec") {
        None => return DEFAULT_HEARTBEAT_SEC,
        Some(Value::Number(n)) => n.as_f64(),
        Some(Value::String(s)) => s.trim().parse::<f64>().ok(),
        Some(Value::Bool(b)) => Some(if *b { 1.0 } else { 0.0 }),
        Some(_) => None,
    };
    match sec {
        Some(s) if s.is_finite() && s > 0.0 => s,
        _ => DEFAULT_HEARTBEAT_SEC,
    }
}

/// `int(cmd["display_id"])` of the Python agent.
fn display_id(v: Option<&Value>) -> Result<i64, String> {
    match v {
        None => Err("no display_id".into()),
        Some(Value::Number(n)) => n
            .as_i64()
            .or_else(|| {
                n.as_f64()
                    .filter(|f| f.is_finite() && f.abs() < 9.0e18)
                    .map(|f| f.trunc() as i64)
            })
            .ok_or_else(|| format!("display_id {n} is out of range")),
        Some(Value::String(s)) => s
            .trim()
            .parse::<i64>()
            .map_err(|_| "display_id is not a number".to_string()),
        Some(Value::Bool(b)) => Ok(i64::from(*b)),
        Some(_) => Err("display_id is not a number".into()),
    }
}

/// `pending == cmd.get("display_id")` of the Python agent.
fn same_id(v: Option<&Value>, id: i64) -> bool {
    match v {
        Some(Value::Number(n)) => match n.as_i64() {
            Some(i) => i == id,
            None => n.as_f64() == Some(id as f64),
        },
        Some(Value::Bool(b)) => i64::from(*b) == id,
        _ => false,
    }
}

/// How a refused notice URL is logged: what comes before `#` (never the fragment, which holds
/// the token), as a JSON string so control characters cannot forge log lines.
fn shown_url(url: Option<&Value>) -> String {
    match url {
        Some(Value::String(s)) => {
            let shown = match s.split_once('#') {
                Some((before, _)) => format!("{before}#..."),
                None => s.clone(),
            };
            serde_json::to_string(&shown).unwrap_or_default()
        }
        Some(Value::Null) | None => "(none)".into(),
        Some(Value::Bool(_)) => "(a boolean)".into(),
        Some(Value::Number(_)) => "(a number)".into(),
        Some(Value::Array(_)) => "(an array)".into(),
        Some(Value::Object(_)) => "(an object)".into(),
    }
}

/// Why the session ended early.
enum End {
    Rejected,
    Unverified(String),
    Unreachable,
}

/// 1, 2, 4, 8, 10, 10 … seconds between attempts; gives up `limit` seconds after the first failure.
struct Backoff {
    limit: f64,
    monotonic: Arc<dyn Fn() -> f64 + Send + Sync>,
    sleep: Arc<dyn Fn(f64) + Send + Sync>,
    since: Option<f64>,
    failures: usize,
}

impl Backoff {
    fn new(limit: f64, clock: &Clock) -> Backoff {
        Backoff {
            limit,
            monotonic: clock.monotonic.clone(),
            sleep: clock.sleep.clone(),
            since: None,
            failures: 0,
        }
    }

    fn failed(&mut self) -> Result<(), End> {
        let now = (self.monotonic)();
        let since = *self.since.get_or_insert(now);
        if now - since >= self.limit {
            return Err(End::Unreachable);
        }
        (self.sleep)(BACKOFF_SEC[self.failures.min(BACKOFF_SEC.len() - 1)]);
        self.failures = self.failures.saturating_add(1);
        Ok(())
    }

    fn ok(&mut self) {
        self.since = None;
        self.failures = 0;
    }
}

/// What the heartbeat thread hands the command loop (Python `_rejection` / `_rejected`).
#[derive(Default)]
struct Rejection {
    flag: AtomicBool,
    error: Mutex<Option<ClientError>>,
}

struct Heartbeat {
    /// Dropping it wakes and ends the thread at once (it waits on the channel, not in a sleep).
    stop: mpsc::Sender<()>,
    done: mpsc::Receiver<()>,
    handle: JoinHandle<()>,
}

type OnHello = Box<dyn FnOnce(&Value) + Send>;
type IdleSource = Arc<dyn Fn() -> Option<f64> + Send + Sync>;

pub struct AgentRunner {
    notice_prefix: String,
    unreachable_exit_sec: f64,
    client: Arc<ServerClient>,
    window: Box<dyn NoticeWindow>,
    session_id: u32,
    pid: u32,
    clock: Clock,
    idle: IdleSource,
    log: Log,
    on_hello: Option<OnHello>,
}

impl AgentRunner {
    pub fn new(
        cfg: &AgentConfig,
        client: Arc<ServerClient>,
        window: Box<dyn NoticeWindow>,
        session_id: u32,
        pid: u32,
    ) -> AgentRunner {
        AgentRunner {
            notice_prefix: format!("{}/notice#", cfg.server.trim_end_matches('/')),
            unreachable_exit_sec: cfg.unreachable_exit_sec,
            client,
            window,
            session_id,
            pid,
            clock: Clock::real(),
            idle: Arc::new(idle_seconds),
            log: log_stderr(),
            on_hello: None,
        }
    }

    pub fn with_clock(mut self, clock: Clock) -> AgentRunner {
        self.clock = clock;
        self
    }

    /// The heartbeat's idle source; `None` from it skips that heartbeat (logged).
    pub fn with_idle(mut self, idle: Arc<dyn Fn() -> Option<f64> + Send + Sync>) -> AgentRunner {
        self.idle = idle;
        self
    }

    pub fn with_log(mut self, log: Log) -> AgentRunner {
        self.log = log;
        self
    }

    /// Called once with the server's HELLO answer, before the heartbeat starts.
    pub fn on_hello(mut self, f: Box<dyn FnOnce(&Value) + Send>) -> AgentRunner {
        self.on_hello = Some(f);
        self
    }

    /// Runs until told to exit or the session ends; returns the exit code. The window is always
    /// closed at the end, and the heartbeat thread is waited for (up to 5 s).
    pub fn run(mut self) -> i32 {
        let rejection = Arc::new(Rejection::default());
        let mut heartbeat = None;
        let code = match self.session(&rejection, &mut heartbeat) {
            Ok(code) => code,
            Err(End::Unverified(m)) => {
                (self.log)(&format!("{m}; stopping"));
                EXIT_UNVERIFIED
            }
            Err(End::Rejected) => EXIT_REJECTED,
            Err(End::Unreachable) => EXIT_UNREACHABLE,
        };
        let stopping = heartbeat.map(|h: Heartbeat| {
            drop(h.stop);
            (h.done, h.handle)
        });
        self.window.close();
        if let Some((done, handle)) = stopping {
            match done.recv_timeout(Duration::from_secs(HEARTBEAT_JOIN_SEC)) {
                Ok(()) | Err(RecvTimeoutError::Disconnected) => {
                    let _ = handle.join();
                }
                Err(RecvTimeoutError::Timeout) => {} // still in a request: left to the process exit
            }
        }
        code
    }

    fn session(
        &mut self,
        rejection: &Arc<Rejection>,
        heartbeat: &mut Option<Heartbeat>,
    ) -> Result<i32, End> {
        let mut backoff = Backoff::new(self.unreachable_exit_sec, &self.clock);
        let hello = self.hello(&mut backoff)?;
        if let Some(f) = self.on_hello.take() {
            f(&hello);
        }
        *heartbeat = self.start_heartbeat(heartbeat_sec(&hello), rejection.clone());
        self.command_loop(&mut backoff, rejection)
    }

    fn hello(&mut self, backoff: &mut Backoff) -> Result<Value, End> {
        let body = json!({"session_id": self.session_id, "pid": self.pid, "version": PRODUCT});
        loop {
            match self.client.post("/api/agent/hello", Some(&body), false) {
                Ok(hello) => {
                    backoff.ok();
                    return Ok(hello.unwrap_or_else(|| json!({})));
                }
                Err(ClientError::Unavailable(_)) => backoff.failed()?,
                // A proven but unusable answer (M13): try again later.
                Err(ClientError::Unexpected(m)) => {
                    (self.log)(&format!("hello: {m}"));
                    backoff.failed()?;
                }
                Err(ClientError::Rejected(_)) => return Err(End::Rejected),
                Err(ClientError::Unverified(m)) => return Err(End::Unverified(m)),
            }
        }
    }

    fn command_loop(&mut self, backoff: &mut Backoff, rejection: &Rejection) -> Result<i32, End> {
        let mut pending: Option<i64> = None;
        // The user closed the window but the server has not been told yet (a lost report is sent
        // again; a window may report a user close only once).
        let mut closed_unreported = false;
        loop {
            if rejection.flag.load(Ordering::SeqCst) {
                let error = rejection
                    .error
                    .lock()
                    .unwrap_or_else(|e| e.into_inner())
                    .take();
                return Err(match error {
                    Some(ClientError::Unverified(m)) => End::Unverified(m),
                    _ => End::Rejected,
                });
            }
            let cmd = match self.poll(&mut pending, &mut closed_unreported) {
                Ok(cmd) => {
                    backoff.ok();
                    cmd
                }
                Err(ClientError::Unavailable(_)) => {
                    backoff.failed()?;
                    continue;
                }
                // A proven but unexpected answer (M13): log, back off, go on.
                Err(ClientError::Unexpected(m)) => {
                    (self.log)(&m);
                    backoff.failed()?;
                    continue;
                }
                Err(ClientError::Rejected(_)) => return Err(End::Rejected),
                Err(ClientError::Unverified(m)) => return Err(End::Unverified(m)),
            };
            let Some(cmd) = cmd else { continue };
            let kind = cmd.get("type");
            if kind.and_then(Value::as_str) == Some("exit") {
                return Ok(EXIT_OK); // run() closes the window
            }
            // One bad command (or window) must not end the agent (M13).
            if let Err(e) = self.command(&cmd, &mut pending, &mut closed_unreported) {
                let kind = kind.map_or_else(|| "null".to_string(), Value::to_string);
                (self.log)(&format!("command {kind} failed: {e}"));
            }
        }
    }

    /// Reports a window the user closed, then asks for the next command.
    fn poll(
        &mut self,
        pending: &mut Option<i64>,
        closed_unreported: &mut bool,
    ) -> Result<Option<Value>, ClientError> {
        if let Some(id) = *pending
            && (*closed_unreported || self.window.closed_by_user())
        {
            *closed_unreported = true;
            self.client
                .post(&format!("/api/agent/notice/{id}/closed"), None, false)?;
            *pending = None;
            *closed_unreported = false;
        }
        self.client.next(if pending.is_some() {
            POLL_WHILE_SHOWN_SEC
        } else {
            POLL_SEC
        })
    }

    /// `show_notice` / `close_notice`; anything else is ignored.
    fn command(
        &mut self,
        cmd: &Value,
        pending: &mut Option<i64>,
        closed_unreported: &mut bool,
    ) -> Result<(), String> {
        match cmd.get("type").and_then(Value::as_str) {
            Some("show_notice") => {
                let id = display_id(cmd.get("display_id"))?;
                let url = cmd.get("url");
                let Some(url) = url
                    .and_then(Value::as_str)
                    .filter(|u| u.starts_with(&self.notice_prefix))
                else {
                    (self.log)(&format!(
                        "refused notice url {}: not under {}",
                        shown_url(url),
                        self.notice_prefix
                    ));
                    return Ok(());
                };
                if pending.take().is_some() {
                    self.window.close();
                }
                *closed_unreported = false;
                self.window.open(url, id)?;
                *pending = Some(id);
                Ok(())
            }
            Some("close_notice") => {
                if let Some(id) = *pending
                    && same_id(cmd.get("display_id"), id)
                {
                    self.window.close();
                    *pending = None;
                    *closed_unreported = false;
                }
                Ok(())
            }
            _ => Ok(()),
        }
    }

    fn start_heartbeat(&self, every: f64, rejection: Arc<Rejection>) -> Option<Heartbeat> {
        let (stop_tx, stop_rx) = mpsc::channel::<()>();
        let (done_tx, done_rx) = mpsc::channel::<()>();
        let client = self.client.clone();
        let idle = self.idle.clone();
        let log = self.log.clone();
        // Too long for a Duration: wait for the stop only.
        let wait = Duration::try_from_secs_f64(every).unwrap_or(Duration::MAX);
        let spawned = std::thread::Builder::new()
            .name("agent-heartbeat".into())
            .spawn(move || {
                while let Err(RecvTimeoutError::Timeout) = stop_rx.recv_timeout(wait) {
                    if !beat(&client, &idle, &log, &rejection) {
                        break;
                    }
                }
                let _ = done_tx.send(());
            });
        match spawned {
            Ok(handle) => Some(Heartbeat {
                stop: stop_tx,
                done: done_rx,
                handle,
            }),
            Err(e) => {
                (self.log)(&format!("heartbeat thread not started: {e}"));
                None
            }
        }
    }
}

/// One heartbeat; false when the server rejected us (the command loop then ends the agent).
fn beat(client: &ServerClient, idle: &IdleSource, log: &Log, rejection: &Rejection) -> bool {
    let Some(idle_sec) = idle().filter(|s| s.is_finite() && *s >= 0.0) else {
        log("heartbeat skipped: the idle time is not available");
        return true;
    };
    let body = json!({"idle_sec": idle_sec as i64, "locked": null});
    match client.post("/api/agent/heartbeat", Some(&body), false) {
        // The command loop owns the unreachable limit.
        Ok(_) | Err(ClientError::Unavailable(_)) => true,
        Err(ClientError::Unexpected(m)) => {
            log(&format!("heartbeat failed: {m}"));
            true
        }
        Err(e) => {
            // Rejected or Unverified: the loop exits with its code.
            *rejection.error.lock().unwrap_or_else(|e| e.into_inner()) = Some(e);
            rejection.flag.store(true, Ordering::SeqCst);
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::testkit::*;
    use crate::cli::Dialog;
    use serde_json::{Value, json};
    use std::sync::atomic::{AtomicBool, Ordering::SeqCst};
    use std::sync::{Arc, Mutex};

    fn url(d: i64) -> String {
        format!("{BASE}/notice#d={d}&t=tok_ABCDEFGHIJKLmnop")
    }
    fn show(d: i64) -> Value {
        json!({"type": "show_notice", "display_id": d, "attempt": 1, "url": url(d)})
    }

    type OnOpen = Arc<dyn Fn() + Send + Sync>;
    #[derive(Clone, Default)]
    struct Win {
        opened: Arc<Mutex<Vec<(i64, String)>>>,
        closed: Arc<Mutex<u32>>,
        user_closed: Arc<AtomicBool>,
        fail_open: bool,
        on_open: Option<OnOpen>,
    }
    struct FakeWindow(Win);
    impl NoticeWindow for FakeWindow {
        fn open(&mut self, url: &str, id: i64) -> Result<(), String> {
            if self.0.fail_open {
                return Err("no window".into());
            }
            self.0.opened.lock().unwrap().push((id, url.into()));
            self.0.user_closed.store(false, SeqCst);
            if let Some(f) = &self.0.on_open {
                f();
            }
            Ok(())
        }
        fn close(&mut self) {
            *self.0.closed.lock().unwrap() += 1;
        }
        fn closed_by_user(&mut self) -> bool {
            self.0.user_closed.load(SeqCst)
        }
    }

    fn cfg(unreachable: f64) -> AgentConfig {
        AgentConfig {
            server: BASE.into(),
            token: "tok".into(),
            server_key: KEY,
            dialog: Dialog::Print,
            url_file: None,
            unreachable_exit_sec: unreachable,
        }
    }
    fn logs() -> (Log, Arc<Mutex<Vec<String>>>) {
        let lines = Arc::new(Mutex::new(Vec::new()));
        let l = lines.clone();
        (
            Arc::new(move |s: &str| l.lock().unwrap().push(s.to_string())),
            lines,
        )
    }
    /// A clock whose sleep advances it; `on_sleep(n)` runs after the n-th sleep.
    fn fake_clock(
        on_sleep: impl Fn(usize) + Send + Sync + 'static,
    ) -> (Clock, Arc<Mutex<Vec<f64>>>) {
        let now = Arc::new(Mutex::new(0.0));
        let sleeps = Arc::new(Mutex::new(Vec::new()));
        let (n, s) = (now.clone(), sleeps.clone());
        let clock = Clock {
            monotonic: Arc::new(move || *n.lock().unwrap()),
            sleep: Arc::new(move |d| {
                *now.lock().unwrap() += d;
                let count = {
                    let mut v = s.lock().unwrap();
                    v.push(d);
                    v.len()
                };
                on_sleep(count);
            }),
        };
        (clock, sleeps)
    }
    fn runner(
        fake: &Arc<FakeServer>,
        w: &Win,
        unreachable: f64,
    ) -> (AgentRunner, Arc<Mutex<Vec<String>>>) {
        let (log, lines) = logs();
        (
            AgentRunner::new(
                &cfg(unreachable),
                client(fake),
                Box::new(FakeWindow(w.clone())),
                2,
                4242,
            )
            .with_idle(Arc::new(|| Some(12.9)))
            .with_log(log),
            lines,
        )
    }
    fn paths(fake: &Arc<FakeServer>) -> Vec<String> {
        fake.state()
            .requests
            .iter()
            .map(|r| r.path.clone())
            .collect()
    }

    #[test]
    fn shows_and_closes_the_notice() {
        let fake = FakeServer::new();
        fake.state().commands.extend([
            show(7),
            json!({"type": "close_notice", "display_id": 7}),
            json!({"type": "exit"}),
        ]);
        let w = Win::default();
        assert_eq!(runner(&fake, &w, 120.0).0.run(), EXIT_OK);
        assert_eq!(*w.opened.lock().unwrap(), [(7, url(7))]);
        assert!(*w.closed.lock().unwrap() >= 1);
        let hello = fake
            .state()
            .requests
            .iter()
            .find(|r| r.path == "/api/agent/hello")
            .unwrap()
            .body
            .clone();
        assert_eq!(
            hello,
            Some(json!({"session_id": 2, "pid": 4242, "version": "1.1.0"}))
        );
    }

    #[test]
    fn reports_a_window_the_user_closed() {
        let fake = FakeServer::new();
        fake.state().commands.push_back(show(7));
        let w = Win::default();
        let r = runner(&fake, &w, 120.0).0;
        let t = std::thread::spawn(move || r.run());
        wait_until(|| w.opened.lock().unwrap().len() == 1);
        w.user_closed.store(true, SeqCst);
        wait_until(|| paths(&fake).contains(&"/api/agent/notice/7/closed".to_string()));
        fake.state().commands.push_back(json!({"type": "exit"}));
        assert_eq!(t.join().unwrap(), EXIT_OK);
    }

    #[test]
    fn sends_heartbeats_with_idle() {
        let fake = FakeServer::new();
        fake.state().hello =
            json!({"heartbeat_sec": 0.05, "events_max": 200, "idle_threshold_sec": 300});
        let r = runner(&fake, &Win::default(), 120.0).0;
        let t = std::thread::spawn(move || r.run());
        wait_until(|| {
            paths(&fake)
                .iter()
                .filter(|p| *p == "/api/agent/heartbeat")
                .count()
                >= 2
        });
        fake.state().commands.push_back(json!({"type": "exit"}));
        assert_eq!(t.join().unwrap(), EXIT_OK);
        let hb = fake
            .state()
            .requests
            .iter()
            .find(|r| r.path == "/api/agent/heartbeat")
            .unwrap()
            .body
            .clone();
        assert_eq!(hb, Some(json!({"idle_sec": 12, "locked": null})));
    }

    #[test]
    fn exits_3_when_rejected() {
        let fake = FakeServer::new();
        fake.state()
            .status_for
            .insert("/api/agent/hello".into(), 401);
        assert_eq!(runner(&fake, &Win::default(), 120.0).0.run(), EXIT_REJECTED);
    }

    #[test]
    fn unreachable_backoff_is_1_2_4_8_then_10_and_exits_4() {
        let fake = FakeServer::new();
        fake.state().down = true;
        let (clock, sleeps) = fake_clock(|_| {});
        assert_eq!(
            runner(&fake, &Win::default(), 30.0)
                .0
                .with_clock(clock)
                .run(),
            EXIT_UNREACHABLE
        );
        assert_eq!(*sleeps.lock().unwrap(), [1.0, 2.0, 4.0, 8.0, 10.0, 10.0]);
    }

    #[test]
    fn hello_retries_until_the_server_answers() {
        let fake = FakeServer::new();
        fake.state()
            .status_for
            .insert("/api/agent/hello".into(), 503);
        fake.state().commands.push_back(json!({"type": "exit"}));
        let f2 = fake.clone();
        let (clock, sleeps) = fake_clock(move |n| {
            if n == 2 {
                f2.state().status_for.remove("/api/agent/hello");
            }
        });
        let hellos = Arc::new(Mutex::new(Vec::new()));
        let h = hellos.clone();
        let r = runner(&fake, &Win::default(), 120.0)
            .0
            .with_clock(clock)
            .on_hello(Box::new(move |v: &Value| h.lock().unwrap().push(v.clone())));
        assert_eq!(r.run(), EXIT_OK);
        assert_eq!(*sleeps.lock().unwrap(), [1.0, 2.0]);
        assert_eq!(*hellos.lock().unwrap(), [default_hello()]);
        assert_eq!(
            paths(&fake)
                .iter()
                .filter(|p| *p == "/api/agent/hello")
                .count(),
            3
        );
    }

    #[test]
    fn window_events_flag_defaults_to_on() {
        assert!(
            wants_window_events(&json!({"heartbeat_sec": 5}))
                && wants_window_events(&json!({"window_events": true}))
        );
        assert!(!wants_window_events(&json!({"window_events": false})));
        assert_eq!(
            (
                heartbeat_sec(&json!({"heartbeat_sec": 0})),
                heartbeat_sec(&json!({"heartbeat_sec": "x"})),
                heartbeat_sec(&json!({"heartbeat_sec": 0.5}))
            ),
            (5.0, 5.0, 0.5)
        );
    }

    #[test]
    fn a_new_notice_replaces_the_open_one_and_exit_closes_it() {
        let fake = FakeServer::new();
        fake.state()
            .commands
            .extend([show(7), show(8), json!({"type": "exit"})]);
        let w = Win::default();
        assert_eq!(runner(&fake, &w, 120.0).0.run(), EXIT_OK);
        assert_eq!(
            w.opened
                .lock()
                .unwrap()
                .iter()
                .map(|x| x.0)
                .collect::<Vec<_>>(),
            [7, 8]
        );
        assert!(*w.closed.lock().unwrap() >= 2);
    }

    #[test]
    fn a_rejected_heartbeat_stops_the_loop_with_3() {
        let fake = FakeServer::new();
        fake.state().hello = json!({"heartbeat_sec": 0.05});
        let w = Win::default();
        let r = runner(&fake, &w, 120.0).0;
        let t = std::thread::spawn(move || r.run());
        wait_until(|| paths(&fake).contains(&"/api/agent/heartbeat".to_string()));
        fake.state()
            .status_for
            .insert("/api/agent/heartbeat".into(), 401);
        assert_eq!(t.join().unwrap(), EXIT_REJECTED);
        assert!(*w.closed.lock().unwrap() >= 1);
    }

    #[test]
    fn a_closed_report_lost_to_an_outage_is_sent_again() {
        let fake = FakeServer::new();
        fake.state().commands.push_back(show(7));
        fake.state()
            .status_for
            .insert("/api/agent/notice/7/closed".into(), 503);
        let f2 = fake.clone();
        let (clock, _) = fake_clock(move |n| {
            if n == 1 {
                f2.state().status_for.remove("/api/agent/notice/7/closed");
            }
        });
        fake.on_answer("/api/agent/notice/7/closed", |s| {
            s.commands.push_back(json!({"type": "exit"}))
        });
        let w = Win {
            on_open: None,
            ..Win::default()
        };
        let r = runner(&fake, &w, 120.0).0.with_clock(clock);
        let w2 = w.clone();
        let t = std::thread::spawn(move || r.run());
        wait_until(|| w2.opened.lock().unwrap().len() == 1);
        w.user_closed.store(true, SeqCst);
        assert_eq!(t.join().unwrap(), EXIT_OK);
        assert_eq!(
            paths(&fake)
                .iter()
                .filter(|p| *p == "/api/agent/notice/7/closed")
                .count(),
            2
        );
    }

    #[test]
    fn an_unexpected_answer_or_command_is_logged_and_the_agent_keeps_running() {
        let fake = FakeServer::new();
        fake.state()
            .status_for
            .insert("/api/agent/next".into(), 422);
        let f2 = fake.clone();
        let (clock, _) = fake_clock(move |n| {
            if n == 1 {
                f2.state().status_for.remove("/api/agent/next");
            }
        });
        fake.state().commands.extend([
            json!({"type": "show_notice", "display_id": "x", "url": url(7)}),
            json!({"type": "exit"}),
        ]);
        let w = Win::default();
        let (r, lines) = runner(&fake, &w, 120.0);
        assert_eq!(r.with_clock(clock).run(), EXIT_OK);
        let all = lines.lock().unwrap().join("\n");
        assert!(
            all.contains("unexpected status 422")
                && all.contains(r#"command "show_notice" failed"#),
            "{all}"
        );
        assert!(w.opened.lock().unwrap().is_empty());
    }

    #[test]
    fn a_failing_window_open_does_not_end_the_agent() {
        let fake = FakeServer::new();
        fake.state()
            .commands
            .extend([show(7), json!({"type": "exit"})]);
        let w = Win {
            fail_open: true,
            ..Win::default()
        };
        let (r, lines) = runner(&fake, &w, 120.0);
        assert_eq!(r.run(), EXIT_OK);
        assert!(
            lines
                .lock()
                .unwrap()
                .iter()
                .any(|l| l.contains("no window"))
        );
    }

    #[test]
    fn a_server_without_the_key_is_dropped_at_once_and_nothing_is_opened() {
        let fake = FakeServer::new();
        fake.state().key = Some([0x22; 32]);
        fake.state().commands.push_back(show(7));
        let (clock, sleeps) = fake_clock(|_| {});
        let w = Win::default();
        assert_eq!(
            runner(&fake, &w, 120.0).0.with_clock(clock).run(),
            EXIT_UNVERIFIED
        );
        assert!(w.opened.lock().unwrap().is_empty() && sleeps.lock().unwrap().is_empty());
        assert_eq!(paths(&fake), ["/api/agent/hello"]);
    }

    #[test]
    fn a_rogue_that_takes_over_mid_run_gets_no_window_opened() {
        let fake = FakeServer::new();
        fake.state().commands.push_back(show(7));
        let f2 = fake.clone();
        let w = Win {
            on_open: Some(Arc::new(move || {
                let mut s = f2.state();
                s.key = None; // the service is gone; something else answers now
                // A well-formed notice of the configured server (review item 13): only the
                // missing proof keeps it from opening, not the URL filter.
                s.commands.push_back(show(8));
            })),
            ..Win::default()
        };
        assert_eq!(runner(&fake, &w, 120.0).0.run(), EXIT_UNVERIFIED);
        assert_eq!(*w.opened.lock().unwrap(), [(7, url(7))]);
        assert!(*w.closed.lock().unwrap() >= 1);
    }

    #[test]
    fn a_rejected_heartbeat_from_an_unproven_server_exits_5() {
        let fake = FakeServer::new();
        fake.state().hello = json!({"heartbeat_sec": 0.05});
        let r = runner(&fake, &Win::default(), 120.0).0;
        let t = std::thread::spawn(move || r.run());
        wait_until(|| paths(&fake).contains(&"/api/agent/heartbeat".to_string()));
        fake.state().key = None;
        assert_eq!(t.join().unwrap(), EXIT_UNVERIFIED);
    }

    #[test]
    fn only_notice_urls_of_the_configured_server_are_opened() {
        let fake = FakeServer::new();
        let bad = [
            json!("https://evil.example/notice#d=7&t=x"),
            json!("http://127.0.0.1:1/notice#d=7&t=x"),
            json!(format!("{BASE}/admin#x")),
            json!(format!("{BASE}/notice?d=7")),
            json!(format!("{BASE}@evil.example/notice#d=7")),
            json!(format!("{BASE}.evil/notice#d=7")),
            json!(7),
        ];
        for u in &bad {
            fake.state()
                .commands
                .push_back(json!({"type": "show_notice", "display_id": 7, "attempt": 1, "url": u}));
        }
        fake.state()
            .commands
            .extend([show(7), json!({"type": "exit"})]);
        let w = Win::default();
        let (r, lines) = runner(&fake, &w, 120.0);
        assert_eq!(r.run(), EXIT_OK);
        assert_eq!(*w.opened.lock().unwrap(), [(7, url(7))]);
        let all = lines.lock().unwrap().join("\n");
        assert_eq!(all.matches("refused notice url").count(), bad.len());
        assert!(!all.contains("t=x") && all.contains("#..."), "{all}");
    }

    // --- beyond the plan: F09, F10 (ported Python tests) and F29 --------------------------------

    #[test]
    fn exit_returns_at_once_although_the_heartbeat_waits_5_s() {
        // F09: the server kills an agent 2 s after `exit`; the heartbeat must not hold it up.
        let fake = FakeServer::new();
        assert_eq!(fake.state().hello["heartbeat_sec"], 5);
        fake.state().commands.push_back(json!({"type": "exit"}));
        let started = Instant::now();
        assert_eq!(runner(&fake, &Win::default(), 120.0).0.run(), EXIT_OK);
        assert!(
            started.elapsed() < Duration::from_secs(1),
            "{:?}",
            started.elapsed()
        );
        assert!(!paths(&fake).contains(&"/api/agent/heartbeat".to_string()));
    }

    #[test]
    fn the_hello_version_is_the_product_version() {
        let fake = FakeServer::new();
        fake.state().commands.push_back(json!({"type": "exit"}));
        runner(&fake, &Win::default(), 120.0).0.run();
        let hello = fake.state().requests[0].body.clone().unwrap();
        assert_eq!(hello["version"], PRODUCT);
    }

    #[test]
    fn a_heartbeat_without_an_idle_time_is_skipped_and_logged() {
        let fake = FakeServer::new();
        fake.state().hello = json!({"heartbeat_sec": 0.05});
        let (r, lines) = runner(&fake, &Win::default(), 120.0);
        let r = r.with_idle(Arc::new(|| None));
        let t = std::thread::spawn(move || r.run());
        wait_until(|| {
            lines
                .lock()
                .unwrap()
                .iter()
                .filter(|l| l.contains("heartbeat skipped"))
                .count()
                >= 2
        });
        fake.state().commands.push_back(json!({"type": "exit"}));
        assert_eq!(t.join().unwrap(), EXIT_OK);
        assert!(!paths(&fake).contains(&"/api/agent/heartbeat".to_string()));
    }

    #[test]
    fn an_unexpected_heartbeat_answer_is_logged_and_heartbeats_go_on() {
        let fake = FakeServer::new();
        fake.state().hello = json!({"heartbeat_sec": 0.05});
        fake.state()
            .status_for
            .insert("/api/agent/heartbeat".into(), 422);
        let (r, lines) = runner(&fake, &Win::default(), 120.0);
        let t = std::thread::spawn(move || r.run());
        wait_until(|| {
            paths(&fake)
                .iter()
                .filter(|p| *p == "/api/agent/heartbeat")
                .count()
                >= 2
        });
        fake.state().commands.push_back(json!({"type": "exit"}));
        assert_eq!(t.join().unwrap(), EXIT_OK);
        let all = lines.lock().unwrap().join("\n");
        assert!(
            all.contains("heartbeat failed: POST /api/agent/heartbeat: unexpected status 422"),
            "{all}"
        );
    }

    #[test]
    fn loop_outage_backs_off_then_recovers() {
        let fake = FakeServer::new();
        fake.state().commands.push_back(show(7));
        let f2 = fake.clone();
        let w = Win {
            on_open: Some(Arc::new(move || {
                f2.state().status_for.insert("/api/agent/next".into(), 503);
            })),
            ..Win::default()
        };
        let f3 = fake.clone();
        let (clock, sleeps) = fake_clock(move |n| {
            if n == 3 {
                let mut s = f3.state();
                s.status_for.remove("/api/agent/next");
                s.commands.push_back(json!({"type": "exit"}));
            }
        });
        assert_eq!(runner(&fake, &w, 120.0).0.with_clock(clock).run(), EXIT_OK);
        assert_eq!(*sleeps.lock().unwrap(), [1.0, 2.0, 4.0]);
        assert_eq!(*w.opened.lock().unwrap(), [(7, url(7))]);
    }

    #[test]
    fn loop_outage_past_the_limit_closes_the_window_and_exits_4() {
        let fake = FakeServer::new();
        fake.state().commands.push_back(show(7));
        let f2 = fake.clone();
        let w = Win {
            on_open: Some(Arc::new(move || {
                f2.state().status_for.insert("/api/agent/next".into(), 503);
            })),
            ..Win::default()
        };
        let (clock, sleeps) = fake_clock(|_| {});
        assert_eq!(
            runner(&fake, &w, 10.0).0.with_clock(clock).run(),
            EXIT_UNREACHABLE
        );
        assert_eq!(*sleeps.lock().unwrap(), [1.0, 2.0, 4.0, 8.0]);
        assert!(*w.closed.lock().unwrap() >= 1);
    }

    #[test]
    fn rejected_during_the_loop_closes_the_window_and_exits_3() {
        let fake = FakeServer::new();
        fake.state().commands.push_back(show(7));
        let f2 = fake.clone();
        let w = Win {
            on_open: Some(Arc::new(move || {
                f2.state().status_for.insert("/api/agent/next".into(), 403);
            })),
            ..Win::default()
        };
        assert_eq!(runner(&fake, &w, 120.0).0.run(), EXIT_REJECTED);
        assert_eq!(*w.opened.lock().unwrap(), [(7, url(7))]);
        assert!(*w.closed.lock().unwrap() >= 1);
    }

    #[test]
    fn a_wrong_id_close_and_an_unknown_command_change_nothing() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("u.url");
        let fake = FakeServer::new();
        fake.state().commands.extend([
            show(7),
            json!({"type": "close_notice", "display_id": 99}),
            json!({"type": "close_notice", "display_id": "7"}),
            json!({"type": "reboot"}),
            json!({"display_id": 7}),
            json!({"type": "show_notice", "display_id": "8", "attempt": 1, "url": url(8)}),
            json!({"type": "close_notice", "display_id": 8.0}),
            json!({"type": "exit"}),
        ]);
        let (log, lines) = logs();
        let r = AgentRunner::new(
            &cfg(120.0),
            client(&fake),
            Box::new(crate::agent::window::PrintWindow::new(file.clone())),
            2,
            1,
        )
        .with_idle(Arc::new(|| Some(0.0)))
        .with_log(log);
        assert_eq!(r.run(), EXIT_OK);
        let written = std::fs::read_to_string(&file).unwrap();
        assert_eq!(
            written.lines().collect::<Vec<_>>(),
            [
                format!("OPEN 7 {}", url(7)).as_str(),
                "CLOSE 7",
                &format!("OPEN 8 {}", url(8)),
                "CLOSE 8"
            ]
        );
        assert!(
            lines.lock().unwrap().is_empty(),
            "{:?}",
            lines.lock().unwrap()
        );
    }

    #[test]
    fn lenient_values_are_read_like_python() {
        let id = |v: Value| display_id(Some(&v));
        assert_eq!(id(json!(7)).unwrap(), 7);
        assert_eq!(id(json!(" 7 ")).unwrap(), 7);
        assert_eq!(id(json!(7.9)).unwrap(), 7);
        assert_eq!(id(json!(true)).unwrap(), 1);
        for bad in [
            json!("x"),
            json!("7.0"),
            json!(null),
            json!([7]),
            json!(1e300),
        ] {
            assert!(id(bad.clone()).is_err(), "{bad}");
        }
        assert!(display_id(None).is_err());
        assert!(same_id(Some(&json!(7)), 7) && same_id(Some(&json!(7.0)), 7));
        assert!(
            !same_id(Some(&json!("7")), 7) && !same_id(None, 7) && !same_id(Some(&json!(8)), 7)
        );
        assert_eq!(heartbeat_sec(&json!({"heartbeat_sec": "0.5"})), 0.5);
        assert_eq!(heartbeat_sec(&json!({"heartbeat_sec": null})), 5.0);
        assert_eq!(heartbeat_sec(&json!({"heartbeat_sec": -1})), 5.0);
        assert_eq!(heartbeat_sec(&json!({"heartbeat_sec": "inf"})), 5.0);
        assert_eq!(heartbeat_sec(&json!({})), 5.0);
        for off in [json!(null), json!(0), json!(""), json!([]), json!({})] {
            assert!(
                !wants_window_events(&json!({ "window_events": off })),
                "{off}"
            );
        }
        assert!(wants_window_events(&json!({"window_events": 1})));
    }

    #[test]
    fn refused_urls_are_logged_without_the_fragment_or_control_characters() {
        assert_eq!(
            shown_url(Some(&json!("https://evil.example/n#t=secret"))),
            r#""https://evil.example/n#...""#
        );
        assert_eq!(
            shown_url(Some(&json!("http://x/\nfake line"))),
            r#""http://x/\nfake line""#
        );
        assert_eq!(shown_url(Some(&json!(7))), "(a number)");
        assert_eq!(shown_url(None), "(none)");
    }

    #[test]
    fn idle_seconds_reads_this_session() {
        let idle = idle_seconds().expect("GetLastInputInfo works in a test process");
        assert!((0.0..4_294_967.296).contains(&idle), "{idle}");
    }
}
