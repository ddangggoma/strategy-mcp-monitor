"""Keep the notice token out of the logs (I2, V15).

The agent opens the notice as ``msedge --app=<Local>/notice#d=<id>&t=<token>``: the token is on
Edge's command line (read by process collection, ``activity.process`` and 4688 ``process_cmdline``)
and can be the caption of the Edge window while the page loads (``activity.window`` titles).
"""

from __future__ import annotations

import re

_NOTICE_TOKEN = re.compile(r"(/notice#(?:[^\s\"'#&]*&)*t=)[^\s\"'&#]+")
REDACTED = "<redacted>"


def redact_notice_tokens(text: str) -> str:
    """``text`` with every notice-page token (``/notice#…t=<token>``) replaced by ``<redacted>``."""
    return _NOTICE_TOKEN.sub(lambda m: m.group(1) + REDACTED, text)
