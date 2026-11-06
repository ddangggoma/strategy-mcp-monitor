"""HTTP client for the monitor's Local agent API (``urllib.request`` only)."""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

TOKEN_HEADER = "X-Agent-Token"


class ServerUnavailable(Exception):
    """Connection failure, timeout or 5xx: worth retrying."""


class AgentRejected(Exception):
    """401/403: this agent's token is no longer accepted."""


class ServerClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        # No proxy, ever: the service is on loopback and the token must not leave the machine.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def post(self, path: str, body: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        return self._request("POST", path, body, self._timeout)

    def next(self, timeout: float) -> dict[str, Any] | None:
        return self._request("GET", f"/api/agent/next?timeout={timeout:g}", None, timeout + 10)

    def _request(self, method: str, path: str, body: Mapping[str, Any] | None, timeout: float) -> dict[str, Any] | None:
        headers = {TOKEN_HEADER: self._token}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self._base + path, data=data, headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            with e:
                status = e.code
            if status in (401, 403):
                raise AgentRejected(f"{method} {path}: {status}") from None
            if status >= 500:
                raise ServerUnavailable(f"{method} {path}: {status}") from None
            raise RuntimeError(f"{method} {path}: unexpected status {status}") from None
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            raise ServerUnavailable(f"{method} {path}: {e}") from e
        if status == 204 or not raw:
            return None
        try:
            result = json.loads(raw.decode("utf-8"))
        except ValueError:
            result = None
        if not isinstance(result, dict):
            raise RuntimeError(f"{method} {path}: response is not a JSON object")
        return result
