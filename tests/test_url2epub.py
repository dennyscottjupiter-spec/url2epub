"""Offline regression tests for url2epub.py (the Android single-file engine)."""
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import url2epub as u  # noqa: E402


def soup(html):
    return BeautifulSoup(html, "html.parser")


def build(tmp_path, html, title="T", author="A", source="https://e.com/?a=1&b=2"):
    art = u.clean_soup(soup(html))
    path = tmp_path / "out.epub"
    u.write_epub(str(path), title, author, source, u.split_into_chapters(art), [])
    return path


def assert_valid_epub(path):
    with zipfile.ZipFile(path) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype"
        assert first.compress_type == zipfile.ZIP_STORED
        names = set(z.namelist())
        for n in names:
            if n.endswith((".xhtml", ".opf", ".ncx", ".xml")):
                ET.fromstring(z.read(n))          # raises if not well-formed


@pytest.mark.parametrize("raw,expected", [
    ("example.com/a", "https://example.com/a"),
    ("  http://x.org ", "http://x.org"),
    ("HTTPS://A.B/c", "HTTPS://A.B/c"),
])
def test_normalize_url_ok(raw, expected):
    assert u.normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "localhost", "https://"])
def test_normalize_url_rejects(raw):
    with pytest.raises(ValueError):
        u.normalize_url(raw)


def test_sanitize_filename():
    assert u.sanitize_filename("Hello, World: a/b?") == "Hello_World_ab"
    assert u.sanitize_filename("???") == "article"
    assert len(u.sanitize_filename("x" * 300)) == 80


def test_xml_strips_control_chars():
    assert u.xml("a\x0bb\x01<") == "ab&lt;"


def test_epub_well_formed_with_hostile_markup(tmp_path):
    html = ('<div :class="a" x-on:click="b" @click="c" data-x><o:p>hi\x0b there\x01</o:p>'
            '<p>text &amp; more <svg:rect/></p><h1>One</h1><p>a</p><h2>Two</h2><p>b</p></div>')
    path = build(tmp_path, html, title="T\x0c", author="A&B")
    assert_valid_epub(path)
    with zipfile.ZipFile(path) as z:
        body = "".join(z.read(n).decode() for n in z.namelist() if n.startswith("EPUB/chap"))
    assert "hi there" in body and "@click" not in body


def _chapter_texts(path):
    with zipfile.ZipFile(path) as z:
        return ([z.read(n).decode() for n in sorted(z.namelist()) if n.startswith("EPUB/chap")],
                z.read("EPUB/nav.xhtml").decode())


def test_single_chapter_uses_book_title_not_article(tmp_path):
    chaps, nav = _chapter_texts(build(tmp_path, "<div><h2>Real</h2><p>body text</p></div>", title="My Book"))
    assert len(chaps) == 1 and ">Article<" not in chaps[0] and ">Article<" not in nav
    assert "My Book" in nav and chaps[0].count("<h1>") == 0       # body already had a heading
    chaps, _ = _chapter_texts(build(tmp_path, "<p>no heading here</p>", title="My Book"))
    assert "<h1>My Book</h1>" in chaps[0]


def test_mediawiki_edit_links_removed():
    out = u.clean_soup(soup('<h2>Hist<span class="mw-editsection">[edit]</span></h2><p>x</p>'))
    assert "[edit]" not in out.get_text()


def test_chapters_split_on_headings():
    chs = u.split_into_chapters(soup("<p>intro</p><h1>A</h1><p>x</p><h2>B</h2><p>y</p>"))
    assert [t for t, _ in chs] == ["Introduction", "A", "B"]
    assert u.split_into_chapters(soup("<p>only</p>"))[0][0] == "Article"


def test_clean_soup_survives_decomposed_descendants():
    # bs4 >= 4.13 regression (CLAUDE.md): junk parent decomposed before its children.
    html = ('<div class="sidebar"><div class="menu"><a href="#">x</a></div></div>'
            '<article class="newsletter-post">' + "<p>real prose, here.</p>" * 40 + "</article>")
    out = u.clean_soup(soup(html))
    assert "real prose" in out.get_text() and "menu" not in str(out)


def test_is_truncated_accepts_string_wordcount():
    art = soup("<p>" + "word " * 100 + "</p>")
    assert u._is_truncated(art, {"wordCount": "5000"})
    assert u._is_truncated(art, {"wordCount": 5000})
    assert not u._is_truncated(art, {"wordCount": "120"})
    assert not u._is_truncated(art, {"wordCount": "lots"})


def test_jina_skip_only_matches_x_hosts(monkeypatch):
    calls = []
    monkeypatch.setattr(u.requests, "get", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(
        u.requests.exceptions.ConnectionError("offline")))
    assert u.fetch_via_jina("https://x.com/a/status/1") is None
    assert u.fetch_via_jina("https://mobile.twitter.com/a") is None
    assert calls == []
    u.fetch_via_jina("https://netflix.com/article")
    assert len(calls) == 1                     # netflix.com was NOT skipped


