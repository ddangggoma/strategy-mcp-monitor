"""HTTP client for the monitor's Local agent API (``urllib.request`` only).

The server proves itself on every answer (I1): each request carries a fresh random
``X-Agent-Nonce`` and an answer counts only with ``X-Server-Proof`` = HMAC-SHA256(nonce) under the
key the agent was launched with (``MCPMON_AGENT_SERVER_KEY``; it never goes over the wire). A
process that took the port while the service was down cannot produce it. 401/403 (we stop anyway)
and 5xx/no answer (nothing is acted on) need no proof.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import secrets
import threading
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

TOKEN_HEADER = "X-Agent-Token"
NONCE_HEADER = "X-Agent-Nonce"
PROOF_HEADER = "X-Server-Proof"


class ServerUnavailable(Exception):
    """Connection failure, timeout or 5xx: worth retrying."""


class AgentRejected(Exception):
    """401/403: this agent's token is no longer accepted."""


class ServerUnverified(AgentRejected):
    """The answer does not prove the launch key: whatever answers is not our service (I1). Stop."""


def proof_for(server_key: bytes, nonce: str) -> str:
    return hmac.new(server_key, nonce.encode("utf-8"), hashlib.sha256).hexdigest()


class ServerClient:
    def __init__(self, base_url: str, token: str, server_key: str, *, timeout: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._key = bytes.fromhex(server_key)
        self._timeout = timeout
        # No proxy, ever: the service is on loopback and the token must not leave the machine.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._verified = threading.Event()

    @property
    def verified(self) -> bool:
        """The last answer proved the server, and no outage was seen since."""
        return self._verified.is_set()

    def post(self, path: str, body: Mapping[str, Any] | None = None, *,
             verified_only: bool = False) -> dict[str, Any] | None:
        """``verified_only``: refuse (``ServerUnavailable``, nothing sent) until an answer proved the
        server since the last outage; for what must not reach an impostor (window titles)."""
        if verified_only and not self._verified.is_set():
            raise ServerUnavailable(f"POST {path}: the server has not proved itself since the last outage")
        return self._request("POST", path, body, self._timeout)

    def next(self, timeout: float) -> dict[str, Any] | None:
        return self._request("GET", f"/api/agent/next?timeout={timeout:g}", None, timeout + 10)

    def _check(self, what: str, nonce: str, proof: str | None) -> None:
        if proof is None or not proof.isascii() or not hmac.compare_digest(proof, proof_for(self._key, nonce)):
            self._verified.clear()
            raise ServerUnverified(f"{what}: the answer does not prove the server key")
        self._verified.set()

    def _request(self, method: str, path: str, body: Mapping[str, Any] | None, timeout: float) -> dict[str, Any] | None:
        what = f"{method} {path}"
        nonce = secrets.token_hex(16)
        headers = {TOKEN_HEADER: self._token, NONCE_HEADER: nonce}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self._base + path, data=data, headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                status, raw, proof = resp.status, resp.read(), resp.headers.get(PROOF_HEADER)
        except urllib.error.HTTPError as e:
            with e:
                status = e.code
                proof = e.headers.get(PROOF_HEADER) if e.headers is not None else None
            if status in (401, 403):
                # Unproven (may come from a squatter, R2); after a real one nothing is accepted anyway.
                self._verified.clear()
                raise AgentRejected(f"{what}: {status}") from None
            if status >= 500:
                self._verified.clear()
                raise ServerUnavailable(f"{what}: {status}") from None
            self._check(what, nonce, proof)
            raise RuntimeError(f"{what}: unexpected status {status}") from None
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            self._verified.clear()
            raise ServerUnavailable(f"{what}: {e}") from e
        self._check(what, nonce, proof)
        if status == 204 or not raw:
            return None
        try:
            result = json.loads(raw.decode("utf-8"))
        except ValueError:
            result = None
        if not isinstance(result, dict):
            raise RuntimeError(f"{what}: response is not a JSON object")
        return result
