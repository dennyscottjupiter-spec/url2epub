# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single self-contained Python script (`url2epub.py`) that turns a web article URL into a
Kindle-friendly EPUB3. There is no package, no build, no dependency manifest, and no test
suite — the whole program is one file.

**It runs on Android only, inside the [PyDroid 3](https://play.google.com/store/apps/details?id=ru.iiec.pydroid3)
app — not Windows/macOS/Linux.** Desktop CPython works and is how the tool is developed and
tested, but that is *not* a supported use (see "Running it").

## The overriding design constraint: zero compiled dependencies

This is the single most important thing to know before changing anything. The tool is built
to run under **PyDroid 3 on Android**, which has no C compiler and no libxml2/libxslt headers.
Any dependency that compiles from source (lxml, `readability-lxml`, `ebooklib`, Pillow, …)
crashes on `pip install` on the phone. The `v2` rewrite exists *specifically* to purge those:

- content extraction is a hand-written pure-Python scorer (replaces `readability-lxml`)
- the EPUB writer is hand-rolled with `zipfile` + string templates (replaces `ebooklib`)
- HTML parsing uses the stdlib `html.parser` (replaces the `lxml` parser)

The only two third-party deps are `requests` and `beautifulsoup4`, both **pure Python**, and
they are auto-installed at runtime via `pip` (Section 1, `ensure_packages()`).

**Rule for any future change: never introduce a dependency that needs a compiler, and never
switch the parser off `html.parser`.** If a task seems to need lxml/Pillow/etc., solve it with
the stdlib or a pure-Python approach instead.

## Running it

```powershell
python3 url2epub.py
```

It is **interactive**: it prompts for a URL on stdin, takes no CLI args or flags, and (in the
weak-extraction case) may prompt again to choose "full page body vs abort". Output goes to
Android's `/storage/emulated/0/Download/`, falling back to the current working directory when
that path isn't writable — which is always the case on a desktop, so the `.epub` lands in the cwd.

There is no lint, no CI, and no tests. To exercise it non-interactively, feed the URL to stdin.
On Windows, **do not use a PowerShell `|` pipe** for this — PowerShell prepends a UTF-8 BOM to
the piped bytes and the script rejects the URL as invalid. Drive it from a Python subprocess
instead:

```powershell
python3 -c "import subprocess; subprocess.run(['python3','url2epub.py'], input='https://example.com/article\n', text=True, encoding='utf-8')"
```

## Architecture (big picture)

The file is organized top-to-bottom into numbered `SECTION 0…12` comment banners that follow
the runtime pipeline order. Keep that structure: put new code in the matching section and keep
the helper functions pure. `resolve_article()` (Section 12) turns a URL into
`(title, author, article_soup, base_url)`; `main()` then builds the EPUB from that. The
interesting logic is the extraction fallback chain `resolve_article` drives:

0. **Special-site handlers** (Section 6B) run FIRST, before the generic pipeline — for sites
   that never expose text to a JavaScript-free fetch. Currently **X / Twitter**:
   `tweet_to_article()` pulls the post from X's public syndication JSON API
   (`cdn.syndication.twimg.com/tweet-result`, no login/JS), including media and quoted tweets;
   `_tweet_token()` reproduces X's base36 token. Add future per-site handlers here — each returns
   the same `{title, author, article, base_url}` dict, or `None` to fall through.
1. **Fetch** (Section 4) — a shared `requests.Session` (`get_session()`) with a **Samsung Galaxy
   S24** fingerprint + Sec-CH-UA client hints and automatic **retry/backoff** (HTTPAdapter +
   urllib3 Retry) on 429/5xx. `fetch_page()` **raises `FetchError`** (it no longer `sys.exit()`s)
   so callers can react — a `blocked` error triggers the archive.today fallback; `_decode()`
   fixes requests' cp1252-default mangling of UTF-8.
2. **Metadata** (Section 5) — title/author, mining `<script type="application/ld+json">`
   structured data first, then `og:`/meta tags, then visible DOM.
3. **Extraction — a 5-stage fallback chain** (Section 6). Each stage is accepted only if it
   yields ≥ `MIN_GOOD_TEXT` (500) chars, else it falls through to the next:
   1. **Score-based DOM extraction** (`extract_main_content` → `score_container`): Reader-Mode
      heuristics — reward long paragraphs and comma counts, weight by `POSITIVE_HINTS`
      /`NEGATIVE_HINTS` class/id names, and multiply down by link density. Then climb parents
      to reunite an article split across sibling `<div>`s.
   2. **JSON-LD `articleBody`** — JS-rendered sites often ship the full text here for SEO even
      when the visible DOM is empty.
   3. **AMP** — refetch the `<link rel="amphtml">` version (server-rendered plain HTML).
   4. **archive.today** (`fetch_via_archive()`) — on a blocked page (401/402/403/429/451) or
      still-weak extraction, try the public archive.ph/today/is snapshot. Best-effort: detects
      Cloudflare/rate-limit responses and returns `None` gracefully (won't beat hard paywalls).
   5. **Interactive** — offer the full cleaned page body, or abort.
4. **Cleanup** (`clean_soup`, Section 7) — strips `JUNK_TAGS`, elements whose class/id/role
   match `JUNK_KEYWORDS`, inline styles/handlers, and empties. Note `JUNK_KEYWORDS` *deletes*
   nodes, while `POSITIVE_HINTS`/`NEGATIVE_HINTS` only *score* them — don't conflate the two.
   **Guard:** `clean_soup` refuses to delete a *large, link-sparse* block even if a junk keyword
   matches its class — this protects e.g. Substack's `<article class="newsletter-post">` from
   being wiped by the `newsletter` keyword.
5. **Images** (Section 8) — download + embed each `<img>` as an internal EPUB path, resolving
   lazy-load attributes (`data-src`, `srcset`, …); failed/oversized images are dropped.
6. **Chapters** (Section 9) — inject an invisible marker before every `h1`/`h2`, serialize,
   split on the marker, and re-parse each fragment (this repairs tags broken by the cut and
   handles headings that don't share a parent).
7. **EPUB writer** (Section 10) — an EPUB is just a ZIP with a fixed skeleton: `mimetype` must
   be the **first entry and STORED (uncompressed)**, then `META-INF/container.xml`,
   `EPUB/content.opf` (manifest + spine), `nav.xhtml` (EPUB3 TOC) + `toc.ncx` (legacy TOC), and
   the XHTML/CSS/image files. Every XHTML file **must be well-formed XML** — that is why content
   is re-serialized through BeautifulSoup (void elements self-closed) and all interpolated
   strings pass through `xml()`.

Tuning knobs are the module constants in **Section 2** (`OUTPUT_DIR`, `TIMEOUT`,
`MAX_IMAGE_BYTES`, `MIN_GOOD_TEXT`, `HEADERS` — now a Galaxy S24 fingerprint — and the
junk/hint lists), plus `ARCHIVE_HOSTS` (Section 4) and `TWEET_URL_RE` (Section 6B).

## Known compatibility gotcha (bs4 ≥ 4.13 crash — the REAL cause)

The script targets the older BeautifulSoup PyDroid 3 ships, but must not crash on newer bs4
(e.g. 4.15 on this dev machine). The "crashes on Wikipedia" bug:

`clean_soup` iterates a **static** `find_all(True)` snapshot and `decompose()`s junk containers
mid-loop. On **bs4 ≥ 4.13**, `decompose()` nulls out `.attrs` (and `.name`) on the node **and all
its descendants**. Those dead descendants are still in the snapshot, so when the loop reaches one,
`tag.get(...)` becomes `None.get(...)` → `AttributeError: 'NoneType' object has no attribute 'get'`.

**The fix is to SKIP already-decomposed nodes**: `if getattr(tag, "decomposed", False): continue`
at the top of the loop (a harmless no-op on the older bs4, which never had the crash). ⚠️ The
once-suggested `tag.get("class") or []` does **NOT** fix this — it still dereferences the `None`
`.attrs`. (We do use `tag.get("class") or []` defensively, but the decomposed-guard is what
actually prevents the crash.) Keep this in mind when testing on desktop — a crash there may be
this version skew, not the site.
