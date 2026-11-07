"""The keyword box → an FTS5 MATCH expression (ruling W3).

Every whitespace-separated word that has a letter or digit becomes a quoted prefix phrase
``"word"*``; the phrases are ANDed (FTS5's implicit operator). Quoting makes FTS5 operators and
punctuation in the words literal; the tokenizer then splits ``Stop-Process`` into ``stop`` +
``process`` as a phrase, and the trailing ``*`` matches Korean words with particles (``로그`` →
``로그를``).
"""
from __future__ import annotations

MAX_TERMS = 10
MAX_TERM_CHARS = 100


class InvalidQuery(ValueError):
    """Too many words, or a word that is too long."""


def fts_expression(q: str | None) -> str | None:
    """The MATCH expression for ``q``, or None when no word is left (no keyword condition)."""
    if q is None:
        return None
    words = [w for w in q.split() if any(ch.isalnum() for ch in w)]
    if len(words) > MAX_TERMS:
        raise InvalidQuery(f"at most {MAX_TERMS} words")
    if any(len(w) > MAX_TERM_CHARS for w in words):
        raise InvalidQuery(f"a word has at most {MAX_TERM_CHARS} characters")
    if not words:
        return None
    return " ".join('"' + w.replace('"', '""') + '"*' for w in words)
