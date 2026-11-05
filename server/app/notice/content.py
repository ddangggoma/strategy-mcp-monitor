"""The value type shared by the built-in default text and the stored versions."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NoticeContent:
    title: str
    body: str  # raw text; the markup subset is interpreted only by the web parser
    button_text: str
