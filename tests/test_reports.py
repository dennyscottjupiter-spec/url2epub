import codecs
import csv
import io

from core import reports
from core.runner import Result

OK = Result(True, "https://e.com/a", title="My Title", author="Ann", path="C:/x/My_Title.epub",
            size_kb=120, chapters=3, images=2, chars=900, seconds=1.2)
BAD = Result(False, "https://e.com/b", error="boom")
PIPE = Result(True, "https://e.com/c", title="A | B", size_kb=5)


def test_append_then_load_newest_first(tmp_path):
    f = tmp_path / "h.jsonl"
    reports.append(OK, f)
    reports.append(BAD, f)
    rows = reports.load(f)
    assert [r["ok"] for r in rows] == [False, True]
    assert rows[0]["url"] == "https://e.com/b"
    assert "when" in rows[0]


def test_load_skips_blank_corrupt_and_non_dict_lines(tmp_path):
    f = tmp_path / "h.jsonl"
    reports.append(OK, f)
    with open(f, "a", encoding="utf-8") as fh:
        fh.write("\nnot json\n[1, 2]\n")
    reports.append(BAD, f)
    assert len(reports.load(f)) == 2


def test_load_missing_file_is_empty(tmp_path):
    assert reports.load(tmp_path / "none.jsonl") == []


def test_clear_empties_history(tmp_path):
    f = tmp_path / "h.jsonl"
    reports.append(OK, f)
    reports.clear(f)
    assert f.exists()
    assert reports.load(f) == []


def test_summary_counts_ok_and_kb():
    rows = [{"ok": True, "size_kb": 120}, {"ok": True, "size_kb": 30}, {"ok": False, "size_kb": 0}]
    assert reports.summary(rows) == {"total": 3, "ok": 2, "failed": 1, "total_kb": 150}


def test_summary_ignores_non_numeric_size():
    rows = [{"ok": True, "size_kb": 120}, {"ok": True, "size_kb": "big"}, {"ok": True, "size_kb": None}, {"ok": True}]
    assert reports.summary(rows) == {"total": 4, "ok": 4, "failed": 0, "total_kb": 120}


def test_export_csv_columns_and_bom(tmp_path):
    hist, dest = tmp_path / "h.jsonl", tmp_path / "h.csv"
    reports.append(OK, hist)
    reports.export_csv(reports.load(hist), dest)
    raw = dest.read_bytes()
    assert raw.startswith(codecs.BOM_UTF8)
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert list(rows[0].keys()) == reports.CSV_COLUMNS
    assert rows[0]["title"] == "My Title"
    assert rows[0]["size_kb"] == "120"


def test_export_markdown_table_and_escaping(tmp_path):
    hist, dest = tmp_path / "h.jsonl", tmp_path / "h.md"
    reports.append(OK, hist)
    reports.append(PIPE, hist)
    reports.append(BAD, hist)
    reports.export_markdown(reports.load(hist), dest)
    text = dest.read_text(encoding="utf-8")
    assert text.startswith("# url2epub history\n")
    assert "3 conversions: 2 OK, 1 failed, 125 KB saved." in text
    assert "| OK | My Title | 120 | 3 | 2 | https://e.com/a |" in text
    assert "| OK | A \\| B | 5 | 0 | 0 | https://e.com/c |" in text
    assert "| FAILED |  | 0 | 0 | 0 | https://e.com/b |" in text


def test_export_csv_neutralises_formulas(tmp_path):
    dest = tmp_path / "h.csv"
    rows = [{"ok": True, "title": '=HYPERLINK("http://x","y")', "author": "@ann",
             "url": "https://e.com/a", "size_kb": -5, "error": "+1"}]
    reports.export_csv(rows, dest)
    out = list(csv.DictReader(io.StringIO(dest.read_bytes().decode("utf-8-sig"))))[0]
    assert out["title"].startswith("'=")
    assert out["author"] == "'@ann"
    assert out["error"] == "'+1"
    assert out["url"] == "https://e.com/a"
    assert out["size_kb"] == "-5"
