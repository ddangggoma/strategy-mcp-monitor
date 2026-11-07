import gzip
import json

import pytest

from app.logstore.files import list_log_files
from app.logstore.reader import open_log, parse_line, read_chunk, split_lines


def line(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def test_split_on_newline_only_keeps_u2028_inside_a_line():
    a = line({"ts": "2026-11-04T14:00:00.000+09:00", "cat": "system", "text": "x y z\x1c"})
    lines, used = split_lines(a + b"\n\n" + b'{"ts": "partial')
    assert lines == [a] and used == len(a) + 2


def test_read_chunk_resumes_plain_and_gz(tmp_path):
    rows = [line({"ts": f"2026-11-04T14:00:0{i}.000+09:00", "cat": "system", "i": i}) for i in range(3)]
    body = b"\n".join(rows) + b"\n"
    (tmp_path / "2026-11-04.jsonl").write_bytes(body)
    (tmp_path / "2026-11-03.jsonl.gz").write_bytes(gzip.compress(body))
    for f in list_log_files(tmp_path):
        with open_log(f.path) as fh:
            c1 = read_chunk(fh, 0, max_bytes=len(rows[0]) + 5)
            assert [r for _, r in c1.lines] == [rows[0]] and c1.next_offset == len(rows[0]) + 1
            c2 = read_chunk(fh, c1.next_offset)
            assert [r for _, r in c2.lines] == rows[1:] and c2.eof and c2.lines[0][0] == c1.next_offset


def test_final_gz_tail_without_newline_is_a_line(tmp_path):
    a = line({"ts": "2026-11-04T14:00:00.000+09:00", "cat": "system"})
    p = tmp_path / "2026-11-04.jsonl.gz"; p.write_bytes(gzip.compress(a))
    with open_log(p) as fh:
        assert [r for _, r in read_chunk(fh, 0, final=True).lines] == [a]


def test_oversized_line_is_skipped_and_counted(tmp_path, monkeypatch):
    import app.logstore.reader as reader
    monkeypatch.setattr(reader, "MAX_LINE_BYTES", 64)
    ok = line({"ts": "2026-11-04T14:00:00.000+09:00", "cat": "system"})
    p = tmp_path / "2026-11-04.jsonl"; p.write_bytes(b"x" * 200 + b"\n" + ok + b"\n")
    with open_log(p) as fh:
        c = read_chunk(fh, 0, max_bytes=32)
    assert c.oversized == 1 and [r for _, r in c.lines] == [ok]


@pytest.mark.parametrize("raw", [b"[]", b'"x"', b'{"cat": "system"}', b'{"ts": "nope", "cat": "system"}',
                                 b'{"ts": "2026-11-04T14:00:00+09:00"}', b"{broken",
                                 b'{"ts": "2026-11-04T14:00:00", "cat": "system"}'])
def test_parse_line_rejects(raw):
    assert parse_line(raw) is None


def test_list_log_files_ignores_other_names(tmp_path):
    for n in ("2026-11-04.jsonl", "2026-11-03.jsonl.gz", "2026-13-01.jsonl", "notes.txt", "2026-11-04.jsonl.gz.tmp"):
        (tmp_path / n).write_bytes(b"x")
    assert [f.name for f in list_log_files(tmp_path)] == ["2026-11-03.jsonl.gz", "2026-11-04.jsonl"]


# ---- beyond the plan's list: offsets, partial tails, oversized edges, file metadata ----

def test_line_offsets_skip_blank_lines_and_partial_tail_is_left(tmp_path):
    a, b = line({"ts": "2026-11-04T14:00:00+09:00", "cat": "system"}), line({"ts": "2026-11-04T14:00:01+09:00", "cat": "system"})
    p = tmp_path / "2026-11-04.jsonl"; p.write_bytes(a + b"\n\n" + b + b"\n" + b'{"ts": "half')
    with open_log(p) as fh:
        c = read_chunk(fh, 0)
        assert c.lines == [(0, a), (len(a) + 2, b)] and c.next_offset == len(a) + len(b) + 3 and c.eof
        assert c.oversized == 0
        again = read_chunk(fh, c.next_offset)  # the writer has not finished the last line yet
        assert again.lines == [] and again.next_offset == c.next_offset and again.eof


def test_line_without_newline_in_the_first_read_extends_to_the_newline(tmp_path):
    a = line({"ts": "2026-11-04T14:00:00+09:00", "cat": "system", "pad": "y" * 300})
    b = line({"ts": "2026-11-04T14:00:01+09:00", "cat": "system"})
    p = tmp_path / "2026-11-04.jsonl"; p.write_bytes(a + b"\n" + b + b"\n")
    with open_log(p) as fh:
        c = read_chunk(fh, 0, max_bytes=16)
    assert [r for _, r in c.lines] == [a, b] and c.next_offset == p.stat().st_size and c.eof


def test_oversized_line_spanning_several_extensions_is_skipped_without_keeping_it(tmp_path, monkeypatch):
    import app.logstore.reader as reader
    monkeypatch.setattr(reader, "MAX_LINE_BYTES", 64)
    monkeypatch.setattr(reader, "EXTEND_BYTES", 50)
    ok = line({"ts": "2026-11-04T14:00:00+09:00", "cat": "system"})
    big = b"z" * 1000
    p = tmp_path / "2026-11-04.jsonl"; p.write_bytes(big + b"\n" + ok + b"\n")
    with open_log(p) as fh:
        c = read_chunk(fh, 0, max_bytes=32)
    assert c.oversized == 1 and c.lines == [(len(big) + 1, ok)] and c.next_offset == p.stat().st_size


def test_oversized_partial_line_at_the_end_of_a_live_file_waits(tmp_path, monkeypatch):
    import app.logstore.reader as reader
    monkeypatch.setattr(reader, "MAX_LINE_BYTES", 64)
    monkeypatch.setattr(reader, "EXTEND_BYTES", 50)
    ok = line({"ts": "2026-11-04T14:00:00+09:00", "cat": "system"})
    p = tmp_path / "2026-11-04.jsonl"; p.write_bytes(ok + b"\n" + b"z" * 500)
    with open_log(p) as fh:
        c = read_chunk(fh, 0, max_bytes=len(ok) + 3)
        assert c.lines == [(0, ok)] and c.next_offset == len(ok) + 1
        tail = read_chunk(fh, c.next_offset, max_bytes=32)
        assert tail.lines == [] and tail.next_offset == len(ok) + 1 and tail.eof and tail.oversized == 0
        done = read_chunk(fh, c.next_offset, max_bytes=32, final=True)  # an immutable file: skip it
        assert done.lines == [] and done.next_offset == p.stat().st_size and done.oversized == 1


def test_gz_reads_past_the_compressed_size_and_reports_uncompressed_offsets(tmp_path):
    rows = [line({"ts": "2026-11-04T14:00:00+09:00", "cat": "system", "i": i, "pad": "a" * 200}) for i in range(200)]
    body = b"\n".join(rows) + b"\n"
    p = tmp_path / "2026-11-04.jsonl.gz"; p.write_bytes(gzip.compress(body))
    assert p.stat().st_size < len(body) // 4
    with open_log(p) as fh:
        got, offset = [], 0
        while True:
            c = read_chunk(fh, offset, max_bytes=4096, final=True)
            got += c.lines; offset = c.next_offset
            if c.eof:
                break
    assert [r for _, r in got] == rows and offset == len(body)
    assert all(body[o:o + len(r)] == r for o, r in got)


def test_parse_line_accepts_a_valid_line_and_replaces_bad_utf8():
    obj = parse_line(b'{"ts": "2026-11-04T14:00:00.000+09:00", "cat": "system", "text": "a\xffb"}')
    assert obj is not None and obj["cat"] == "system" and obj["text"] == "a�b"
    assert parse_line(b'{"ts": 5, "cat": "system"}') is None
    assert parse_line(b'{"ts": "2026-11-04T14:00:00+09:00", "cat": 3}') is None
    assert parse_line(b"[" * 100_000) is None  # too deep for json: rejected, not a crash


def test_list_log_files_metadata_order_and_missing_dir(tmp_path):
    (tmp_path / "2026-11-04.jsonl").write_bytes(b"abc")
    (tmp_path / "2026-11-04.jsonl.gz").write_bytes(b"defgh")
    (tmp_path / "2026-11-02.jsonl").mkdir()  # a directory with a log name is not a log file
    files = list_log_files(tmp_path)
    assert [(f.name, f.day.isoformat(), f.compressed, f.size) for f in files] == [
        ("2026-11-04.jsonl", "2026-11-04", False, 3), ("2026-11-04.jsonl.gz", "2026-11-04", True, 5)]
    assert files[0].path == tmp_path / "2026-11-04.jsonl"
    assert list_log_files(tmp_path / "missing") == []
