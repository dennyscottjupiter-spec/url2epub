# ---
# purpose: Conversion history as JSON lines, plus summary and CSV/Markdown export
# exports: append(), load(), clear(), summary(), export_csv(), export_markdown(), CSV_COLUMNS
# depends: paths.py, runner.py
# ---
import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from . import paths
from .runner import Result

CSV_COLUMNS = ["when", "ok", "title", "author", "url", "path", "size_kb",
               "chapters", "images", "chars", "seconds", "error"]


def _resolve(path) -> Path:
    return paths.history_file() if path is None else Path(path)


def append(result: Result, path=None) -> None:
    row = {**asdict(result), "when": datetime.now().isoformat(timespec="seconds")}
    with open(_resolve(path), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")  # default ensure_ascii keeps U+2028 out of the line


def load(path=None) -> list[dict]:
    target = _resolve(path)
    if not target.exists():
        return []
    rows = []
    # errors="replace" turns bad bytes into text that fails JSON parsing and is skipped below
    with open(target, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows[::-1]


def clear(path=None) -> None:
    target = _resolve(path)
    if target.exists():
        with open(target, "w", encoding="utf-8"):
            pass


def summary(rows: list[dict]) -> dict:
    ok_rows = [r for r in rows if r.get("ok")]
    # a hand-edited history row can hold a string or null size; those count as 0
    sizes = [r.get("size_kb") for r in ok_rows]
    return {
        "total": len(rows),
        "ok": len(ok_rows),
        "failed": len(rows) - len(ok_rows),
        "total_kb": sum(s for s in sizes if isinstance(s, int) and not isinstance(s, bool)),
    }


def _csv_safe(value):
    # Excel runs a cell starting with these as a formula; a leading quote makes it plain text
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def export_csv(rows: list[dict], dest) -> None:
    # utf-8-sig adds a BOM so Excel opens accented titles correctly
    with open(dest, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: _csv_safe(v) for k, v in r.items()} for r in rows)


def _cell(value) -> str:
    # a raw pipe or newline would break the Markdown table
    return str(value).replace("|", "\\|").replace("\n", " ")


def export_markdown(rows: list[dict], dest) -> None:
    s = summary(rows)
    lines = [
        "# url2epub history",
        "",
        f"{s['total']} conversions: {s['ok']} OK, {s['failed']} failed, {s['total_kb']:,} KB saved.",
        "",
        "| When | Status | Title | KB | Chapters | Images | URL |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        cells = [
            r.get("when", ""),
            "OK" if r.get("ok") else "FAILED",
            r.get("title", ""),
            r.get("size_kb", ""),
            r.get("chapters", ""),
            r.get("images", ""),
            r.get("url", ""),
        ]
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    Path(dest).write_text("\n".join(lines) + "\n", encoding="utf-8")
