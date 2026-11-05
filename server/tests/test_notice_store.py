import sqlite3
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.notice.defaults import DEFAULT_NOTICE
from app.notice.store import (
    NoticeBody,
    NoticeContent,
    NoticeNotFoundError,
    NoticeStore,
    content_sha256,
)

C1 = NoticeContent("안내", "본문 1", "확인")
C2 = NoticeContent("안내", "본문 2", "알겠습니다")


def test_default_is_version_zero(db, clock):
    v = NoticeStore(db, clock).current()
    assert (v.version, v.content, v.created_at, v.author_id) == (0, DEFAULT_NOTICE, None, None)
    assert v.reverted_from is None


def test_default_text_is_the_built_in_notice():
    assert DEFAULT_NOTICE.title == "행동 감사 안내" and DEFAULT_NOTICE.button_text == "확인"
    assert DEFAULT_NOTICE.body.splitlines() == [
        "이 PC의 원격 접속 세션은 보안 감사를 위해 기록됩니다.",
        "",
        "- 접속 정보(사용자, 접속 IP, 시각)",
        "- 실행한 프로그램과 명령",
        "- 창 전환 기록",
    ]


def test_save_versions_and_noop(db, clock):
    s = NoticeStore(db, clock)
    assert s.save(C1, 1)[0].version == 1 and s.save(C1, 1) == (s.current(), False)
    assert s.save(C2, 2)[0].version == 2
    assert [v.version for v in s.versions()] == [2, 1]


def test_save_records_author_time_and_content(db, clock):
    s = NoticeStore(db, clock)
    v, created = s.save(C1, 5)
    assert created
    assert (v.version, v.content, v.author_id, v.reverted_from) == (1, C1, 5, None)
    assert v.created_at == datetime(2026, 11, 4, 5, 0, 0, tzinfo=UTC)
    assert s.current() == v and s.version(1) == v
    # the stored timestamp is the Plan 2 format: UTC-aware isoformat()
    raw = db.query("SELECT created_at FROM notice_versions")[0]["created_at"]
    assert raw == "2026-11-04T05:00:00+00:00"


def test_saving_the_default_text_while_on_default_is_a_noop(db, clock):
    s = NoticeStore(db, clock)
    assert s.save(DEFAULT_NOTICE, 1) == (s.current(), False)
    assert s.versions() == []


def test_one_changed_field_is_a_new_version(db, clock):
    s = NoticeStore(db, clock)
    s.save(C1, 1)
    for changed in (
        NoticeContent("다른 제목", C1.body, C1.button_text),
        NoticeContent(C1.title, "다른 본문", C1.button_text),
        NoticeContent(C1.title, C1.body, "다른 버튼"),
    ):
        base = s.current().version
        v, created = s.save(changed, 1)
        assert created and v.version == base + 1
        s.save(C1, 1)  # back, also a new version (differs from the current one)


def test_version_lookup(db, clock):
    s = NoticeStore(db, clock)
    s.save(C1, 1)
    assert s.version(0) is not None and s.version(0).content == DEFAULT_NOTICE
    assert s.version(1).content == C1
    assert s.version(2) is None and s.version(-1) is None


def test_versions_newest_first_limit_and_no_default(db, clock):
    s = NoticeStore(db, clock)
    for n in range(5):
        s.save(NoticeContent("안내", f"본문 {n}", "확인"), 1)
    assert [v.version for v in s.versions()] == [5, 4, 3, 2, 1]
    assert [v.version for v in s.versions(limit=2)] == [5, 4]


def test_revert_creates_a_new_version(db, clock):
    s = NoticeStore(db, clock); s.save(C1, 1); s.save(C2, 1)
    v, created = s.revert(1, 7)
    assert created and (v.version, v.content, v.reverted_from, v.author_id) == (3, C1, 1, 7)
    v0, created0 = s.revert(0, 7)
    assert created0 and v0.content == DEFAULT_NOTICE and v0.reverted_from == 0
    assert v0.version == 4
    with pytest.raises(NoticeNotFoundError): s.revert(99, 7)


def test_revert_to_identical_content_creates_nothing(db, clock):
    s = NoticeStore(db, clock)
    assert s.revert(0, 1) == (s.current(), False)  # on the default already
    s.save(C1, 1)
    s.save(C2, 1)
    assert s.revert(2, 1) == (s.current(), False)  # the current version itself
    s.save(C1, 1)  # v3 has the same content as v1
    current = s.current()
    assert s.revert(1, 1) == (current, False)
    assert [v.version for v in s.versions()] == [3, 2, 1]


def test_failed_revert_writes_nothing(db, clock):
    s = NoticeStore(db, clock)
    s.save(C1, 1)
    with pytest.raises(NoticeNotFoundError):
        s.revert(5, 1)
    assert [v.version for v in s.versions()] == [1]
    assert not db._conn.in_transaction  # the transaction was closed


def test_version_numbers_come_from_the_table_not_memory(db, clock):
    NoticeStore(db, clock).save(C1, 1)
    again = NoticeStore(db, clock)  # a fresh store on the same database continues the sequence
    assert again.save(C2, 1)[0].version == 2


def test_table_rejects_version_zero(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO notice_versions (version, title, body, button_text, created_at)"
            " VALUES (0, 't', 'b', 'x', 'now')"
        )


def test_content_sha256_is_stable_and_field_sensitive():
    assert content_sha256(C1) == content_sha256(NoticeContent("안내", "본문 1", "확인"))
    assert len(content_sha256(C1)) == 64
    # shifting text between fields must change the digest
    assert content_sha256(NoticeContent("ab", "c", "d")) != content_sha256(NoticeContent("a", "bc", "d"))