class _Resp:
    def __init__(self, status, ctype="text/html", text="<html>ok</html>"):
        self.status_code, self.text, self.url = status, text, "https://e.com/"
        self.headers, self.ok, self.reason = {"Content-Type": ctype}, status < 400, "x"
        self.encoding, self.apparent_encoding = "utf-8", "utf-8"


def _patch_fetch(monkeypatch, first, retries):
    class S:
        def get(self, *a, **k):
            return first
    monkeypatch.setattr(u, "get_session", lambda: S())
    it = iter(retries)
    monkeypatch.setattr(u.requests, "get", lambda *a, **k: next(it))


def test_403_then_404_is_not_blocked(monkeypatch):
    _patch_fetch(monkeypatch, _Resp(403), [_Resp(404)])
    with pytest.raises(u.FetchError) as e:
        u.fetch_page("https://e.com/missing", quiet=True)
    assert e.value.status == 404 and not e.value.blocked


def test_403_then_plain_ua_succeeds(monkeypatch):
    _patch_fetch(monkeypatch, _Resp(403), [_Resp(403), _Resp(200)])
    assert u.fetch_page("https://e.com/", quiet=True)[0] == "<html>ok</html>"


def test_403_on_both_retries_is_blocked(monkeypatch):
    _patch_fetch(monkeypatch, _Resp(403), [_Resp(403), _Resp(403)])
    with pytest.raises(u.FetchError) as e:
        u.fetch_page("https://e.com/", quiet=True)
    assert e.value.blocked


def test_403_then_pdf_is_not_a_web_page(monkeypatch):
    _patch_fetch(monkeypatch, _Resp(403), [_Resp(200, "application/pdf")])
    with pytest.raises(u.FetchError) as e:
        u.fetch_page("https://e.com/a.pdf", quiet=True)
    assert "not a web page" in str(e.value) and not e.value.blocked


def test_archive_stops_after_first_timeout(monkeypatch):
    calls = []

    def fake_get(*a, **k):
        calls.append(a[0])
        raise u.requests.exceptions.ReadTimeout("slow")
    monkeypatch.setattr(u.requests, "get", fake_get)
    assert u.fetch_via_archive("https://e.com/", quiet=True) is None
    assert len(calls) == 1


def test_detect_title_prefers_h1_matching_ld_name():
    s = soup("<h1>EPUB</h1>")
    assert u.detect_title(s, {"headline": "e-book format", "name": "EPUB"}) == "EPUB"
    assert u.detect_title(s, {"headline": "Real Headline"}) == "Real Headline"
    assert u.detect_title(soup(""), {}) == "Untitled Article"


def test_detect_author_variants():
    assert u.detect_author(soup(""), {"author": [{"name": "Ann"}]}) == "Ann"
    assert u.detect_author(soup('<meta name="author" content="Bob">'), {}) == "Bob"
    assert u.detect_author(soup('<span class="byline">By Cy</span>'), {}) == "Cy"


def test_extract_main_content_picks_article():
    html = ("<nav>" + "<a href='#'>link</a>" * 50 + "</nav>"
            "<div class='content'>" + "<p>This is a long, real, paragraph of prose text.</p>" * 30
            + "</div><div class='sidebar'>ads</div>")
    art = u.extract_main_content(soup(html))
    assert u.text_len(art) > 1000 and "link" not in art.get_text()


def test_jsonld_and_state_fallbacks():
    body = "Paragraph one, with words.\n\n" * 40
    assert u.text_len(u.jsonld_body_to_soup({"articleBody": body})) > 500
    script = ('<script>window.__NEXT_DATA__ = {"props": {"body": "%s"}};</script>'
              % ("Sentence of real prose here. " * 30))
    assert u.text_len(u.extract_from_state(soup(script))) > 500


def test_tweet_token_and_url_patterns():
    assert u._tweet_token("20")                         # non-empty, no dots/zeros
    assert "." not in u._tweet_token("1234567890123456789")
    assert u.is_tweet_url("https://x.com/jack/status/20")
    assert u.is_article_url("https://x.com/i/article/123")
    assert not u.is_tweet_url("https://netflix.com/jack/status/20")


def test_draftjs_rendering():
    cs = {"blocks": [
        {"type": "header-two", "text": "Head", "inlineStyleRanges": [], "entityRanges": []},
        {"type": "unstyled", "text": "bold link", "inlineStyleRanges":
            [{"offset": 0, "length": 4, "style": "Bold"}],
         "entityRanges": [{"offset": 5, "length": 4, "key": 0}]},
        {"type": "unordered-list-item", "text": "a", "inlineStyleRanges": [], "entityRanges": []},
    ], "entityMap": [{"key": "0", "value": {"type": "LINK", "data": {"url": "https://e.com"}}}]}
    html = u._draftjs_to_html(cs)
    assert "<h2>Head</h2>" in html and "<b>bold</b>" in html
    assert '<a href="https://e.com">link</a>' in html and "<ul><li>a</li></ul>" in html


def test_pick_image_url_lazy_attrs():
    assert u.pick_image_url(soup('<img data-src="a.png" src="data:x">').img) == "a.png"
    assert u.pick_image_url(soup('<img srcset="s.png 1x, l.png 2x">').img) == "l.png"
