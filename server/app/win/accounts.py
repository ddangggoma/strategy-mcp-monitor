"""SID → ``DOMAIN\\name`` (blocking ``LookupAccountSid``: collector threads or ``to_thread`` only)."""

from __future__ import annotations

import functools

from app.win import IS_WINDOWS

if IS_WINDOWS:
    import pywintypes
    import win32security


@functools.lru_cache(maxsize=4096)
def sid_to_account(sid: str) -> str | None:
    """``S-1-5-18`` → ``NT AUTHORITY\\SYSTEM`` (name only when the domain is empty); ``None`` when
    the SID is malformed or unknown. Results, failures included, are cached."""
    try:
        name, domain, _kind = win32security.LookupAccountSid(
            None, win32security.ConvertStringSidToSid(sid)
        )
    except pywintypes.error:
        return None
    if not name:
        return None
    return f"{domain}\\{name}" if domain else name
