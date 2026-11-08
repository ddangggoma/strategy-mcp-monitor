//! Test helpers for the agent: an in-memory stand-in for the monitor's `/api/agent/*` (the
//! answers of the Python agent's `tests/fake_server.py`), behind the client's [`Transport`].

use super::client::{NONCE_HEADER, RawResponse, ServerClient, TOKEN_HEADER, Transport, proof_for};
use serde_json::{Value, json};
use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};

/// The key the test agent is launched with (`"11"` × 32 in hex).
pub const KEY: [u8; 32] = [0x11; 32];
pub const BASE: &str = "http://127.0.0.1:8700";

#[derive(Clone, Debug, PartialEq)]
pub struct Req {
    pub method: String,
    pub path: String,
    pub query: String,
    pub body: Option<Value>,
    pub token: String,
    pub nonce: String,
}

type OnAnswer = Box<dyn FnOnce(&mut FakeState) + Send>;

pub struct FakeState {
    pub requests: Vec<Req>,
    pub commands: VecDeque<Value>,
    /// Path → the status every request to it gets.
    pub status_for: HashMap<String, u16>,
    pub hello: Value,
    /// `None`: answers without any proof (a process that grabbed the port).
    pub key: Option<[u8; 32]>,
    /// No answer at all (connection refused); nothing is recorded.
    pub down: bool,
    /// Path → how long every answer to it is held back (a stalling server); the request is
    /// recorded before the wait.
    pub delay_for: HashMap<String, Duration>,
    on_answer: Vec<(String, OnAnswer)>,
}

pub struct FakeServer {
    state: Mutex<FakeState>,
}

/// The hub's HELLO (`server/app/activity/agent_hub.py`).
pub fn default_hello() -> Value {
    json!({"heartbeat_sec": 5, "events_max": 200, "idle_threshold_sec": 300, "window_events": true})
}

impl FakeServer {
    pub fn new() -> Arc<FakeServer> {
        Arc::new(FakeServer {
            state: Mutex::new(FakeState {
                requests: Vec::new(),
                commands: VecDeque::new(),
                status_for: HashMap::new(),
                hello: default_hello(),
                key: Some(KEY),
                down: false,
                delay_for: HashMap::new(),
                on_answer: Vec::new(),
            }),
        })
    }

    pub fn state(&self) -> MutexGuard<'_, FakeState> {
        self.state.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Runs `f` once, right after the next successful (2xx) answer to `path`.
    pub fn on_answer(&self, path: &str, f: impl FnOnce(&mut FakeState) + Send + 'static) {
        self.state().on_answer.push((path.to_string(), Box::new(f)));
    }

    fn answer(
        &self,
        method: &str,
        url: &str,
        headers: &[(&'static str, String)],
        body: Option<Vec<u8>>,
    ) -> Result<RawResponse, String> {
        let header = |name: &str| {
            headers
                .iter()
                .find(|(n, _)| n.eq_ignore_ascii_case(name))
                .map(|(_, v)| v.clone())
                .unwrap_or_default()
        };
        let rest = url
            .strip_prefix(BASE)
            .ok_or_else(|| format!("the fake server only answers {BASE}"))?;
        let (path, query) = rest.split_once('?').unwrap_or((rest, ""));
        let nonce = header(NONCE_HEADER);
        let mut idle = false;
        let mut st = self.state();
        if st.down {
            return Err("connection refused (the fake server is down)".into());
        }
        st.requests.push(Req {
            method: method.into(),
            path: path.into(),
            query: query.into(),
            body: body.map(|b| serde_json::from_slice(&b).expect("the agent sends JSON")),
            token: header(TOKEN_HEADER),
            nonce: nonce.clone(),
        });
        let (status, payload) = if let Some(&forced) = st.status_for.get(path) {
            (forced, (forced >= 400).then(|| json!({"error": "forced"})))
        } else if method == "GET" && path == "/api/agent/next" {
            match st.commands.pop_front() {
                Some(cmd) => (200, Some(cmd)),
                None => {
                    idle = true;
                    (204, None)
                }
            }
        } else if method == "POST" && path == "/api/agent/hello" {
            (200, Some(st.hello.clone()))
        } else if method == "POST" {
            (204, None)
        } else {
            (404, Some(json!({"error": "not_found"})))
        };
        let proof = match st.key {
            Some(key) if status != 401 && status != 403 => Some(proof_for(&key, &nonce)),
            _ => None,
        };
        if (200..300).contains(&status)
            && let Some(i) = st.on_answer.iter().position(|(p, _)| p == path)
        {
            let (_, f) = st.on_answer.remove(i);
            f(&mut st);
        }
        let delay = st.delay_for.get(path).copied();
        drop(st);
        if idle {
            std::thread::sleep(Duration::from_millis(5));
        }
        if let Some(delay) = delay {
            std::thread::sleep(delay);
        }
        Ok(RawResponse {
            status,
            proof,
            body: payload.map_or_else(Vec::new, |p| serde_json::to_vec(&p).unwrap()),
        })
    }
}

/// [`FakeServer`] as the client's transport.
pub struct FakeTransport(pub Arc<FakeServer>);

impl Transport for FakeTransport {
    fn send(
        &self,
        method: &str,
        url: &str,
        headers: &[(&'static str, String)],
        body: Option<Vec<u8>>,
        _timeout: Duration,
    ) -> Result<RawResponse, String> {
        self.0.answer(method, url, headers, body)
    }
}

/// A client of `fake` at [`BASE`], token `tok`, key [`KEY`].
pub fn client(fake: &Arc<FakeServer>) -> Arc<ServerClient> {
    Arc::new(ServerClient::new(
        BASE,
        "tok",
        KEY,
        Box::new(FakeTransport(fake.clone())),
    ))
}

/// Waits up to 5 s (polling every 20 ms) for `f` to hold; panics if it never does.
pub fn wait_until(f: impl Fn() -> bool) {
    let end = Instant::now() + Duration::from_secs(5);
    while !f() {
        assert!(Instant::now() < end, "condition not met within 5 s");
        std::thread::sleep(Duration::from_millis(20));
    }
}
