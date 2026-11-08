//! HTTP client for the monitor's Local agent API (Python `mcp_agent.client`).
//!
//! The server proves itself on every answer (Plan 4 I1): each request carries a fresh random
//! `X-Agent-Nonce`, and an answer counts only with `X-Server-Proof` = HMAC-SHA256(nonce) under the
//! key the agent was launched with (it never goes over the wire). A process that took the port
//! while the service was down cannot produce it. 401/403 (we stop anyway) and 5xx/no answer
//! (nothing is acted on) need no proof. The token is sent only to the configured server, never
//! through a proxy, and is never part of an error message.

use hmac::{Hmac, KeyInit, Mac};
use serde_json::Value;
use sha2::Sha256;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

pub const TOKEN_HEADER: &str = "X-Agent-Token";
pub const NONCE_HEADER: &str = "X-Agent-Nonce";
pub const PROOF_HEADER: &str = "X-Server-Proof";
pub const DEFAULT_TIMEOUT_SEC: f64 = 10.0;
/// `next` waits this much longer than the long poll it asks for.
pub const NEXT_EXTRA_SEC: f64 = 10.0;

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug)]
pub enum ClientError {
    /// Connection failure, timeout or 5xx: worth retrying.
    Unavailable(String),
    /// 401/403: this agent's token is no longer accepted.
    Rejected(String),
    /// The answer does not prove the launch key: whatever answers is not our service. Stop.
    Unverified(String),
    /// A proven answer the agent cannot use (another status, not a JSON object).
    Unexpected(String),
}

impl ClientError {
    /// `Rejected` or `Unverified` (Python: `ServerUnverified` is an `AgentRejected`).
    pub fn is_rejected(&self) -> bool {
        matches!(self, ClientError::Rejected(_) | ClientError::Unverified(_))
    }
}

impl std::fmt::Display for ClientError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ClientError::Unavailable(m)
            | ClientError::Rejected(m)
            | ClientError::Unverified(m)
            | ClientError::Unexpected(m) => f.write_str(m),
        }
    }
}

pub struct RawResponse {
    pub status: u16,
    /// The `X-Server-Proof` header as sent (bytes that are not UTF-8 become U+FFFD).
    pub proof: Option<String>,
    pub body: Vec<u8>,
}