def test_body_normalization_and_limits():
    b = NoticeBody.model_validate({"title": "  안내 ", "body": "\r\n줄1  \r\n줄2\r\n\r\n", "button_text": " 확인 "})
    assert b.to_content() == NoticeContent("안내", "줄1\n줄2", "확인")
    for bad in ({"title": "", "body": "x", "button_text": "확인"}, {"title": "x" * 81, "body": "x", "button_text": "확인"},
                {"title": "x", "body": "x" * 4001, "button_text": "확인"}, {"title": "x", "body": "x", "button_text": "x" * 21},
                {"title": "a\x07", "body": "x", "button_text": "확인"}, {"title": "x", "body": "x", "button_text": "확인", "extra": 1}):
        with pytest.raises(ValidationError): NoticeBody.model_validate(bad)


def _body(**over):
    return {"title": "안내", "body": "본문", "button_text": "확인", **over}


def test_limits_are_inclusive_and_counted_in_code_points():
    ok = NoticeBody.model_validate(_body(title="가" * 80, body="나" * 4000, button_text="다" * 20))
    assert (len(ok.title), len(ok.body), len(ok.button_text)) == (80, 4000, 20)
    emoji = NoticeBody.model_validate(_body(title="😀" * 80))  # 80 code points, 160 UTF-16 units
    assert len(emoji.title) == 80


def test_limits_apply_after_normalization():
    # trailing spaces / blank edges do not count toward the limit
    assert NoticeBody.model_validate(_body(body="x" * 4000 + "   \r\n\r\n")).body == "x" * 4000
    assert NoticeBody.model_validate(_body(title=" " + "x" * 80 + " ")).title == "x" * 80
    # CRLF is one character after normalization
    assert NoticeBody.model_validate(_body(body="\r\n".join(["a"] * 2000))).body.count("\n") == 1999


@pytest.mark.parametrize("field", ["title", "body", "button_text"])
@pytest.mark.parametrize("blank", ["", "   ", " \t "])
def test_blank_fields_are_rejected(field, blank):
    with pytest.raises(ValidationError):
        NoticeBody.model_validate(_body(**{field: blank}))


def test_body_blank_lines_only_is_rejected():
    with pytest.raises(ValidationError):
        NoticeBody.model_validate(_body(body="\r\n \n\t\n"))


def test_body_keeps_inner_blank_lines_and_indentation():
    b = NoticeBody.model_validate(_body(body="\n\n  첫 줄  \n\n\n- 항목\t\n\n"))
    assert b.body == "  첫 줄\n\n\n- 항목"


def test_lone_cr_is_a_newline():
    assert NoticeBody.model_validate(_body(body="a\rb")).body == "a\nb"


@pytest.mark.parametrize("ch", ["\x00", "\x07", "\x08", "\x0b", "\x0c", "\x1b", "\x1f", "\x7f", "\x80", "\x85", "\x9f"])
@pytest.mark.parametrize("field", ["title", "body", "button_text"])
def test_control_characters_are_rejected_everywhere(field, ch):
    with pytest.raises(ValidationError):
        NoticeBody.model_validate(_body(**{field: f"a{ch}b"}))


def test_control_character_hidden_at_the_edge_is_still_rejected():
    # strip() would silently drop \x0b / \x1c-\x1f; they must be refused, not erased
    for edge in ("\x0b", "\x1c", "\x85"):
        with pytest.raises(ValidationError):
            NoticeBody.model_validate(_body(title=f"{edge}안내"))
        with pytest.raises(ValidationError):
            NoticeBody.model_validate(_body(body=f"본문{edge}"))


def test_tab_is_allowed_and_newline_only_in_body():
    b = NoticeBody.model_validate(_body(title="가\t나", body="가\n나\t다", button_text="가\t나"))
    assert b.title == "가\t나" and b.body == "가\n나\t다"
    for field in ("title", "button_text"):
        with pytest.raises(ValidationError):
            NoticeBody.model_validate(_body(**{field: "a\nb"}))
        with pytest.raises(ValidationError):
            NoticeBody.model_validate(_body(**{field: "a\rb"}))


def test_lone_surrogates_are_rejected():
    # json.loads("\"\\ud800\"") yields one; SQLite cannot store it
    for field in ("title", "body", "button_text"):
        with pytest.raises(ValidationError):
            NoticeBody.model_validate(_body(**{field: "a\ud800b"}))


def test_strict_types_and_required_fields():
    for bad in (_body(title=1), _body(body=None), _body(button_text=["확인"])):
        with pytest.raises(ValidationError):
            NoticeBody.model_validate(bad)
    for missing in ("title", "body", "button_text"):
        data = _body()
        del data[missing]
        with pytest.raises(ValidationError):
            NoticeBody.model_validate(data)


def test_markup_is_stored_verbatim():
    raw = "**중요** `코드` <b>x</b> [링크](http://x) - 항목"
    assert NoticeBody.model_validate(_body(body=raw)).body == raw


def test_default_notice_fits_limits():
    NoticeBody.model_validate({"title": DEFAULT_NOTICE.title, "body": DEFAULT_NOTICE.body, "button_text": DEFAULT_NOTICE.button_text})
    # and it is already in normalized form, so saving it back is recognised as "same content"
    assert NoticeBody.model_validate(
        {"title": DEFAULT_NOTICE.title, "body": DEFAULT_NOTICE.body, "button_text": DEFAULT_NOTICE.button_text}
    ).to_content() == DEFAULT_NOTICE
