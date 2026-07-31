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
  regenerated daily) — X rotates doc_ids every 2-4 weeks to break scrapers that hardcode one.

  **THE id-type bug (fixed):** an Article's own id is a DIFFERENT number from any tweet hosting it —
  verified empirically (real Article ids return an empty `TweetResultByRestId` result). `ARTICLE_URL_RE`
  captures both `x.com/<handle>/article/<id>` and `x.com/i/article/<id>` with a named `handle` group;
  `_article_once()` always tries the cheap guest `TweetResultByRestId` lookup first (works when `<id>`
  is really a hosting tweet's id), and treats ANY empty result as proof `<id>` is actually the Article's
  own entity id — which requires `ArticleEntityResultByRestId`, and **X only serves that to a logged-in
  session** (guest access is HTTP 404, verified empirically; there is no login-free path for those URLs).
  `_find_article_dict()` recursively hunts the response for the `{title, content_state}` shape rather
  than trusting a guessed wrapper key, since that success shape is unverified (guest 404s before ever
  reaching a real payload).

  **Optional cookie auth:** `_x_auth_client()` mirrors `_x_guest_client()` but authenticates with a real
  session read from `x_cookies.txt` — a plain-text file, two lines, looked up next to `url2epub.py` then
  in `OUTPUT_DIR`:
  ```
  auth_token=<value from your logged-in x.com session cookie>
  ct0=<value from the same session's ct0 cookie>
  ```
  Get both from a browser's devtools → Application → Cookies after logging into x.com. Absent file =
  silent fallback to the guest path (normal, not an error) — **never commit this file** (`.gitignore`'d).

  The Article body is a Draft.js rich-text attachment, rendered by `_draftjs_to_html()`. **Quirk:** X
  sends inline style names TitleCase (`"Bold"`), not Draft.js's `"BOLD"` — matched case-insensitively.
  **Fragility:** everything but the doc_id lookup is a fixed point that breaks silently if X changes its
  obfuscation or schema; no self-healing short of a new `xclienttransaction` release or a manual fix.
  **Reliability:** *transient* failures (network blips, GraphQL errors) are retried with backoff
  (`_ARTICLE_ATTEMPTS`, `_article_once` raises `_ArticleTransient`); a *definitive* miss sets
  `_LAST_ARTICLE_ERROR` to one of `needs_login` / `auth_rejected` / `not_found` /
  `transient_exhausted` and returns `None`. `resolve_article()` reads that and **exits with the actual
  cause** (`_ARTICLE_ERROR_MESSAGES`) — e.g. step-by-step cookie instructions for `needs_login` — instead
  of a blanket "rate limited, try again" that couldn't fix an auth problem.

**1. Fetch** (S4) — a shared `requests.Session` (`get_session()`) with a **Samsung Galaxy S24**
fingerprint + Sec-CH-UA hints and auto retry/backoff (HTTPAdapter + urllib3 Retry) on 429/5xx.
`fetch_page()` **raises `FetchError`** (no longer `sys.exit()`s) so callers can react — a `blocked`
error triggers the archive.today → Wayback → Jina escalation (S12); on a plain 403 it first retries once
with `_DESKTOP_HEADERS`. `_decode()` fixes requests' cp1252-default UTF-8 mangling.

**2. Metadata** (S5) — title/author from `<script type="application/ld+json">` first, then
`og:`/meta tags, then the visible DOM.

**3. Extraction — local-best, then a network escalation chain** (S6/S12). The local stage runs EVERY
cheap strategy and keeps the **best** candidate by `quality = text_len * (1 - link_density)` (not the
first one to merely clear `MIN_GOOD_TEXT` = 500 chars — that used to let a weak-but-passing extraction
permanently block a genuinely better later stage). A JSON-LD `wordCount` far above what was extracted
also escalates ("continue reading" truncations), even though the char count passed:
1. **Score-based DOM** (`extract_main_content` → `score_container`): Reader-Mode heuristics — reward
   long paragraphs and comma counts, weight by `POSITIVE_HINTS`/`NEGATIVE_HINTS` class/id names,
   multiply down by link density, then climb parents to reunite an article split across sibling `<div>`s.
2. **JSON-LD `articleBody`** — JS-rendered sites often ship the full text here for SEO even when the
   visible DOM is empty.
3. **`<noscript>`** (`extract_from_noscript`) — many SPAs ship a full server-rendered copy here for
   SEO/no-JS clients; reparsed through the same DOM scorer. Only tried if 1-2 were weak/truncated.
4. **Embedded JSON state** (`extract_from_state`) — ONE generic recursive miner instead of five
   framework handlers: `__NEXT_DATA__`/`__NUXT__`/`__APOLLO_STATE__`/`__remixContext`/RSC chunks all
   reduce to "there's JSON in a `<script>`, the article is somewhere inside it". A prose false-positive
   guard (`_looks_like_prose`: space ratio, brace/semicolon density, base64-likeness, sentence-break
   heuristic) keeps it from mistaking minified JS for article text.
5. **RSS `content:encoded`** (`extract_from_rss`) — newsletters (Substack/Medium/Ghost) publish the
   complete body in their feed even when the live page is JS-gated. Parsed with **regex over the raw
   feed text, never BeautifulSoup**: `html.parser` treats `<link>` as a void element, so a bare Atom
   `<link>url</link>` is unreachable via bs4 (broke 3/10 feeds in testing); the `"xml"` parser isn't an
   option since it needs lxml.

If the best local candidate is still weak/truncated, escalate over the network, each step gated the
same way:
6. **AMP** — refetch the `<link rel="amphtml">` version (server-rendered plain HTML).
7. **archive.today** (`fetch_via_archive()`) — on a blocked initial fetch (401/402/403/429/451) OR
   still-weak extraction, try the public archive.ph/today/is snapshot. Best-effort: detects
   Cloudflare/rate-limit and returns `None` gracefully (won't beat hard paywalls).
8. **Wayback Machine** (`fetch_via_wayback()`) — `archive.org/wayback/available` lookup; a public,
   well-documented API, generally more reliable than archive.today.
9. **Jina Reader** (`fetch_via_jina()`) — `r.jina.ai` renders JS server-side. **Must use its own clean
   session/UA**, never the shared one: the Galaxy S24 fingerprint gets a 403 Cloudflare challenge in
   front of Jina (verified), while a plain non-browser UA is let through. **Skips x.com entirely** — Jina
   blocks it outright with `AbuseAlleviationError` (verified), which is why X needs its own handlers
   (6B/6C) instead. Strips Jina's `Title:`/`URL Source:`/`Markdown Content:` header before wrapping the
   body as paragraphs, reusing the title when the page has none of its own.
10. **Interactive** — offer the full cleaned page body, or abort.

A blocked *initial* fetch (step 7's 401/402/403/429/451 case) escalates through archive → Wayback → Jina
before giving up — Jina's return there bypasses the rest of the pipeline entirely since it hands back an
already-built article, not a raw page to re-extract from.

On a 403 specifically, `fetch_page()` first retries once with a plain desktop Chrome fingerprint
(`_DESKTOP_HEADERS`) before treating it as blocked — fixes sites that UA-sniff the mobile fingerprint
specifically rather than blocking bots generally.

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
`HEADERS` — Galaxy S24 fingerprint — `_DESKTOP_HEADERS`, and the junk/hint lists), plus `ARCHIVE_HOSTS` /
`_JINA_HEADERS` (S4), `TWEET_URL_RE` (6B), and `ARTICLE_URL_RE` / `_GRAPHQL_REGISTRY` (6C).

## Navigating this file efficiently (token budget)

`url2epub.py` is one ~1,670-line module (~19K tokens). **Don't full-read it for a localized change** —
use the catalog below to pick the one or two sections you need. The script stays a single file (a
hard product constraint); this index lives outside the code so the code stays lean.

1. **Locate live:** `Grep "^# SECTION"` returns every banner with its *current* line (the numbers
   below are a snapshot — trust the Grep after edits shift them).
2. **Read one section:** `Read` with `offset`/`limit` for its range (its start line → the next
   section's start). e.g. Section 6C ≈ `offset 937, limit 440`.
3. **Find a symbol:** `Grep` its name; the table says which section owns it.

| § | Line | Purpose | Key symbols |
|---|------|---------|-------------|
| 0  | 28   | stdlib imports | — |
| 1  | 43   | runtime auto-install of the 3 pure-Python deps | `ensure_packages`, `REQUIRED_PACKAGES` |
| 2  | 96   | **all tuning knobs / config constants** | `OUTPUT_DIR`, `TIMEOUT`, `MAX_IMAGE_BYTES`, `MIN_GOOD_TEXT`, `HEADERS`, `_DESKTOP_HEADERS`, `JUNK_TAGS`, `JUNK_KEYWORDS`, `POSITIVE_HINTS`, `NEGATIVE_HINTS`, `EPUB_CSS` |
| 3  | 179  | small pure helpers | `normalize_url`, `sanitize_filename`, `text_len`, `xml` |
| 4  | 212  | fetch: retrying session, 403 UA retry, archive.today/Wayback/Jina recovery | `get_session`, `fetch_page`, `FetchError`, `_decode`, `fetch_via_archive`, `fetch_via_wayback`, `fetch_via_jina`, `ARCHIVE_HOSTS` |
| 5  | 434  | metadata (title/author) incl. JSON-LD | `find_jsonld_article`, `detect_title`, `detect_author`, `iter_jsonld_objects` |
| 6  | 510  | pure-Python Reader-Mode content extraction + JS-page fallbacks | `extract_main_content`, `score_container`, `link_density`, `jsonld_body_to_soup`, `find_amp_url`, `extract_from_noscript`, `extract_from_state`, `_looks_like_prose`, `extract_from_rss`, `find_rss_url` |
| 6B | 769  | special-site: X / Twitter tweets (syndication JSON) | `tweet_to_article`, `fetch_tweet`, `_tweet_token`, `TWEET_URL_RE` |
| 6C | 937  | special-site: X Articles (internal GraphQL, Draft.js, optional cookie auth) | `article_to_article`, `_article_once`, `_draftjs_to_html`, `_x_guest_client`, `_x_auth_client`, `_find_article_dict`, `_gql_get`, `ARTICLE_URL_RE`, `_GRAPHQL_REGISTRY`, `_LAST_ARTICLE_ERROR` |
| 7  | 1373 | junk removal / soup cleanup | `clean_soup` |
| 8  | 1418 | image download + EPUB embedding | `collect_images`, `pick_image_url`, `IMG_MIME` |
| 9  | 1475 | chapter splitting on h1/h2 | `split_into_chapters`, `SPLIT_MARK` |
| 10 | 1503 | hand-rolled EPUB3 writer (zip + templates) | `write_epub`, `soup_to_xhtml_body`, `XHTML_SHELL`, `CONTAINER_XML` |
| 11 | 1628 | output-path resolution (Android Download → cwd) | `resolve_output_path` |
| 12 | 1642 | orchestration: keep-best local extraction, network escalation, X error messages | `resolve_article` (URL → title/author/soup/base_url), `main`, `_candidate_quality`, `_is_truncated`, `_ARTICLE_ERROR_MESSAGES` |

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