/// One HTTP exchange. `Err` = no answer (connection failure, timeout), as a message without the
/// token.
pub trait Transport: Send + Sync {
    fn send(
        &self,
        method: &str,
        url: &str,
        headers: &[(&'static str, String)],
        body: Option<Vec<u8>>,
        timeout: Duration,
    ) -> Result<RawResponse, String>;
}

/// Plain HTTP over `ureq` (no TLS: the server is on loopback). Proxy settings from the
/// environment are ignored (the token must not leave the PC), redirects are not followed and
/// every status is an answer.
pub struct UreqTransport {
    agent: ureq::Agent,
}

impl UreqTransport {
    pub fn new() -> UreqTransport {
        let config = ureq::Agent::config_builder()
            .proxy(None)
            .http_status_as_error(false)
            .max_redirects(0)
            .build();
        UreqTransport {
            agent: ureq::Agent::new_with_config(config),
        }
    }

    fn run<S: ureq::AsSendBody>(
        &self,
        request: ureq::http::Request<S>,
        timeout: Duration,
    ) -> Result<RawResponse, String> {
        let request = self
            .agent
            .configure_request(request)
            .timeout_global(Some(timeout))
            .build();
        let mut response = self.agent.run(request).map_err(|e| e.to_string())?;
        let status = response.status().as_u16();
        let proof = response
            .headers()
            .get(PROOF_HEADER)
            .map(|v| String::from_utf8_lossy(v.as_bytes()).into_owned());
        let body = response
            .body_mut()
            .read_to_vec()
            .map_err(|e| e.to_string())?;
        Ok(RawResponse {
            status,
            proof,
            body,
        })
    }
}

impl Default for UreqTransport {
    fn default() -> Self {
        UreqTransport::new()
    }
}

impl Transport for UreqTransport {
    fn send(
        &self,
        method: &str,
        url: &str,
        headers: &[(&'static str, String)],
        body: Option<Vec<u8>>,
        timeout: Duration,
    ) -> Result<RawResponse, String> {
        let mut builder = ureq::http::Request::builder().method(method).uri(url);
        for (name, value) in headers {
            builder = builder.header(*name, value.as_str());
        }
        match body {
            Some(bytes) => self.run(builder.body(bytes).map_err(|e| e.to_string())?, timeout),
            None => self.run(builder.body(()).map_err(|e| e.to_string())?, timeout),
        }
    }
}

/// HMAC-SHA256 of `nonce` under `key`, lower-case hex (the server's `server_proof`).
pub fn proof_for(key: &[u8], nonce: &str) -> String {
    let mut mac = HmacSha256::new_from_slice(key).expect("HMAC takes a key of any length");
    mac.update(nonce.as_bytes());
    hex::encode(mac.finalize().into_bytes())
}

fn try_nonce() -> Result<String, getrandom::Error> {
    let mut bytes = [0u8; 16];
    getrandom::fill(&mut bytes)?;
    Ok(hex::encode(bytes))
}

/// 16 random bytes as 32 lower-case hex digits.
pub fn new_nonce() -> String {
    try_nonce().expect("the system random number generator failed")
}

/// Python `%g`: six significant digits, no trailing zeros (`25.0` → `25`, `0.5` → `0.5`).
pub fn format_g(x: f64) -> String {
    if x == 0.0 {
        return "0".into();
    }
    if !x.is_finite() {
        return if x.is_nan() {
            "nan".into()
        } else if x > 0.0 {
            "inf".into()
        } else {
            "-inf".into()
        };
    }
    let sci = format!("{x:.5e}");
    let (mantissa, exp) = sci.split_once('e').expect("{:e} has an exponent");
    let exp: i32 = exp.parse().expect("{:e} exponent is a number");
    let trim = |s: &str| -> String {
        if s.contains('.') {
            s.trim_end_matches('0').trim_end_matches('.').to_string()
        } else {
            s.to_string()
        }
    };
    if !(-4..6).contains(&exp) {
        let sign = if exp < 0 { '-' } else { '+' };
        format!("{}e{sign}{:02}", trim(mantissa), exp.abs())
    } else {
        trim(&format!("{x:.*}", (5 - exp) as usize))
    }
}

fn duration(sec: f64) -> Duration {
    Duration::try_from_secs_f64(sec).unwrap_or(Duration::from_secs_f64(DEFAULT_TIMEOUT_SEC))
}

pub struct ServerClient {
    base: String,
    token: String,
    key: [u8; 32],
    transport: Box<dyn Transport>,
    timeout: Duration,
    verified: AtomicBool,
}

impl ServerClient {
    pub fn new(
        base: impl Into<String>,
        token: impl Into<String>,
        key: [u8; 32],
        transport: Box<dyn Transport>,
    ) -> ServerClient {
        ServerClient {
            base: base.into().trim_end_matches('/').to_string(),
            token: token.into(),
            key,
            transport,
            timeout: duration(DEFAULT_TIMEOUT_SEC),
            verified: AtomicBool::new(false),
        }
    }

    /// The last answer proved the server, and no outage or unproven 401/403 was seen since.
    pub fn verified(&self) -> bool {
        self.verified.load(Ordering::SeqCst)
    }

    /// `verified_only`: refuse (`Unavailable`, nothing sent) until an answer proved the server
    /// since the last outage; for what must not reach an impostor (window titles).
    pub fn post(
        &self,
        path: &str,
        body: Option<&Value>,
        verified_only: bool,
    ) -> Result<Option<Value>, ClientError> {
        if verified_only && !self.verified() {
            return Err(ClientError::Unavailable(format!(
                "POST {path}: the server has not proved itself since the last outage"
            )));
        }
        self.request("POST", path, body, self.timeout)
    }

    /// `GET /api/agent/next?timeout=<%g>`: the next command (long poll), or `None`.
    pub fn next(&self, timeout_sec: f64) -> Result<Option<Value>, ClientError> {
        let path = format!("/api/agent/next?timeout={}", format_g(timeout_sec));
        self.request("GET", &path, None, duration(timeout_sec + NEXT_EXTRA_SEC))
    }

    fn distrust(&self) {
        self.verified.store(false, Ordering::SeqCst);
    }

    /// Constant-time check of the proof (`Mac::verify_slice`). Like Python's `compare_digest`
    /// against the lower-case hex digest, the proof must be exactly 64 lower-case hex digits.
    fn check(&self, what: &str, nonce: &str, proof: Option<&str>) -> Result<(), ClientError> {
        let proven = proof.is_some_and(|p| {
            p.len() == 64
                && p.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
                && hex::decode(p).is_ok_and(|bytes| {
                    let mut mac = HmacSha256::new_from_slice(&self.key)
                        .expect("HMAC takes a key of any length");
                    mac.update(nonce.as_bytes());
                    mac.verify_slice(&bytes).is_ok()
                })
        });
        if !proven {
            self.distrust();
            return Err(ClientError::Unverified(format!(
                "{what}: the answer does not prove the server key"
            )));
        }
        self.verified.store(true, Ordering::SeqCst);
        Ok(())
    }

    fn request(
        &self,
        method: &str,
        path: &str,
        body: Option<&Value>,
        timeout: Duration,
    ) -> Result<Option<Value>, ClientError> {
        let what = format!("{method} {path}");
        let nonce = match try_nonce() {
            Ok(nonce) => nonce,
            Err(e) => {
                self.distrust();
                return Err(ClientError::Unavailable(format!(
                    "{what}: no random nonce: {e}"
                )));
            }
        };
        let mut headers = vec![
            (TOKEN_HEADER, self.token.clone()),
            (NONCE_HEADER, nonce.clone()),
        ];
        let data = match body {
            Some(value) => {
                headers.push(("Content-Type", "application/json".to_string()));
                Some(serde_json::to_vec(value).map_err(|e| {
                    ClientError::Unexpected(format!("{what}: the body is not JSON: {e}"))
                })?)
            }
            None => None,
        };
        let url = format!("{}{path}", self.base);
        let answer = match self.transport.send(method, &url, &headers, data, timeout) {
            Ok(answer) => answer,
            Err(e) => {
                self.distrust();
                return Err(ClientError::Unavailable(format!("{what}: {e}")));
            }
        };
        let status = answer.status;
        if status == 401 || status == 403 {
            // Unproven (may come from a squatter, R2); after a real one nothing is accepted anyway.
            self.distrust();
            return Err(ClientError::Rejected(format!("{what}: {status}")));
        }
        if status >= 500 {
            self.distrust();
            return Err(ClientError::Unavailable(format!("{what}: {status}")));
        }
        self.check(&what, &nonce, answer.proof.as_deref())?;
        if !(200..300).contains(&status) {
            return Err(ClientError::Unexpected(format!(
                "{what}: unexpected status {status}"
            )));
        }
        if status == 204 || answer.body.is_empty() {
            return Ok(None);
        }
        match serde_json::from_slice::<Value>(&answer.body) {
            Ok(value @ Value::Object(_)) => Ok(Some(value)),
            _ => Err(ClientError::Unexpected(format!(
                "{what}: response is not a JSON object"
            ))),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::testkit::*;
    use serde_json::json;

    #[test]
    fn proof_matches_the_python_vectors() {
        assert_eq!(
            proof_for(&[0x11; 32], "abc"),
            "8094a4aa0311ceadd62bd4b17fa76cb0066cff4f125cbfc64dea5bab2493f2cd"
        );
        assert_eq!(
            proof_for(&[0x11; 32], "00112233445566778899aabbccddeeff"),
            "6e954b5b533f380aef1f7121d19df77241bf24c1b258dea69a65d4dbdb0b7e5f"
        );
        let (a, b) = (new_nonce(), new_nonce());
        assert!(a.len() == 32 && a != b && a.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn sends_the_token_a_fresh_nonce_and_json_and_needs_the_proof() {
        let fake = FakeServer::new();
        let c = client(&fake);
        assert!(!c.verified());
        c.post(
            "/api/agent/heartbeat",
            Some(&json!({"idle_sec": 1, "locked": null})),
            false,
        )
        .unwrap();
        c.post("/api/agent/heartbeat", Some(&json!({})), false)
            .unwrap();
        let reqs = fake.state().requests.clone();
        assert_eq!(
            (reqs[0].token.as_str(), reqs[0].body.clone()),
            ("tok", Some(json!({"idle_sec": 1, "locked": null})))
        );
        assert!(reqs[0].nonce != reqs[1].nonce && reqs[0].nonce.len() == 32 && c.verified());
    }

    #[test]
    fn refuses_an_answer_without_a_valid_proof() {
        let fake = FakeServer::new();
        let c = client(&fake);
        c.post("/api/agent/heartbeat", Some(&json!({})), false)
            .unwrap();
        for key in [None, Some([0x22; 32])] {
            fake.state().key = key;
            assert!(matches!(
                c.post("/api/agent/hello", Some(&json!({})), false),
                Err(ClientError::Unverified(_))
            ));
            assert!(!c.verified());
            assert!(matches!(c.next(0.0), Err(ClientError::Unverified(_))));
        }
        fake.state()
            .status_for
            .insert("/api/agent/next".into(), 404);
        assert!(matches!(c.next(0.0), Err(ClientError::Unverified(_)))); // an unproven 4xx: not our service either
        assert!(ClientError::Unverified(String::new()).is_rejected());
    }

    #[test]
    fn statuses_map_like_the_python_agent() {
        let fake = FakeServer::new();
        let c = client(&fake);
        fake.state().key = None;
        fake.state()
            .status_for
            .insert("/api/agent/heartbeat".into(), 401);
        assert!(matches!(
            c.post("/api/agent/heartbeat", Some(&json!({})), false),
            Err(ClientError::Rejected(_))
        ));
        fake.state()
            .status_for
            .insert("/api/agent/heartbeat".into(), 503);
        assert!(matches!(
            c.post("/api/agent/heartbeat", Some(&json!({})), false),
            Err(ClientError::Unavailable(_))
        ));
        fake.state().key = Some(KEY);
        fake.state()
            .status_for
            .insert("/api/agent/heartbeat".into(), 422);
        match c.post("/api/agent/heartbeat", Some(&json!({})), false) {
            Err(ClientError::Unexpected(m)) => assert!(m.contains("unexpected status 422"), "{m}"),
            other => panic!("{other:?}"),
        }
        fake.state().hello = json!([1, 2]);
        assert!(matches!(
            c.post("/api/agent/hello", Some(&json!({})), false),
            Err(ClientError::Unexpected(_))
        ));
        fake.state().down = true;
        assert!(matches!(c.next(0.0), Err(ClientError::Unavailable(_))));
    }

    #[test]
    fn sensitive_posts_wait_for_a_proven_answer_after_an_outage() {
        let fake = FakeServer::new();
        let c = client(&fake);
        assert!(matches!(
            c.post("/api/agent/events", Some(&json!({"events": []})), true),
            Err(ClientError::Unavailable(_))
        ));
        assert!(fake.state().requests.is_empty());
        c.next(0.0).unwrap();
        assert_eq!(
            c.post("/api/agent/events", Some(&json!({"events": []})), true)
                .unwrap(),
            None
        );
        fake.state()
            .status_for
            .insert("/api/agent/next".into(), 503);
        assert!(c.next(0.0).is_err());
        assert!(matches!(
            c.post("/api/agent/events", Some(&json!({"events": []})), true),
            Err(ClientError::Unavailable(_))
        ));
        assert_eq!(
            fake.state()
                .requests
                .iter()
                .filter(|r| r.path == "/api/agent/events")
                .count(),
            1
        );
    }

    #[test]
    fn an_unproven_401_after_a_proven_answer_drops_the_trust() {
        let fake = FakeServer::new();
        let c = client(&fake);
        c.next(0.0).unwrap();
        assert!(c.verified());
        for status in [401, 403] {
            fake.state().key = None;
            fake.state()
                .status_for
                .insert("/api/agent/heartbeat".into(), status);
            assert!(matches!(
                c.post("/api/agent/heartbeat", Some(&json!({})), false),
                Err(ClientError::Rejected(_))
            ));
            assert!(!c.verified());
            assert!(matches!(
                c.post("/api/agent/events", Some(&json!({"events": []})), true),
                Err(ClientError::Unavailable(_))
            ));
            fake.state().key = Some(KEY);
            c.next(0.0).unwrap();
        }
        assert!(
            !fake
                .state()
                .requests
                .iter()
                .any(|r| r.path == "/api/agent/events")
        );
    }

    #[test]
    fn next_sends_the_timeout_like_python() {
        let fake = FakeServer::new();
        let c = client(&fake);
        for t in [25.0, 2.0, 0.5, 0.0] {
            c.next(t).unwrap();
        }
        let q: Vec<String> = fake
            .state()
            .requests
            .iter()
            .map(|r| r.query.clone())
            .collect();
        assert_eq!(q, ["timeout=25", "timeout=2", "timeout=0.5", "timeout=0"]);
    }

    // --- beyond the plan ----------------------------------------------------------------------

    #[test]
    fn format_g_is_python_percent_g() {
        for (x, g) in [
            (25.0, "25"),
            (2.0, "2"),
            (0.5, "0.5"),
            (0.0, "0"),
            (2.5, "2.5"),
            (30.123456789, "30.1235"),
            (0.0001, "0.0001"),
            (0.00001, "1e-05"),
            (1234567.0, "1.23457e+06"),
            (999999.7, "1e+06"),
            (100000.0, "100000"),
            (-1.5, "-1.5"),
        ] {
            assert_eq!(format_g(x), g, "{x}");
        }
    }

    #[test]
    fn a_proven_answer_returns_the_command_and_an_empty_one_is_none() {
        let fake = FakeServer::new();
        let c = client(&fake);
        fake.state().commands.push_back(json!({"type": "exit"}));
        assert_eq!(c.next(25.0).unwrap(), Some(json!({"type": "exit"})));
        assert_eq!(c.next(25.0).unwrap(), None);
        let hello = c.post("/api/agent/hello", Some(&json!({})), false).unwrap();
        assert_eq!(hello, Some(fake.state().hello.clone()));
        let r = fake.state().requests[0].clone();
        assert_eq!(
            (r.method.as_str(), r.path.as_str(), r.body),
            ("GET", "/api/agent/next", None)
        );
    }

    #[test]
    fn a_proof_in_upper_case_or_with_extra_bytes_is_not_a_proof() {
        struct Answer(fn(&str) -> String);
        impl Transport for Answer {
            fn send(
                &self,
                _: &str,
                _: &str,
                headers: &[(&'static str, String)],
                _: Option<Vec<u8>>,
                _: Duration,
            ) -> Result<RawResponse, String> {
                let nonce = &headers.iter().find(|h| h.0 == NONCE_HEADER).unwrap().1;
                Ok(RawResponse {
                    status: 204,
                    proof: Some((self.0)(&proof_for(&KEY, nonce))),
                    body: vec![],
                })
            }
        }
        let good: fn(&str) -> String = |p| p.to_string();
        let bad: [fn(&str) -> String; 5] = [
            |p| p.to_uppercase(),
            |p| format!("{p}00"),
            |p| p[..62].to_string(),
            |p| format!(" {}", &p[1..]),
            |p| format!("{}\u{FFFD}", &p[..61]),
        ];
        let c = ServerClient::new("http://127.0.0.1:8700", "tok", KEY, Box::new(Answer(good)));
        assert!(c.next(0.0).is_ok() && c.verified());
        for f in bad {
            let c = ServerClient::new("http://127.0.0.1:8700", "tok", KEY, Box::new(Answer(f)));
            assert!(matches!(c.next(0.0), Err(ClientError::Unverified(_))));
            assert!(!c.verified());
        }
    }

    #[test]
    fn errors_never_show_the_token() {
        let fake = FakeServer::new();
        let c = ServerClient::new(
            "http://127.0.0.1:8700/",
            "tok_SECRET",
            KEY,
            Box::new(FakeTransport(fake.clone())),
        );
        let mut seen = Vec::new();
        for (status, key) in [(401, None), (503, None), (422, Some(KEY)), (404, None)] {
            fake.state().key = key;
            fake.state()
                .status_for
                .insert("/api/agent/hello".into(), status);
            seen.push(
                c.post("/api/agent/hello", Some(&json!({})), false)
                    .unwrap_err()
                    .to_string(),
            );
        }
        fake.state().down = true;
        seen.push(c.next(0.0).unwrap_err().to_string());
        assert!(seen.iter().all(|m| !m.contains("tok_SECRET")), "{seen:?}");
        assert_eq!(fake.state().requests[0].token, "tok_SECRET");
    }

    /// A one-shot HTTP server on 127.0.0.1:0 that answers 204 with a proof and hands back the raw
    /// request it read.
    fn one_shot_server() -> (String, std::thread::JoinHandle<String>) {
        use std::io::{BufRead, BufReader, Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let handle = std::thread::spawn(move || {
            let (stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(10)))
                .unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            let mut head = String::new();
            let mut length = 0usize;
            let mut nonce = String::new();
            loop {
                let mut line = String::new();
                reader.read_line(&mut line).unwrap();
                if let Some((name, value)) = line.trim_end().split_once(':') {
                    if name.eq_ignore_ascii_case("content-length") {
                        length = value.trim().parse().unwrap();
                    }
                    if name.eq_ignore_ascii_case(NONCE_HEADER) {
                        nonce = value.trim().to_string();
                    }
                }
                head.push_str(&line);
                if line == "\r\n" || line.is_empty() {
                    break;
                }
            }
            let mut body = vec![0; length];
            reader.read_exact(&mut body).unwrap();
            let answer = format!(
                "HTTP/1.1 204 No Content\r\n{PROOF_HEADER}: {}\r\nConnection: close\r\n\r\n",
                proof_for(&KEY, &nonce)
            );
            (&stream).write_all(answer.as_bytes()).unwrap();
            head + &String::from_utf8(body).unwrap()
        });
        (url, handle)
    }

    #[test]
    fn the_real_transport_sends_json_only_with_a_body() {
        let (url, server) = one_shot_server();
        let c = ServerClient::new(url, "tok", KEY, Box::new(UreqTransport::new()));
        assert_eq!(
            c.post("/api/agent/notice/7/closed", None, false).unwrap(),
            None
        );
        let raw = server.join().unwrap().to_ascii_lowercase();
        assert!(
            raw.starts_with("post /api/agent/notice/7/closed http/1.1\r\n"),
            "{raw}"
        );
        assert!(raw.contains("\r\nx-agent-token: tok\r\n") && raw.contains("\r\nx-agent-nonce: "));
        assert!(!raw.contains("content-type"), "{raw}");
        assert!(c.verified());

        let (url, server) = one_shot_server();
        let c = ServerClient::new(url, "tok", KEY, Box::new(UreqTransport::new()));
        c.post(
            "/api/agent/heartbeat",
            Some(&json!({"idle_sec": 3, "locked": null})),
            false,
        )
        .unwrap();
        let raw = server.join().unwrap();
        assert!(
            raw.to_ascii_lowercase()
                .contains("\r\ncontent-type: application/json\r\n"),
            "{raw}"
        );
        let body = raw.split("\r\n\r\n").nth(1).unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(body).unwrap(),
            json!({"idle_sec": 3, "locked": null})
        );
    }

    #[test]
    fn nothing_listening_is_unavailable() {
        let port = {
            let l = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
            l.local_addr().unwrap().port()
        };
        let c = ServerClient::new(
            format!("http://127.0.0.1:{port}"),
            "t",
            KEY,
            Box::new(UreqTransport::new()),
        );
        assert!(matches!(
            c.post("/api/agent/hello", Some(&json!({})), false),
            Err(ClientError::Unavailable(_))
        ));
    }

    #[test]
    fn a_server_that_never_answers_is_unavailable_after_the_timeout() {
        // Accepts the connection (backlog) but never answers.
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let t = UreqTransport::new();
        let started = std::time::Instant::now();
        let result = t.send(
            "POST",
            &format!("{url}/api/agent/hello"),
            &[],
            Some(b"{}".to_vec()),
            Duration::from_millis(300),
        );
        assert!(result.is_err());
        assert!(started.elapsed() < Duration::from_secs(5));
        drop(listener);
    }
}
