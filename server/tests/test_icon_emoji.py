import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.monitor.icons import MAX_UTF16, is_emoji
from tests.mcp_helpers import cfg

# The same cases run in web/src/lib/mcp-emoji.test.ts: the client and the server agree on what an emoji is.
CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "mcp-icon-cases.json").read_text("utf-8")
)


@pytest.mark.parametrize("value", CASES["valid"], ids=lambda v: v.encode("unicode_escape").decode())
def test_one_emoji_is_an_icon(value):
    assert is_emoji(value)
    assert cfg(icon=value).icon == value


@pytest.mark.parametrize("value", CASES["invalid"], ids=lambda v: v.encode("unicode_escape").decode() or "empty")
def test_anything_else_is_refused(value):
    assert not is_emoji(value)
    with pytest.raises(ValidationError):
        cfg(icon=value)


def test_the_cases_cover_the_rules():
    lengths = [len(v.encode("utf-16-le")) // 2 for v in CASES["invalid"]]
    assert max(lengths) > MAX_UTF16  # one case is only too long
    assert len(CASES["valid"]) >= 15 and len(CASES["invalid"]) >= 25
