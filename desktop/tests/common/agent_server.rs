//! A stand-in for the monitor's Local agent API on a real socket (`127.0.0.1:0`): one thread per
//! connection, one request per connection (`Connection: close`). It answers like the unit tests'
//! `testkit::FakeServer` (and the Python agent's `tests/fake_server.py`): `next` → the next queued
//! command (200) or, after 5 ms, 204; `hello` → 200 + the hub's HELLO; any other POST → 204;
//! pages from `serve_page` → 200 HTML; anything else → 404. With a key, every answer except
//! 401/403 carries `X-Server-Proof`, made with `mcp_monitor::agent::client::proof_for`.

use mcp_monitor::agent::client::{NONCE_HEADER, PROOF_HEADER, TOKEN_HEADER, proof_for};
use serde_json::{Value, json};
use std::collections::{HashMap, VecDeque};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

#[derive(Clone, Debug)]
pub struct Req {
    pub method: String,
    pub path: String,
    /// `Value::Null` without a body.
    pub body: Value,
    pub token: String,
}

struct Shared {
    key: Option<[u8; 32]>,
    hello: Value,
    commands: VecDeque<Value>,
    requests: Vec<Req>,
    pages: HashMap<String, String>,
}

pub struct AgentServer {
    addr: SocketAddr,
    shared: Arc<Mutex<Shared>>,
    stop: Arc<AtomicBool>,
}

impl AgentServer {
    pub fn start(key: Option<[u8; 32]>) -> AgentServer {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        let shared = Arc::new(Mutex::new(Shared {
            key,
            hello: json!({"heartbeat_sec": 5, "events_max": 200, "idle_threshold_sec": 300, "window_events": true}),
            commands: VecDeque::new(),
            requests: Vec::new(),
            pages: HashMap::new(),
        }));
        let stop = Arc::new(AtomicBool::new(false));
        let (s, st) = (shared.clone(), stop.clone());
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                if st.load(Ordering::SeqCst) {
                    break;
                }
                let Ok(stream) = stream else { continue };
                let s = s.clone();
                std::thread::spawn(move || {
                    let _ = handle(stream, &s);
                });
            }
        });
        AgentServer { addr, shared, stop }
    }

    /// `http://127.0.0.1:<port>`
    pub fn url(&self) -> String {
        format!("http://{}", self.addr)
    }

    pub fn queue(&self, command: Value) {
        self.lock().commands.push_back(command);
    }

    pub fn requests(&self) -> Vec<Req> {
        self.lock().requests.clone()
    }

    /// `GET <path>` answers `html` (for the WebView tests of Tasks 11 and 12).
    pub fn serve_page(&self, path: &str, html: &str) {
        self.lock().pages.insert(path.to_string(), html.to_string());
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Shared> {
        self.shared.lock().unwrap_or_else(|e| e.into_inner())
    }
}

impl Drop for AgentServer {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        // Wake the accept loop so it sees the stop.
        let _ = TcpStream::connect_timeout(&self.addr, Duration::from_secs(1));
    }
}

fn reason(status: u16) -> &'static str {
    match status {
        200 => "OK",
        204 => "No Content",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        _ => "Status",
    }
}

fn handle(stream: TcpStream, shared: &Mutex<Shared>) -> std::io::Result<()> {
    stream.set_read_timeout(Some(Duration::from_secs(10)))?;
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut request_line = String::new();
    reader.read_line(&mut request_line)?;
    let mut parts = request_line.split_whitespace();
    let (Some(method), Some(target)) = (parts.next(), parts.next()) else {
        return Ok(());
    };
    let (method, target) = (method.to_string(), target.to_string());
    let mut headers = HashMap::new();
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line)? == 0 || line == "\r\n" || line == "\n" {
            break;
        }
        if let Some((name, value)) = line.trim_end().split_once(':') {
            headers.insert(name.trim().to_ascii_lowercase(), value.trim().to_string());
        }
    }
    let length: usize = headers
        .get("content-length")
        .and_then(|v| v.parse().ok())
        .unwrap_or(0);
    let mut raw = vec![0; length];
    reader.read_exact(&mut raw)?;
    let header = |name: &str| {
        headers
            .get(&name.to_ascii_lowercase())
            .cloned()
            .unwrap_or_default()
    };
    let path = target.split('?').next().unwrap_or_default().to_string();
    let nonce = header(NONCE_HEADER);

    let (status, content_type, body, proof) = {
        let mut s = shared.lock().unwrap_or_else(|e| e.into_inner());
        s.requests.push(Req {
            method: method.clone(),
            path: path.clone(),
            body: if raw.is_empty() {
                Value::Null
            } else {
                serde_json::from_slice(&raw).unwrap_or(Value::Null)
            },
            token: header(TOKEN_HEADER),
        });
        let json_body = |v: &Value| Some(("application/json", serde_json::to_vec(v).unwrap()));
        let (status, payload) = if method == "GET" && path == "/api/agent/next" {
            match s.commands.pop_front() {
                Some(cmd) => (200, json_body(&cmd)),
                None => (204, None),
            }
        } else if method == "POST" && path == "/api/agent/hello" {
            (200, json_body(&s.hello))
        } else if method == "POST" {
            (204, None)
        } else if let Some(html) = s.pages.get(&path) {
            (
                200,
                Some(("text/html; charset=utf-8", html.clone().into_bytes())),
            )
        } else {
            (404, json_body(&json!({"error": "not_found"})))
        };
        let proof = match s.key {
            Some(key) if status != 401 && status != 403 && !nonce.is_empty() => {
                Some(proof_for(&key, &nonce))
            }
            _ => None,
        };
        let (content_type, body) = payload.unzip();
        (status, content_type, body.unwrap_or_default(), proof)
    };
    if status == 204 && method == "GET" {
        std::thread::sleep(Duration::from_millis(5));
    }
    let mut answer = format!("HTTP/1.1 {status} {}\r\n", reason(status));
    if let Some(proof) = proof {
        answer.push_str(&format!("{PROOF_HEADER}: {proof}\r\n"));
    }
    if let Some(ct) = content_type {
        answer.push_str(&format!("Content-Type: {ct}\r\n"));
    }
    if status != 204 {
        answer.push_str(&format!("Content-Length: {}\r\n", body.len()));
    }
    answer.push_str("Connection: close\r\n\r\n");
    let mut out = stream;
    out.write_all(answer.as_bytes())?;
    out.write_all(&body)?;
    out.flush()
}
