# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this is

`url2epub.py` — one self-contained ~2,020-line script turning a web-article URL into a Kindle-friendly
EPUB3. The engine stays one file (a hard product constraint). **It runs on Android only, inside
[PyDroid 3](https://play.google.com/store/apps/details?id=ru.iiec.pydroid3).** Running the script itself
under desktop CPython is how it's developed/tested, but is *not* a supported use.

**Windows desktop app (`desktop/`)** — a separate tkinter GUI that *imports* the engine; it never
changes it. `desktop/core/` (paths, settings, engine loader, runner, connections, reports/history) and
`desktop/ui/` (app shell + sidebar, one `*_view.py` per page, `widgets.Button`, cover, about + changelog,
`palette` tokens, `theme`); entry `desktop/url2epub_gui.py`; icon in `desktop/assets/`.
- `core/runner.convert()` is the only bridge: redirects the engine's `print`s to a log callback, turns its
  `sys.exit("ERROR: …")` into a `Result.error`, and answers its weak-extraction `input()` by temporarily
  setting a module-global `input` on the engine (a module global shadows the builtin). A lock serializes
  runs because the engine keeps state in module globals.
- `core/engine.apply_settings()` sets `TIMEOUT`, `MAX_IMAGE_BYTES`, `OUTPUT_DIR` (so `x_cookies.txt` is
  also found in the output folder). Settings/history: `%APPDATA%\url2epub\`.
- UI rule: worker threads only `app.call_soon()`; every messagebox/filedialog goes through `ui/dialogs.py`
  (tests monkeypatch it).
- **Theme = native ttk `clam` restyled from `ui/palette.py` tokens. Never bring back sv-ttk**: its
  image-drawn widgets made every page switch take 1.8–3.5 s on this PC (clam: ~50 ms). Non-ttk widgets
  (Text, Canvas, `widgets.Button`, sidebar) recolor through `theme.listen()`, called by `theme.apply()`.
  clam gotchas: Progressbar height comes from `arrowsize` (below 6 the fill vanishes), not `thickness`.
- `widgets.Button` is a Canvas "keycap" that mimics ttk.Button (`invoke/state/instate/cget/configure(text=)`).
  Pages are stacked in one grid cell and `tkraise()`d; `requests` is imported lazily (~0.4 s of startup).
- Changelog: add an entry at the top of `ui/changelog.py` and bump `ui/__init__.VERSION` together.
- Exe: `powershell -NoProfile -File build_exe.ps1` → one-file windowed `dist\url2epub.exe`
  (`url2epub-desktop.spec`: engine as hidden import, `desktop/assets` data + icon, xclienttransaction).

**Tests:** `python3 -m pytest tests -q` — fully offline: engine regressions (`test_url2epub.py`), each core
module, every UI button (`test_ui.py`, fake runner/dialogs/opener), and `test_e2e_dummy.py`, which serves
`tests/fixtures/dummy_article.html` on localhost and converts it with the REAL engine, then checks the EPUB.

## The overriding design constraint: zero compiled dependencies

PyDroid 3 has no C compiler and no libxml2/libxslt headers, so any dependency that builds from source
(lxml, `readability-lxml`, `ebooklib`, Pillow…) crashes on `pip install` on the phone. The `v2` rewrite
exists to purge them: extraction → hand-written pure-Python scorer; EPUB writer → `zipfile` + string
templates; parsing → stdlib `html.parser`.

Deps are `requests`, `beautifulsoup4`, `xclienttransaction` — all pure Python, auto-installed at runtime
(S1 `ensure_packages()`). `xclienttransaction` is a documented exception to both the "2 deps only" rule
and the 1,000-star bar (258 stars): it serves only X Articles (6C), where no official no-login way to
read one exists and hand-writing its header would duplicate ~300 lines of reverse-engineered logic.

**Rule for any change: never add a dependency that needs a compiler, and never switch the parser off
`html.parser`.** If a task seems to need lxml/Pillow/etc., use the stdlib or a pure-Python approach.

## Running it

```powershell
python3 url2epub.py
```

Interactive: prompts for a URL on stdin, takes no CLI args, and on weak extraction may prompt "full page
body vs abort". Output goes to Android's `/storage/emulated/0/Download/`, falling back to cwd when that
isn't writable — always the case on desktop. To run non-interactively, feed the URL to stdin, but on
Windows **never via a PowerShell `|` pipe** (it prepends a UTF-8 BOM and the script rejects the URL):

```powershell
python3 -c "import subprocess; subprocess.run(['python3','url2epub.py'], input='https://example.com/article\n', text=True, encoding='utf-8')"
```

## Architecture

Organized top-to-bottom into numbered `SECTION 0…12` banners in runtime-pipeline order. Keep that
structure — put new code in the matching section, keep helpers pure. `resolve_article()` (S12) turns a
URL into `(title, author, article_soup, base_url)`; `main()` builds the EPUB. The core logic is the
extraction fallback chain `resolve_article` drives.

### 0. Special-site handlers (run FIRST, before the generic pipeline)

For sites that never expose text to a JS-free fetch. Each returns `{title, author, article, base_url}`
or `None` to fall through to the next handler, then the generic pipeline.

- **X / Twitter tweets (6B)** — `tweet_to_article()` pulls the post from X's public syndication JSON
  (`cdn.syndication.twimg.com/tweet-result`, no login/JS), incl. media and quoted tweets; `_tweet_token()`
  reproduces X's base36 token.
- **X Articles (6C)** — no public syndication endpoint exists, so it drives X's *internal* GraphQL: a
  guest session (`/1.1/guest/activate.json` + a self-generated CSRF token X only checks for cookie/header
  match), an `x-client-transaction-id` per request (from `xclienttransaction`, derived from `x.com/home`
  + its `ondemand.s.*.js` bundle), and a GraphQL `doc_id` looked up **live** from a community registry
  (`fa0311/TwitterInternalAPIDocument`, regenerated daily) — X rotates doc_ids every 2-4 weeks to break
  scrapers that hardcode one.
  - **THE id-type bug (fixed):** an Article's own id is a DIFFERENT number from any tweet hosting it —
    verified empirically. `ARTICLE_URL_RE` captures both `x.com/<handle>/article/<id>` and
    `x.com/i/article/<id>`. `_article_once()` always tries the cheap guest `TweetResultByRestId` first
    (works when `<id>` is really a hosting tweet's id) and treats ANY empty result as proof `<id>` is the
    Article's own entity id — which needs `ArticleEntityResultByRestId`, and **X serves that only to a
    logged-in session** (guest = HTTP 404, verified; no login-free path exists for those URLs).
    `_find_article_dict()` recursively hunts the response for the `{title, content_state}` shape rather
    than trusting a guessed wrapper key, since that success shape is unverified.
  - **Optional cookie auth:** `_x_auth_client()` mirrors `_x_guest_client()` using a real session from
    `x_cookies.txt` — plain text, two lines `auth_token=<…>` and `ct0=<…>` from a logged-in x.com session
    (devtools → Application → Cookies), looked up next to `url2epub.py` then in `OUTPUT_DIR`. Absent file =
    silent guest fallback (normal, not an error). **Never commit it** (`.gitignore`'d).
  - **Body:** a Draft.js rich-text attachment rendered by `_draftjs_to_html()`. **Quirk:** X sends inline
    style names TitleCase (`"Bold"`), not Draft.js's `"BOLD"` — match case-insensitively.
  - **Fragility:** everything but the doc_id lookup is a fixed point that breaks silently if X changes its
    obfuscation or schema; no self-healing short of a new `xclienttransaction` release or a manual fix.
  - **Reliability:** *transient* failures are retried with backoff (`_ARTICLE_ATTEMPTS`, `_article_once`
    raises `_ArticleTransient`); a *definitive* miss sets `_LAST_ARTICLE_ERROR` to `needs_login` /
    `auth_rejected` / `not_found` / `transient_exhausted` and returns `None`. `resolve_article()` reads it
    and exits with the **actual cause** (`_ARTICLE_ERROR_MESSAGES` — e.g. step-by-step cookie instructions
    for `needs_login`) instead of a blanket "rate limited, try again".

### 1. Fetch (S4)

Shared `requests.Session` (`get_session()`) with a **Samsung Galaxy S24** fingerprint + Sec-CH-UA hints
and auto retry/backoff (HTTPAdapter + urllib3 Retry) on 429/5xx. `fetch_page()` **raises `FetchError`**
(no longer `sys.exit()`s) so callers can react — a `blocked` error triggers the archive.today → Wayback →
Jina escalation (S12). On a plain 403 it first retries once with `_DESKTOP_HEADERS` (fixes sites that
UA-sniff the *mobile* fingerprint rather than blocking bots generally). `_decode()` fixes requests'
cp1252-default UTF-8 mangling.

### 2. Metadata (S5)

Title/author from `<script type="application/ld+json">` first, then `og:`/meta tags, then the visible DOM.

### 3. Extraction — local-best, then a network escalation chain (S6/S12)

The local stage runs EVERY cheap strategy and keeps the **best** candidate by
`quality = text_len * (1 - link_density)` — *not* the first to merely clear `MIN_GOOD_TEXT` (500 chars),
which used to let a weak-but-passing extraction permanently block a better later stage. A candidate with
no links/images/headings/lists (`_RICH_TAGS`) scores ×0.8, so formatted DOM text beats an equal plain
copy. A JSON-LD `wordCount` more than 2× what was extracted marks it truncated ("continue reading" cuts)
even when the char count passed. RSS and embedded-state candidates go through `clean_soup` like the rest.

1. **Score-based DOM** (`extract_main_content` → `score_container`) — Reader-Mode heuristics: reward long
   paragraphs and comma counts, weight by `POSITIVE_HINTS`/`NEGATIVE_HINTS` class/id names, multiply down
   by link density, then climb parents to reunite an article split across sibling `<div>`s.
2. **JSON-LD `articleBody`** — JS-rendered sites often ship the full text here for SEO.
3. **`<noscript>`** (`extract_from_noscript`) — many SPAs ship a server-rendered copy there; reparsed
   through the same DOM scorer. Only tried if 1-2 were weak/truncated.
4. **Embedded JSON state** (`extract_from_state`) — ONE generic recursive miner instead of five framework
   handlers: `__NEXT_DATA__`/`__NUXT__`/`__APOLLO_STATE__`/`__remixContext`/RSC chunks all reduce to
   "there's JSON in a `<script>`". `_looks_like_prose` (space ratio, brace/semicolon density,
   base64-likeness, sentence breaks) keeps it from mistaking minified JS for article text.
5. **RSS `content:encoded`** (`extract_from_rss`) — newsletters (Substack/Medium/Ghost) publish the full
   body in their feed even when the live page is JS-gated. Parsed with **regex over the raw feed text,
   never BeautifulSoup**: `html.parser` treats `<link>` as void, so a bare Atom `<link>url</link>` is
   unreachable via bs4 (broke 3/10 feeds); the `"xml"` parser needs lxml, so it's out.

If the best local candidate is still weak (`_is_weak`) or truncated, escalate over the network. Weak runs
every step 6-10; truncated-but-not-weak runs only 6-8, a replacement must be longer (`_improves`), and a
`[warn]` line is logged if the book may still be cut off:

6. **AMP** — refetch the `<link rel="amphtml">` version (server-rendered plain HTML).
7. **archive.today** (`fetch_via_archive()`) — on a blocked initial fetch (401/402/403/429/451) OR
   still-weak extraction. Best-effort: detects Cloudflare/rate-limit and returns `None` gracefully.
8. **Wayback** (`fetch_via_wayback()`) — `archive.org/wayback/available`; public, documented, generally
   more reliable than archive.today.
9. **Jina Reader** (`fetch_via_jina()`) — `r.jina.ai` renders JS server-side. **Must use its own clean
   session/UA**, never the shared one: the Galaxy S24 fingerprint draws a 403 Cloudflare challenge in
   front of Jina (verified) while a plain non-browser UA passes. **Skips x.com entirely** — Jina blocks it
   with `AbuseAlleviationError` (verified), which is why X needs handlers 6B/6C. Strips Jina's
   `Title:`/`URL Source:`/`Markdown Content:` header before wrapping the body as paragraphs, reusing the
   title when the page has none.
10. **Interactive** — offer the full cleaned page body, or abort.

A blocked *initial* fetch escalates archive → Wayback → Jina before giving up; Jina's return there bypasses
the rest of the pipeline, since it hands back an already-built article, not a raw page to re-extract from.

### 4-7. Cleanup, images, chapters, EPUB

- **Cleanup** (`clean_soup`, S7) — strips `JUNK_TAGS`, elements whose class/id/role match `JUNK_KEYWORDS`,
  inline styles/handlers, and empties. `JUNK_KEYWORDS` *deletes* nodes while `POSITIVE_HINTS`/
  `NEGATIVE_HINTS` only *score* — don't conflate the two. **Guard:** it refuses to delete a *large,
  link-sparse* block even on a keyword match (protects e.g. Substack's `<article class="newsletter-post">`
  from the `newsletter` keyword).
- **Images** (S8) — download + embed each `<img>` as an internal EPUB path, resolving lazy-load attributes
  (`data-src`, `srcset`, …); failed/oversized images are dropped.
- **Chapters** (S9) — inject an invisible marker before every `h1`/`h2`, serialize, split on the marker,
  re-parse each fragment (repairs tags broken by the cut; handles headings with no shared parent).
- **EPUB writer** (S10) — an EPUB is a ZIP with a fixed skeleton: `mimetype` **first and STORED
  (uncompressed)**, then `META-INF/container.xml`, `EPUB/content.opf` (manifest + spine), `nav.xhtml`
  (EPUB3 TOC) + `toc.ncx` (legacy TOC), then XHTML/CSS/images. Every XHTML file **must be well-formed
  XML** — hence content is re-serialized through BeautifulSoup (void elements self-closed) and every
  interpolated string passes through `xml()`. `soup_to_xhtml_body(fragment, base_url)` makes every
  `<a href>` absolute and unwraps `javascript:` links.

Tuning knobs live in **Section 2** (`OUTPUT_DIR`, `TIMEOUT`, `MAX_IMAGE_BYTES`, `MIN_GOOD_TEXT`, `HEADERS`,
`_DESKTOP_HEADERS`, junk/hint lists), plus `ARCHIVE_HOSTS`/`_JINA_HEADERS` (S4), `TWEET_URL_RE` (6B),
`ARTICLE_URL_RE`/`_GRAPHQL_REGISTRY` (6C).

## Navigating this file efficiently (token budget)

`url2epub.py` is ~19K tokens. **Don't full-read it for a localized change** — use this catalog to pick the
one or two sections you need. `Grep "^# SECTION"` returns every banner with its *current* line (the numbers
below are a snapshot); `Read` with `offset`/`limit` for the range from its start line to the next section's.
To find a symbol, `Grep` its name — the table says which section owns it.

| § | Line | Purpose | Key symbols |
|---|------|---------|-------------|
| 0  | 28   | stdlib imports | — |
| 1  | 43   | runtime auto-install of the 3 pure-Python deps | `ensure_packages`, `REQUIRED_PACKAGES` |
| 2  | 96   | **all tuning knobs / config constants** | `OUTPUT_DIR`, `TIMEOUT`, `MAX_IMAGE_BYTES`, `MIN_GOOD_TEXT`, `HEADERS`, `_DESKTOP_HEADERS`, `JUNK_TAGS`, `JUNK_KEYWORDS`, `POSITIVE_HINTS`, `NEGATIVE_HINTS`, `EPUB_CSS` |
| 3  | 180  | small pure helpers | `normalize_url`, `sanitize_filename`, `text_len`, `xml` |
| 4  | 218  | fetch: retrying session, 403 UA retry, archive/Wayback/Jina recovery | `get_session`, `fetch_page`, `FetchError`, `_decode`, `fetch_via_archive`, `fetch_via_wayback`, `fetch_via_jina`, `ARCHIVE_HOSTS` |
| 5  | 456  | metadata (title/author) incl. JSON-LD | `find_jsonld_article`, `detect_title`, `detect_author`, `iter_jsonld_objects` |
| 6  | 538  | Reader-Mode extraction + JS-page fallbacks | `extract_main_content`, `score_container`, `link_density`, `jsonld_body_to_soup`, `find_amp_url`, `extract_from_noscript`, `extract_from_state`, `_looks_like_prose`, `extract_from_rss`, `find_rss_url` |
| 6B | 800  | special-site: X / Twitter tweets (syndication JSON) | `tweet_to_article`, `fetch_tweet`, `_tweet_token`, `TWEET_URL_RE` |
| 6C | 968  | special-site: X Articles (internal GraphQL, Draft.js, cookie auth) | `article_to_article`, `_article_once`, `_draftjs_to_html`, `_x_guest_client`, `_x_auth_client`, `_find_article_dict`, `_gql_get`, `ARTICLE_URL_RE`, `_GRAPHQL_REGISTRY`, `_LAST_ARTICLE_ERROR` |
| 7  | 1418 | junk removal / soup cleanup | `clean_soup` |
| 8  | 1463 | image download + EPUB embedding | `collect_images`, `pick_image_url`, `IMG_MIME` |
| 9  | 1520 | chapter splitting on h1/h2 | `split_into_chapters`, `SPLIT_MARK` |
| 10 | 1548 | hand-rolled EPUB3 writer (zip + templates) | `write_epub`, `soup_to_xhtml_body`, `XHTML_SHELL`, `CONTAINER_XML` |
| 11 | 1700 | output-path resolution (Android Download → cwd) | `resolve_output_path` |
| 12 | 1714 | orchestration: keep-best extraction, network escalation, X errors | `resolve_article`, `main`, `_candidate_quality`, `_is_truncated`, `_is_weak`, `_improves`, `_RICH_TAGS`, `_ARTICLE_ERROR_MESSAGES` |

## Git workflow

No feature branches — work happens directly on `main`. Every change gets an atomic commit, pushed to
`origin/main` before a task is done. "Full housekeeping" here means committed + pushed + no stray branches
(not a merge — there's nothing to merge into).

## Final verification (last step of every round, before "done")

Run all of these; a round is done only when every one passes. Report each result, and name any you couldn't run.

1. **Full suite:** `python3 -m pytest tests -q` → 0 failed (includes the offline e2e dummy conversion).
2. **Tk noise:** `cmd /c "python3 -m pytest tests -q -s > %TEMP%\full.txt 2>&1"`, then count `invalid command name`
   in that file → 0. Plain `-q` captures passing tests' output and hides this noise, so a `-q` count of 0 proves nothing.
3. **Real engine pass:** convert 2-3 live URLs through the stdin pattern in "Running it" (one plain news
   article, one newsletter/feed-backed post, one X post). Each EPUB must be a valid zip with `mimetype`
   first, open its chapters, and show images and absolute links. Keep it short: this PC is slow.
4. **Real desktop pass:** launch `python3 desktop/url2epub_gui.py`, convert a live URL, then click Open EPUB,
   Show in folder, History (open/reveal/export CSV + Markdown), Settings, About (new version + changelog
   entry visible). Take a screenshot of each page. tkinter is not a browser page, so Playwright can't drive it.
   Use computer-use when available; otherwise say so and list exactly what remains unclicked.
5. **No stray files:** `git status --short` clean, with no EPUBs or `x_cookies.txt` left in the repo.
   Do not rebuild `dist\url2epub.exe` unless asked.

## Known gotcha: bs4 ≥ 4.13 crash (the REAL cause)

The script targets the older BeautifulSoup PyDroid 3 ships but must not crash on newer bs4 (e.g. 4.15 on
this dev machine). The "crashes on Wikipedia" bug: `clean_soup` iterates a **static** `find_all(True)`
snapshot and `decompose()`s junk containers mid-loop. On bs4 ≥ 4.13 `decompose()` nulls `.attrs` (and
`.name`) on the node **and all its descendants** — still sitting in the snapshot — so a later `tag.get(...)`
becomes `None.get(...)` → `AttributeError: 'NoneType' object has no attribute 'get'`.

**Fix — SKIP already-decomposed nodes:** `if getattr(tag, "decomposed", False): continue` at the top of the
loop (a no-op on older bs4). ⚠️ `tag.get("class") or []` does **NOT** fix it (it still dereferences the
`None` `.attrs`). A crash on desktop may be this version skew, not the site.

<!-- claude-reflect: learned rules (saved from the band; edit freely) -->
## Learned rules
- Before declaring any work done, run every available kind of test (smoke, pytest, real-user pass, etc.) and finalize only when all pass.
<!-- end claude-reflect -->
