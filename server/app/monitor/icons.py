"""The per-MCP icon: one emoji (``McpConfig.icon``), or ``None`` for the default MCP icon.

The icon is display only (board card, MCP lists). It is never free-form markup, a URL or an upload:
the value must be exactly one emoji, i.e. one of
  - a flag: two regional indicators (🇰🇷),
  - a keycap: 0-9, # or * with an optional U+FE0F and U+20E3 (#️⃣),
  - a tag sequence: 🏴 + tag characters + cancel tag (subdivision flags),
  - one or more emoji elements joined by U+200D (ZWJ), each a pictographic base with an optional
    U+FE0F and an optional skin-tone modifier (👍🏽, 🧑🏽‍💻, ❤️‍🔥),
and at most ``MAX_UTF16`` UTF-16 code units. Letters, digits, whitespace, controls and markup never
pass. web/src/lib/mcp-emoji.ts applies the same rules, and both sides run the shared cases in
web/src/lib/mcp-icon-cases.json (tests/test_icon_emoji.py, mcp-emoji.test.ts).
"""
from __future__ import annotations

import unicodedata

MAX_UTF16 = 16

_ZWJ = "\N{ZERO WIDTH JOINER}"
_VS16 = "\N{VARIATION SELECTOR-16}"
_KEYCAP = "\N{COMBINING ENCLOSING KEYCAP}"
_KEYCAP_BASES = frozenset("0123456789#*")
_BLACK_FLAG = "\U0001f3f4"
_CANCEL_TAG = "\U000e007f"

# Blocks that hold emoji bases; a base must also have a symbol-like category (_BASE_CATEGORIES).
_BASE_RANGES: tuple[tuple[int, int], ...] = (
    (0x00A9, 0x00A9), (0x00AE, 0x00AE), (0x203C, 0x203C), (0x2049, 0x2049), (0x2122, 0x2122),
    (0x2139, 0x2139), (0x2190, 0x21FF), (0x2300, 0x23FF), (0x24C2, 0x24C2), (0x25A0, 0x25FF),
    (0x2600, 0x27BF), (0x2900, 0x297F), (0x2B00, 0x2BFF), (0x3030, 0x3030), (0x303D, 0x303D),
    (0x3297, 0x3297), (0x3299, 0x3299), (0x1F000, 0x1FAFF),
)
_BASE_CATEGORIES = frozenset({"So", "Sm", "Po", "Pd", "Ll"})
# Emoji newer than this Python's Unicode tables are unassigned here; accept them in the
# supplemental pictograph blocks so a new emoji is not refused only because Python is older.
_NEW_EMOJI_RANGE = (0x1F900, 0x1FAFF)


def _in(cp: int, lo: int, hi: int) -> bool:
    return lo <= cp <= hi


def _regional(c: str) -> bool:
    return _in(ord(c), 0x1F1E6, 0x1F1FF)


def _modifier(c: str) -> bool:
    return _in(ord(c), 0x1F3FB, 0x1F3FF)


def _tag(c: str) -> bool:
    return _in(ord(c), 0xE0020, 0xE007E)


def _base(c: str) -> bool:
    cp = ord(c)
    if _regional(c) or _modifier(c) or not any(_in(cp, lo, hi) for lo, hi in _BASE_RANGES):
        return False
    category = unicodedata.category(c)
    return category in _BASE_CATEGORIES or (category == "Cn" and _in(cp, *_NEW_EMOJI_RANGE))


def _element(part: str) -> bool:
    """One ZWJ element: a base, then optionally U+FE0F, then optionally a skin-tone modifier."""
    if not part or not _base(part[0]):
        return False
    rest = part[1:]
    if rest.startswith(_VS16):
        rest = rest[1:]
    return rest == "" or (len(rest) == 1 and _modifier(rest))


def is_emoji(value: str) -> bool:
    """Exactly one emoji (see the module docstring)."""
    if not value or len(value.encode("utf-16-le")) // 2 > MAX_UTF16:
        return False
    cps = list(value)
    if len(cps) == 2 and _regional(cps[0]) and _regional(cps[1]):
        return True
    if cps[0] in _KEYCAP_BASES:
        return cps[1:] in ([_KEYCAP], [_VS16, _KEYCAP])
    if cps[0] == _BLACK_FLAG and len(cps) > 2 and _tag(cps[1]):
        return cps[-1] == _CANCEL_TAG and all(_tag(c) for c in cps[1:-1])
    return all(_element(part) for part in value.split(_ZWJ))


def check_icon(value: str | None) -> str | None:
    if value is not None and not is_emoji(value):
        raise ValueError("icon must be exactly one emoji")
    return value
