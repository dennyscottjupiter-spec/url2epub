# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this is

A single self-contained Python script (`url2epub.py`) that turns a web-article URL into a
Kindle-friendly EPUB3. No package, no build, no dependency manifest, no test suite — the whole
program is one file. **It runs on Android only, inside [PyDroid 3](https://play.google.com/store/apps/details?id=ru.iiec.pydroid3)
— not Windows/macOS/Linux.** Desktop CPython works and is how it's developed and tested, but that
is *not* a supported use.

## The overriding design constraint: zero compiled dependencies

The single most important thing to know before changing anything. PyDroid 3 has no C compiler and
no libxml2/libxslt headers, so any dependency that compiles from source (lxml, `readability-lxml`,
`ebooklib`, Pillow, …) crashes on `pip install` on the phone. The `v2` rewrite exists to purge them:

- content extraction → hand-written pure-Python scorer (replaces `readability-lxml`)
- EPUB writer → hand-rolled `zipfile` + string templates (replaces `ebooklib`)
- HTML parsing → stdlib `html.parser` (replaces the `lxml` parser)

The only deps are `requests`, `beautifulsoup4`, and `xclienttransaction` — all **pure Python**,
auto-installed at runtime (Section 1, `ensure_packages()`). `xclienttransaction` is a documented
exception to the "2 deps only" rule: it exists solely for X Articles (Section 6C) and is a 258-star
unofficial package (below this project's 1,000-star bar), accepted only because there is no
official, no-login way to read an X Article and no way to hand-write the header it generates without
duplicating ~300 lines of reverse-engineered logic.

**Rule for any change: never add a dependency that needs a compiler, and never switch the parser off
`html.parser`.** If a task seems to need lxml/Pillow/etc., use the stdlib or a pure-Python approach.

## Running it

```powershell
python3 url2epub.py
```

**Interactive:** prompts for a URL on stdin, takes no CLI args/flags, and (on weak extraction) may
prompt "full page body vs abort". Output goes to Android's `/storage/emulated/0/Download/`, falling
back to the cwd when that isn't writable — always the case on desktop, so the `.epub` lands in cwd.

No lint, no CI, no tests. To run non-interactively, feed the URL to stdin — but on Windows **do not
use a PowerShell `|` pipe** (it prepends a UTF-8 BOM and the script rejects the URL). Use a Python
subprocess instead:

```powershell
python3 -c "import subprocess; subprocess.run(['python3','url2epub.py'], input='https://example.com/article\n', text=True, encoding='utf-8')"
```

## Architecture (big picture)

Organized top-to-bottom into numbered `SECTION 0…12` banners in runtime-pipeline order. Keep that
structure — put new code in the matching section and keep helpers pure. `resolve_article()`
(Section 12) turns a URL into `(title, author, article_soup, base_url)`; `main()` builds the EPUB.
The core logic is the extraction fallback chain `resolve_article` drives:

**0. Special-site handlers** run FIRST, before the generic pipeline, for sites that never expose
text to a JS-free fetch. Each returns a `{title, author, article, base_url}` dict, or `None` to fall
through to the next handler and then the generic pipeline.
- **X / Twitter tweets** (6B): `tweet_to_article()` pulls the post from X's public syndication JSON
  (`cdn.syndication.twimg.com/tweet-result`, no login/JS), incl. media and quoted tweets;
  `_tweet_token()` reproduces X's base36 token.
- **X Articles** (6C): `article_to_article()` — no public syndication endpoint exists, so it drives
  X's *internal* GraphQL: a guest session (`/1.1/guest/activate.json` + a self-generated CSRF token
  X only checks for a cookie/header match), an `x-client-transaction-id` per request (from the
  `xclienttransaction` dep, derived from `x.com/home` + its `ondemand.s.*.js` bundle), and a GraphQL
  `doc_id` looked up **live** from a community registry (`fa0311/TwitterInternalAPIDocument`,
  regenerated daily) — X rotates doc_ids every 2-4 weeks to break scrapers that hardcode one. An
  Article is a Draft.js rich-text attachment on an ordinary tweet (its article id ≠ the hosting
  tweet's), fetched via `TweetResultByRestId` with article-specific `fieldToggles`, then rendered by
  `_draftjs_to_html()`. **Quirk:** X sends inline style names TitleCase (`"Bold"`), not Draft.js's
  `"BOLD"` — matched case-insensitively. **Fragility:** everything but the doc_id lookup is a fixed
  point that breaks silently if X changes its obfuscation or schema; no self-healing short of a new
  `xclienttransaction` release or a manual fix. **Reliability:** *transient* failures (esp. a 429
  when X rate-limits guest activation — the actual cause of the "blank EPUB" bug) are retried with
  backoff (`_ARTICLE_ATTEMPTS`, `_article_once` raises `_ArticleTransient`); a *definitive* miss
  returns `None` at once. On a final `None` for a recognized X URL, `resolve_article()` **exits with
  a clear "try again" message** rather than emitting a junk near-empty EPUB from the generic pipeline.

**1. Fetch** (S4) — a shared `requests.Session` (`get_session()`) with a **Samsung Galaxy S24**
fingerprint + Sec-CH-UA hints and auto retry/backoff (HTTPAdapter + urllib3 Retry) on 429/5xx.
`fetch_page()` **raises `FetchError`** (no longer `sys.exit()`s) so callers can react — a `blocked`
error triggers the archive.today fallback; `_decode()` fixes requests' cp1252-default UTF-8 mangling.

**2. Metadata** (S5) — title/author from `<script type="application/ld+json">` first, then
`og:`/meta tags, then the visible DOM.

**3. Extraction — a 5-stage fallback chain** (S6). Each stage is accepted only if it yields ≥
`MIN_GOOD_TEXT` (500) chars, else it falls through:
1. **Score-based DOM** (`extract_main_content` → `score_container`): Reader-Mode heuristics — reward
   long paragraphs and comma counts, weight by `POSITIVE_HINTS`/`NEGATIVE_HINTS` class/id names,
   multiply down by link density, then climb parents to reunite an article split across sibling `<div>`s.
2. **JSON-LD `articleBody`** — JS-rendered sites often ship the full text here for SEO even when the
   visible DOM is empty.
3. **AMP** — refetch the `<link rel="amphtml">` version (server-rendered plain HTML).
4. **archive.today** (`fetch_via_archive()`) — on a blocked page (401/402/403/429/451) or still-weak
   extraction, try the public archive.ph/today/is snapshot. Best-effort: detects Cloudflare/rate-limit
   and returns `None` gracefully (won't beat hard paywalls).
5. **Interactive** — offer the full cleaned page body, or abort.

**4. Cleanup** (`clean_soup`, S7) — strips `JUNK_TAGS`, elements whose class/id/role match
`JUNK_KEYWORDS`, inline styles/handlers, and empties. `JUNK_KEYWORDS` *deletes* nodes while
`POSITIVE_HINTS`/`NEGATIVE_HINTS` only *score* — don't conflate the two. **Guard:** `clean_soup`
refuses to delete a *large, link-sparse* block even if a junk keyword matches its class (protects
e.g. Substack's `<article class="newsletter-post">` from the `newsletter` keyword).

**5. Images** (S8) — download + embed each `<img>` as an internal EPUB path, resolving lazy-load
attributes (`data-src`, `srcset`, …); failed/oversized images are dropped.

**6. Chapters** (S9) — inject an invisible marker before every `h1`/`h2`, serialize, split on the
marker, re-parse each fragment (repairs tags broken by the cut; handles headings without a shared parent).

**7. EPUB writer** (S10) — an EPUB is a ZIP with a fixed skeleton: `mimetype` **first and STORED
(uncompressed)**, then `META-INF/container.xml`, `EPUB/content.opf` (manifest + spine), `nav.xhtml`
(EPUB3 TOC) + `toc.ncx` (legacy TOC), then the XHTML/CSS/image files. Every XHTML file **must be
well-formed XML** — hence content is re-serialized through BeautifulSoup (void elements self-closed)
and all interpolated strings pass through `xml()`.

Tuning knobs live in **Section 2** (`OUTPUT_DIR`, `TIMEOUT`, `MAX_IMAGE_BYTES`, `MIN_GOOD_TEXT`,
`HEADERS` — Galaxy S24 fingerprint — and the junk/hint lists), plus `ARCHIVE_HOSTS` (S4),
`TWEET_URL_RE` (6B), and `ARTICLE_URL_RE` / `_GRAPHQL_REGISTRY` (6C).

## Navigating this file efficiently (token budget)

`url2epub.py` is one ~1,300-line module (~15K tokens). **Don't full-read it for a localized change** —
use the catalog below to pick the one or two sections you need. The script stays a single file (a
hard product constraint); this index lives outside the code so the code stays lean.

1. **Locate live:** `Grep "^# SECTION"` returns every banner with its *current* line (the numbers
   below are a snapshot — trust the Grep after edits shift them).
2. **Read one section:** `Read` with `offset`/`limit` for its range (its start line → the next
   section's start). e.g. Section 6C ≈ `offset 656, limit 250`.
3. **Find a symbol:** `Grep` its name; the table says which section owns it.

| § | Line | Purpose | Key symbols |
|---|------|---------|-------------|
| 0  | 28   | stdlib imports | — |
| 1  | 43   | runtime auto-install of the 3 pure-Python deps | `ensure_packages`, `REQUIRED_PACKAGES` |
| 2  | 96   | **all tuning knobs / config constants** | `OUTPUT_DIR`, `TIMEOUT`, `MAX_IMAGE_BYTES`, `MIN_GOOD_TEXT`, `HEADERS`, `JUNK_TAGS`, `JUNK_KEYWORDS`, `POSITIVE_HINTS`, `NEGATIVE_HINTS`, `EPUB_CSS` |
| 3  | 165  | small pure helpers | `normalize_url`, `sanitize_filename`, `text_len`, `xml` |
| 4  | 198  | fetch: retrying session + archive.today recovery | `get_session`, `fetch_page`, `FetchError`, `_decode`, `fetch_via_archive`, `ARCHIVE_HOSTS` |
| 5  | 333  | metadata (title/author) incl. JSON-LD | `find_jsonld_article`, `detect_title`, `detect_author`, `iter_jsonld_objects` |
| 6  | 409  | pure-Python Reader-Mode content extraction | `extract_main_content`, `score_container`, `link_density`, `jsonld_body_to_soup`, `find_amp_url` |
| 6B | 488  | special-site: X / Twitter tweets (syndication JSON) | `tweet_to_article`, `fetch_tweet`, `_tweet_token`, `TWEET_URL_RE` |
| 6C | 656  | special-site: X Articles (internal GraphQL, Draft.js) | `article_to_article`, `_draftjs_to_html`, `_x_guest_client`, `_gql_get`, `ARTICLE_URL_RE`, `_GRAPHQL_REGISTRY` |
| 7  | 904  | junk removal / soup cleanup | `clean_soup` |
| 8  | 949  | image download + EPUB embedding | `collect_images`, `pick_image_url`, `IMG_MIME` |
| 9  | 1006 | chapter splitting on h1/h2 | `split_into_chapters`, `SPLIT_MARK` |
| 10 | 1034 | hand-rolled EPUB3 writer (zip + templates) | `write_epub`, `soup_to_xhtml_body`, `XHTML_SHELL`, `CONTAINER_XML` |
| 11 | 1159 | output-path resolution (Android Download → cwd) | `resolve_output_path` |
| 12 | 1173 | orchestration | `resolve_article` (URL → title/author/soup/base_url), `main` |

## Git workflow

No feature branches — work happens directly on `main`. Every change gets an atomic commit, pushed to
`origin/main` before a task is done. "Full housekeeping" here means committed + pushed + no stray
branches (not a merge — there's nothing to merge into).

## Known gotcha: bs4 ≥ 4.13 crash (the REAL cause)

The script targets the older BeautifulSoup PyDroid 3 ships but must not crash on newer bs4 (e.g. 4.15
on this dev machine). The "crashes on Wikipedia" bug: `clean_soup` iterates a **static**
`find_all(True)` snapshot and `decompose()`s junk containers mid-loop. On **bs4 ≥ 4.13**,
`decompose()` nulls `.attrs` (and `.name`) on the node **and all its descendants** — those dead
descendants are still in the snapshot, so a later `tag.get(...)` becomes `None.get(...)` →
`AttributeError: 'NoneType' object has no attribute 'get'`.

**Fix — SKIP already-decomposed nodes:** `if getattr(tag, "decomposed", False): continue` at the top
of the loop (a no-op on older bs4). ⚠️ `tag.get("class") or []` does **NOT** fix it (it still
dereferences the `None` `.attrs`); the decomposed-guard is what prevents the crash. A crash on
desktop may be this version skew, not the site.
