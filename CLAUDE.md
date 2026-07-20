# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single self-contained Python script (`url2epub.py`) that turns a web article URL into a
Kindle-friendly EPUB3. There is no package, no build, no dependency manifest, and no test
suite — the whole program is one file.

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
the helper functions pure. `main()` (Section 12) orchestrates everything; the interesting logic
is the extraction fallback chain it drives:

1. **Fetch** (Section 4) — one `requests` GET with a mobile User-Agent; hard-exits on paywall
   /404/non-HTML.
2. **Metadata** (Section 5) — title/author, mining `<script type="application/ld+json">`
   structured data first, then `og:`/meta tags, then visible DOM.
3. **Extraction — a 4-stage fallback chain** (Section 6, sequenced in `main()`). Each stage is
   accepted only if it yields ≥ `MIN_GOOD_TEXT` (500) chars, else it falls through to the next:
   1. **Score-based DOM extraction** (`extract_main_content` → `score_container`): Reader-Mode
      heuristics — reward long paragraphs and comma counts, weight by `POSITIVE_HINTS`
      /`NEGATIVE_HINTS` class/id names, and multiply down by link density. Then climb parents
      to reunite an article split across sibling `<div>`s.
   2. **JSON-LD `articleBody`** — JS-rendered sites often ship the full text here for SEO even
      when the visible DOM is empty.
   3. **AMP** — refetch the `<link rel="amphtml">` version (server-rendered plain HTML).
   4. **Interactive** — offer the full cleaned page body, or abort.
4. **Cleanup** (`clean_soup`, Section 7) — strips `JUNK_TAGS`, elements whose class/id/role
   match `JUNK_KEYWORDS`, inline styles/handlers, and empties. Note `JUNK_KEYWORDS` *deletes*
   nodes, while `POSITIVE_HINTS`/`NEGATIVE_HINTS` only *score* them — don't conflate the two.
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
`MAX_IMAGE_BYTES`, `MIN_GOOD_TEXT`, `HEADERS`, and the junk/hint lists).

## Known compatibility gotcha

The script targets the older BeautifulSoup that ships with PyDroid 3. On **bs4 ≥ 4.13**
(e.g. 4.15 on this dev machine) `Tag.attrs` can be `None`, so the `tag.get("class", [])` calls
in `clean_soup`/`score_container` raise `AttributeError: 'NoneType' object has no attribute 'get'`
on many real pages (Wikipedia, etc.). The safe idiom on modern bs4 is `tag.get("class") or []`.
Keep this in mind when testing on desktop — a crash there may be this version skew, not the site.
