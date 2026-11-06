"""SID → ``DOMAIN\\name``.

``sid_to_account`` blocks (``LookupAccountSid``, up to a domain controller's timeout): collector
threads or ``to_thread`` only. The event log watcher of the PowerShell channels calls it for every
record's user SID, so ``cached_account`` — what the loop uses — finds the answer without blocking
(plan review M6).
"""

from __future__ import annotations

import threading

from app.win import IS_WINDOWS

if IS_WINDOWS:
    import pywintypes
    import win32security

_CACHE_MAX = 4096
_cache: dict[str, str | None] = {}
_lock = threading.Lock()


def _lookup(sid: str) -> str | None:
    try:
        name, domain, _kind = win32security.LookupAccountSid(
            None, win32security.ConvertStringSidToSid(sid)
        )
    except pywintypes.error:
        return None
    if not name:
        return None
    return f"{domain}\\{name}" if domain else name


def sid_to_account(sid: str) -> str | None:
    """``S-1-5-18`` → ``NT AUTHORITY\\SYSTEM`` (name only when the domain is empty); ``None`` when
    the SID is malformed or unknown. Results, failures included, are cached. Blocking."""
    with _lock:
        if sid in _cache:
            return _cache[sid]
    account = _lookup(sid)
    with _lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        _cache[sid] = account
    return account


def cached_account(sid: str) -> str | None:
    """What ``sid_to_account`` found for ``sid`` earlier, or None; never blocks (loop thread)."""
    with _lock:
        return _cache.get(sid)
