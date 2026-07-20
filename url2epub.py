#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
url2epub.py (v2) — Web article → Kindle-friendly EPUB, for PyDroid 3 on Android.

WHY v2 EXISTS
  v1 depended on lxml (via readability-lxml and ebooklib). lxml is a COMPILED
  C extension: pip on Android tries to build it from source, needs libxml2/
  libxslt dev headers that don't exist on the phone, and crashes. v2 removes
  every compiled dependency:

    * readability-lxml → replaced by a built-in pure-Python content scorer
                          (same core idea: rank containers by text density
                          and link density, keep the winner)
    * ebooklib → replaced by a hand-rolled EPUB3 writer using only
                          the standard library (an EPUB is just a ZIP with
                          XML inside — see Section 10)
    * lxml parser → replaced by Python's built-in "html.parser"

  Remaining pip deps: requests + beautifulsoup4. Both are PURE PYTHON, so
  auto-install on Android cannot hit a compiler.

EXTRACTION PIPELINE (handles JS-heavy sites better than v1)
  1. Score-based main-content extraction (Reader-Mode style).
  2. If weak → JSON-LD fallback: many JavaScript-rendered sites still ship
     the FULL article text inside <script type="application/ld+json">
     metadata for SEO. We mine it.
  3. If weak → AMP fallback: refetch the page's AMP version
     (<link rel="amphtml">), which is server-rendered plain HTML.
  4. If still weak → interactive choice: full cleaned page body, or abort.

  Hard limit (honest disclosure): pages that ONLY exist after executing
  JavaScript cannot be captured without a real browser engine, which
  PyDroid 3 cannot run.

OUTPUT
  /storage/emulated/0/Download/<Article_Title>.epub
  (falls back to the script's folder if storage permission is missing)
"""

# ----------------------------------------------------------------------------
# SECTION 0 — Standard library imports
# ----------------------------------------------------------------------------
import importlib
import json
import os
import re
import subprocess
import sys
import time
import zipfile # EPUB files ARE zip files — this is the writer
from html import escape # turns < > & " into safe XML entities
from urllib.parse import urljoin, urlparse

# ----------------------------------------------------------------------------
# SECTION 1 — Auto-install (pure-Python packages only → cannot need a compiler)
# ----------------------------------------------------------------------------
REQUIRED_PACKAGES = { # { import name : pip package name }
    "requests": "requests",
    "bs4": "beautifulsoup4",
}


def ensure_packages() -> None:
    """Import each required package; pip-install anything missing."""
    for import_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(import_name)
        except ImportError:
            print(f"[setup] '{pip_name}' not found — installing via pip ...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "--quiet",
                     "--disable-pip-version-check", pip_name]
                )
                importlib.invalidate_caches()
                importlib.import_module(import_name)
                print(f"[setup] '{pip_name}' installed OK.")
            except Exception as exc:
                sys.exit(
                    f"\nFATAL: could not install '{pip_name}' ({exc}).\n"
                    f"In PyDroid 3: menu → Pip → install '{pip_name}', then re-run."
                )


ensure_packages()

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
try:
    # urllib3 ships with requests; this is where the retry policy lives.
    from urllib3.util.retry import Retry
except Exception:                       # pragma: no cover - very old/embedded urllib3
    from requests.packages.urllib3.util.retry import Retry

PARSER = "html.parser" # Python's built-in HTML parser — no compilation ever

# ----------------------------------------------------------------------------
# SECTION 2 — Configuration
# ----------------------------------------------------------------------------
OUTPUT_DIR = "/storage/emulated/0/Download"
TIMEOUT = 30
MAX_IMAGE_BYTES = 10 * 1024 * 1024 # skip images larger than 10 MB
MIN_GOOD_TEXT = 500 # chars below this = "weak" extraction

# We present as a REAL modern Android phone — a Samsung Galaxy S24
# (model SM-S921B, Android 14) running Chrome for Android. This matches the
# tool's true home (PyDroid 3 on a phone) and, crucially, makes UA-sniffing
# sites serve us their normal server-rendered *mobile* HTML instead of a bot
# or "unsupported browser" page. We send the matching Client Hints
# (Sec-CH-UA*) too, because modern Chrome always does and some sites check.
#
# NOTE: we deliberately do NOT set Accept-Encoding — requests picks the
# encodings it can actually decode (gzip/deflate, plus brotli/zstd only if
# those libraries are present) and decompresses automatically. Advertising
# "br" by hand would hand us undecodable bytes on a stock PyDroid 3 install.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,image/apng,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?1",
    "Sec-Ch-Ua-Platform": '"Android"',
    "Upgrade-Insecure-Requests": "1",
}

JUNK_TAGS = [
    "script", "style", "noscript", "iframe", "form", "button", "input",
    "nav", "aside", "footer", "header", "svg", "video", "audio", "canvas",
    "select", "textarea", "dialog",
]

JUNK_KEYWORDS = [
    "cookie", "consent", "gdpr", "advert", "-ad-", "ad-slot", "adsbygoogle",
    "sponsor", "promo", "newsletter", "subscribe", "paywall", "social",
    "share", "sharing", "follow", "comment", "disqus", "related",
    "recommend", "sidebar", "popup", "modal", "overlay", "breadcrumb",
    "menu", "navigation", "pagination", "skip-link", "site-header",
    "site-footer", "widget", "masthead", "banner",
]

# Class/id hints used by the content SCORER (Section 6), not for deletion.
POSITIVE_HINTS = re.compile(
    r"article|content|entry|main|post|body|text|story|prose", re.I)
NEGATIVE_HINTS = re.compile(
    r"sidebar|comment|footer|header|menu|nav|promo|related|share|widget", re.I)

EPUB_CSS = """
body { font-family: serif; line-height: 1.5; margin: 0 5%; text-align: left; }
h1, h2, h3, h4 { font-family: sans-serif; line-height: 1.25;
                 margin: 1.4em 0 0.6em 0; page-break-after: avoid; }
h1 { font-size: 1.6em; } h2 { font-size: 1.35em; } h3 { font-size: 1.15em; }
p { margin: 0 0 0.9em 0; }
img { max-width: 100%; height: auto; display: block; margin: 1em auto; }
blockquote { margin: 1em 1.5em; padding-left: 0.8em;
             border-left: 3px solid #888; font-style: italic; }
pre, code { font-family: monospace; font-size: 0.9em; }
pre { white-space: pre-wrap; word-wrap: break-word;
      background: #f4f4f4; padding: 0.8em; margin: 1em 0; }
table { border-collapse: collapse; margin: 1em 0; width: 100%; }
th, td { border: 1px solid #999; padding: 0.4em; text-align: left; }
ul, ol { margin: 0 0 1em 1.2em; }
hr { border: none; border-top: 1px solid #aaa; margin: 1.5em 0; }
.titlepage { text-align: center; margin-top: 30%; }
.titlepage h1 { font-size: 2em; }
.titlepage .meta { color: #555; font-size: 0.95em; margin-top: 2em; }
"""


# ----------------------------------------------------------------------------
# SECTION 3 — Small helpers
# ----------------------------------------------------------------------------
def normalize_url(raw: str) -> str:
    """Add https:// to bare domains; reject obviously invalid input."""
    url = raw.strip()
    if not url:
        raise ValueError("Empty URL.")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc or "." not in parsed.netloc:
        raise ValueError(f"'{raw}' does not look like a valid URL.")
    return url


def sanitize_filename(title: str) -> str:
    """Article title → safe filename like Policy_on_the_AI_Exponential."""
    name = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE)
    name = re.sub(r"[\s-]+", "_", name).strip("_")
    return name[:80] or "article"


def text_len(soup_or_tag) -> int:
    """Characters of visible text inside a tag/soup."""
    return len(soup_or_tag.get_text(separator=" ", strip=True))


def xml(s: str) -> str:
    """Escape a string so it is safe inside XML/XHTML markup."""
    return escape(s or "", quote=True)


# ----------------------------------------------------------------------------
# SECTION 4 — Download (shared retrying session + archive.today recovery)
# ----------------------------------------------------------------------------
class FetchError(Exception):
    """
    A page could not be downloaded.

    `status`  = the HTTP status code, or None for a network-level failure.
    `blocked` = True for paywall / login-wall / bot-protection / rate-limit
                responses (401/402/403/429/451). resolve_article() treats a
                `blocked` error as "worth retrying through archive.today"
                rather than a hard stop.
    """
    def __init__(self, message: str, status=None, blocked: bool = False):
        super().__init__(message)
        self.status = status
        self.blocked = blocked


def _make_retry() -> Retry:
    """Retry policy for transient failures. Handles the urllib3 kwarg rename
       (allowed_methods in >=1.26, method_whitelist before that) so it works on
       whatever urllib3 PyDroid 3 happens to bundle."""
    base = dict(total=3, connect=3, read=3,
                backoff_factor=0.8,                     # waits ~0.8s, 1.6s, 3.2s
                status_forcelist=(429, 500, 502, 503, 504),
                raise_on_status=False,
                respect_retry_after_header=True)
    try:
        return Retry(allowed_methods=frozenset(["GET", "HEAD"]), **base)
    except TypeError:
        return Retry(method_whitelist=frozenset(["GET", "HEAD"]), **base)


_SESSION = None


def get_session() -> requests.Session:
    """One shared Session for the whole run: Galaxy-S24 headers + auto-retry on
       transient errors, reused for pages AND images (connection pooling)."""
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        s.headers.update(HEADERS)
        adapter = HTTPAdapter(max_retries=_make_retry())
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _SESSION = s
    return _SESSION


def _decode(resp) -> None:
    """Pick a sane text encoding for the response, in place.

    requests defaults to ISO-8859-1 (~cp1252) whenever the server sends no
    charset — which mangles UTF-8 pages (curly quotes, accents, em-dashes).
    So: trust an explicit charset from the Content-Type header, otherwise sniff
    the actual bytes with apparent_encoding, and fall back to UTF-8.
    """
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if resp.encoding is None or "charset" not in ctype:
        resp.encoding = resp.apparent_encoding or resp.encoding or "utf-8"


def fetch_page(url: str, quiet: bool = False) -> "tuple[str, str]":
    """
    Download a page and return (html_text, final_url_after_redirects).

    Raises FetchError on any failure (never sys.exit) so callers can react —
    e.g. fall back to archive.today for a blocked page, or move on from a
    failed AMP mirror. Transient errors are already retried by the session.
    """
    try:
        resp = get_session().get(url, timeout=TIMEOUT, allow_redirects=True)
    except requests.exceptions.SSLError as exc:
        raise FetchError(f"SSL certificate problem on this site ({exc})") from exc
    except requests.exceptions.Timeout as exc:
        raise FetchError(f"no response within {TIMEOUT}s (after retries)") from exc
    except requests.exceptions.ConnectionError as exc:
        raise FetchError(f"could not connect — {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise FetchError(f"request failed — {exc}") from exc

    if resp.status_code in (401, 402, 403, 451):
        raise FetchError(
            f"HTTP {resp.status_code} — access refused (paywall, login wall, "
            f"or bot protection)", status=resp.status_code, blocked=True)
    if resp.status_code == 404:
        raise FetchError("HTTP 404 — page not found. Check the URL.", status=404)
    if resp.status_code == 429:
        raise FetchError("HTTP 429 — rate limited (retries exhausted)",
                         status=429, blocked=True)
    if not resp.ok:
        raise FetchError(f"HTTP {resp.status_code} {resp.reason}.",
                         status=resp.status_code)

    ctype = resp.headers.get("Content-Type", "")
    if "html" not in ctype and "xml" not in ctype:
        raise FetchError(f"URL returned '{ctype}', not a web page.")

    _decode(resp)
    if not quiet:
        print(f"[fetch] got {len(resp.text):,} characters of HTML.")
    return resp.text, resp.url


# archive.today mirrors (same operator, different TLDs — we try each in turn).
ARCHIVE_HOSTS = ("https://archive.ph", "https://archive.today", "https://archive.is")
# Fingerprints of a Cloudflare "checking your browser" interstitial — a 200
# response we must NOT mistake for a real archived article.
_CF_CHALLENGE = ("just a moment", "checking your browser", "cf-browser-verification",
                 "attention required", "enable javascript and cookies")


def fetch_via_archive(url: str, quiet: bool = False) -> "tuple[str, str] | None":
    """
    Recover a soft-paywalled / JS-gated article from archive.today's public
    snapshot. Returns (html, snapshot_url) or None.

    HONEST CAVEAT: archive.today sits behind Cloudflare, which sometimes serves
    an anti-bot JavaScript challenge instead of the snapshot. We can't solve
    that challenge (no JS engine), so we detect it and give up cleanly rather
    than feeding a "checking your browser" page into the extractor. It also
    only helps SOFT paywalls that someone has already archived — it is not a
    key to hard subscriber-only content.
    """
    for host in ARCHIVE_HOSTS:
        snapshot = f"{host}/newest/{url}"
        try:
            resp = get_session().get(snapshot, timeout=TIMEOUT,
                                     allow_redirects=True)
        except requests.exceptions.RequestException:
            continue                        # host down → try the next mirror
        if resp.status_code != 200:
            continue                        # 404 = nothing archived for this URL
        _decode(resp)
        text = resp.text
        low = text[:4000].lower()
        if any(sig in low for sig in _CF_CHALLENGE):
            if not quiet:
                print(f"[archive] {host} returned a Cloudflare challenge — skipping.")
            continue
        if len(text) < 2000:                # "no results" / stub page
            continue
        if not quiet:
            print(f"[archive] recovered a snapshot via {host}")
        return text, resp.url
    return None


# ----------------------------------------------------------------------------
# SECTION 5 — Metadata (title, author) incl. JSON-LD
# ----------------------------------------------------------------------------
def iter_jsonld_objects(soup: BeautifulSoup):
    """
    Yield every JSON-LD object on the page.
    Sites embed structured data as <script type="application/ld+json">{...}.
    The JSON may be a single object, a list, or wrapped in an "@graph" list —
    this generator flattens all three shapes.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                yield item
                for sub in item.get("@graph", []) or []:
                    if isinstance(sub, dict):
                        yield sub


def find_jsonld_article(soup: BeautifulSoup) -> dict:
    """Return the first JSON-LD object that describes an article, else {}."""
    wanted = {"article", "newsarticle", "blogposting", "report", "techarticle"}
    for obj in iter_jsonld_objects(soup):
        types = obj.get("@type", "")
        types = [types] if isinstance(types, str) else types
        if any(str(t).lower() in wanted for t in types):
            return obj
    return {}


def detect_title(soup: BeautifulSoup, ld: dict) -> str:
    """Title priority: JSON-LD headline → og:title → <h1> → <title> tag."""
    candidates = [ld.get("headline", "")]
    og = soup.find("meta", attrs={"property": "og:title"})
    if og:
        candidates.append(og.get("content", ""))
    h1 = soup.find("h1")
    if h1:
        candidates.append(h1.get_text(" ", strip=True))
    if soup.title and soup.title.string:
        # Drop trailing " | SiteName" / " - SiteName" suffixes.
        candidates.append(re.split(r"\s+[|\-–—]\s+", soup.title.string)[0])
    for c in candidates:
        c = (c or "").strip()
        if c:
            return c
    return "Untitled Article"


def detect_author(soup: BeautifulSoup, ld: dict) -> str:
    """Author priority: JSON-LD → meta tags → visible byline element."""
    author = ld.get("author")
    if isinstance(author, list) and author:
        author = author[0]
    if isinstance(author, dict):
        author = author.get("name", "")
    if isinstance(author, str) and author.strip():
        return author.strip()

    for attrs in ({"name": "author"}, {"property": "article:author"},
                  {"name": "twitter:creator"}, {"name": "parsely-author"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content", "").strip():
            content = tag["content"].strip()
            if not content.startswith("http"):
                return content

    byline = soup.find(class_=re.compile(r"\b(byline|author)\b", re.I))
    if byline:
        t = re.sub(r"^\s*by[:\s]+", "",
                   byline.get_text(" ", strip=True), flags=re.I).strip()
        if 0 < len(t) <= 100:
            return t
    return ""


# ----------------------------------------------------------------------------
# SECTION 6 — Pure-Python main-content extraction (Reader-Mode style)
# ----------------------------------------------------------------------------
def link_density(tag) -> float:
    """Fraction of a container's text that sits inside links.
    Menus/footers are nearly 100% links; real prose is nearly 0%."""
    total = text_len(tag)
    if total == 0:
        return 1.0
    linked = sum(text_len(a) for a in tag.find_all("a"))
    return min(linked / total, 1.0)


def score_container(tag) -> float:
    """
    Score how 'article-like' a container is. The recipe (same family of
    heuristics as Readability/Arc90):
      + long paragraphs are strong evidence of prose
      + commas indicate real sentences (lists of links have few commas)
      + class/id names like 'article'/'content' add confidence
      - class/id names like 'sidebar'/'comments' subtract it
      - heavy link density disqualifies menus and footers
    """
    score = 0.0
    for p in tag.find_all(["p", "pre", "blockquote", "li"]):
        t = p.get_text(" ", strip=True)
        if len(t) < 25: # ignore stubs/captions
            continue
        score += min(len(t) / 100.0, 3.0) # cap so one huge <p> can't dominate
        score += t.count(",") * 0.5

    ident = " ".join(tag.get("class") or []) + " " + (tag.get("id") or "")
    if POSITIVE_HINTS.search(ident) or tag.name in ("article", "main"):
        score *= 1.4
    if NEGATIVE_HINTS.search(ident):
        score *= 0.3

    score *= (1.0 - link_density(tag)) # punish link-heavy blocks
    return score


def extract_main_content(full_soup: BeautifulSoup) -> BeautifulSoup | None:
    """Pick the best-scoring container from a *cleaned copy* of the page."""
    # Work on a copy so the original soup stays intact for fallbacks.
    soup = clean_soup(BeautifulSoup(str(full_soup), PARSER))

    candidates = soup.find_all(["article", "main", "section", "div", "td"])
    if not candidates:
        return None
    best, best_score = None, 0.0
    for tag in candidates:
        s = score_container(tag)
        if s > best_score:
            best, best_score = tag, s
    if best is None:
        return None
    # Climb up while the parent holds substantially more text — catches
    # articles split across sibling <div>s (a v1 weakness).
    while (best.parent is not None and best.parent.name not in ("body", "html",
           "[document]") and text_len(best.parent) > text_len(best) * 1.5
           and link_density(best.parent) < 0.3):
        best = best.parent
    return BeautifulSoup(str(best), PARSER)


def jsonld_body_to_soup(ld: dict) -> BeautifulSoup | None:
    """
    Fallback #2: build article HTML from JSON-LD 'articleBody'.
    JS-rendered sites often ship the complete text here for search engines,
    even when the visible DOM is empty before JavaScript runs.
    """
    body = ld.get("articleBody", "")
    if not isinstance(body, str) or len(body.strip()) < MIN_GOOD_TEXT:
        return None
    # articleBody is plain text; rebuild paragraphs from blank lines
    # (or from sentence groups if it arrives as one giant line).
    parts = re.split(r"\n\s*\n|\n", body.strip())
    paras = [p.strip() for p in parts if p.strip()]
    html = "".join(f"<p>{xml(p)}</p>" for p in paras)
    return BeautifulSoup(html, PARSER)


def find_amp_url(full_soup: BeautifulSoup, base_url: str) -> str:
    """Fallback #3: locate the page's AMP version (server-rendered HTML)."""
    link = full_soup.find("link", rel=lambda v: v and "amphtml" in v)
    if link and link.get("href"):
        return urljoin(base_url, link["href"])
    return ""


# ----------------------------------------------------------------------------
# SECTION 6B — Special-site handler: X / Twitter (the "it doesn't work" case)
# ----------------------------------------------------------------------------
# WHY THIS EXISTS
#   x.com / twitter.com is a login-gated JavaScript single-page app. A plain
#   GET (all this tool can do — PyDroid 3 has no browser engine to run JS)
#   returns an almost-empty HTML shell with NO tweet text in it, so the
#   Reader-Mode scorer in Section 6 finds nothing. That is *why* pasting an X
#   link used to fail completely.
#
#   THE TRICK: X still runs a public, unauthenticated "syndication" service
#   that powers embedded tweets on third-party websites. Given a tweet id it
#   returns the whole tweet as clean JSON — text, author, media, and any
#   quoted tweet — with NO login and NO JavaScript required:
#
#       https://cdn.syndication.twimg.com/tweet-result?id=<ID>&lang=en&token=<T>
#
#   The endpoint requires *some* non-empty `token` query param (an absent or
#   empty token just returns "{}"). The token is derived from the tweet id with
#   the same tiny formula X's own front-end uses — see _tweet_token(). We
#   verified empirically that the server does not actually re-check the
#   derivation (any non-empty token is accepted today), but we compute it
#   correctly anyway so the tool keeps working if X starts validating it.
#
# SCOPE (honest disclosure): this captures ONE tweet — plus its quoted tweet
#   and all attached photos/video posters. The public endpoint does NOT return
#   the downstream replies of a self-thread, so a multi-tweet thread collapses
#   to its first tweet. Whole profiles and timelines remain out of scope: those
#   genuinely require an authenticated, JavaScript-capable browser.

# A tweet URL is .../<user>/status/<digits> on x.com, twitter.com, the old
# mobile.twitter.com, or nitter-style mirrors. Capture the numeric status id.
TWEET_URL_RE = re.compile(
    r"^https?://(?:[\w.-]+\.)?(?:twitter|x)\.com/[^/]+/status(?:es)?/(\d+)",
    re.IGNORECASE)

TWEET_ENDPOINT = "https://cdn.syndication.twimg.com/tweet-result"
_B36_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def _js_number_to_base36(x: float) -> str:
    """
    Port of JavaScript's Number.prototype.toString(36) for a positive float.
    X's front-end builds the token as ((id / 1e15) * Math.PI).toString(36),
    and JavaScript renders the FRACTIONAL part in base 36 too — Python has no
    built-in that does that, so we reproduce it digit by digit.
    """
    if x <= 0:
        return "0"
    int_part = int(x)
    frac = x - int_part
    if int_part == 0:
        out = "0"
    else:
        out, n = "", int_part
        while n > 0:
            out = _B36_DIGITS[n % 36] + out
            n //= 36
    if frac == 0:
        return out
    out += "."
    # 30 base-36 fractional digits is far more than a float can distinguish;
    # we stop early once the fraction is exhausted.
    for _ in range(30):
        frac *= 36
        digit = int(frac)
        out += _B36_DIGITS[digit]
        frac -= digit
        if frac == 0:
            break
    return out


def _tweet_token(tweet_id: str) -> str:
    """X's syndication token: base36 of (id / 1e15 * pi), with 0s and '.' removed."""
    value = (int(tweet_id) / 1e15) * 3.141592653589793
    return re.sub(r"0+|\.", "", _js_number_to_base36(value))


def is_tweet_url(url: str) -> bool:
    """True if this URL points at a single tweet/post we can special-case."""
    return bool(TWEET_URL_RE.match(url))


def fetch_tweet(tweet_id: str) -> "dict | None":
    """Call the public syndication endpoint; return the tweet dict, or None."""
    params = {
        "id": tweet_id,
        "lang": "en",
        "token": _tweet_token(tweet_id),
        # The features string is what X's own embed widget sends; the endpoint
        # ignores unknown flags, so this is harmless but keeps us embed-like.
        "features": (
            "tfw_timeline_list:;tfw_follower_count_sunset:true;"
            "tfw_tweet_edit_backend:on;tfw_refsrc_session:on;"
            "tfw_show_business_verified_badge:on;"
        ),
    }
    try:
        r = get_session().get(TWEET_ENDPOINT, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # network error, non-200, or non-JSON body
        print(f"[x] syndication request failed: {exc}")
        return None
    if not isinstance(data, dict) or data.get("__typename") == "TweetTombstone":
        print("[x] tweet unavailable (deleted, protected, or age-restricted).")
        return None
    if not (data.get("text") or data.get("mediaDetails")):
        print("[x] syndication returned no usable tweet content.")
        return None
    return data


def _expand_tweet_text(data: dict) -> str:
    """
    Replace t.co shortlinks with their readable display URLs and strip the
    auto-appended trailing media shortlink. Returns plain (un-escaped) text.
    """
    text = data.get("text") or ""
    for u in (data.get("entities") or {}).get("urls", []) or []:
        short = u.get("url")
        shown = u.get("display_url") or u.get("expanded_url")
        if short and shown:
            text = text.replace(short, shown)
    # Any leftover t.co link is the media link X appends to the text → drop it.
    return re.sub(r"https?://t\.co/\w+", "", text).strip()


def _tweet_media_html(data: dict) -> str:
    """<img> tags (as an HTML string) for a tweet's photos and video posters."""
    html = ""
    for m in data.get("mediaDetails") or []:
        src = m.get("media_url_https") or m.get("media_url")
        if not src:
            continue
        kind = m.get("type", "photo")
        # An EPUB is static, so a video/GIF can only show its poster frame.
        note = "" if kind == "photo" else (
            f"<p class='meta'>[{xml(kind.replace('_', ' '))} — poster frame; "
            f"open on X to watch]</p>")
        html += f'<img src="{xml(src)}" alt="tweet media"/>{note}'
    return html


def _render_tweet_block(data: dict) -> str:
    """One tweet → HTML paragraphs + media (no heading; used for main & quote)."""
    text = _expand_tweet_text(data)
    paras = "".join(f"<p>{xml(p)}</p>"
                    for p in re.split(r"\n{1,}", text) if p.strip())
    return paras + _tweet_media_html(data)


def tweet_to_article(url: str) -> "dict | None":
    """
    Turn an x.com/twitter.com tweet URL into the same shape the generic
    pipeline produces: {title, author, article(BeautifulSoup), base_url}.
    Returns None if this isn't a tweet URL or the fetch fails (so main() can
    fall back to the normal pipeline — e.g. for a twitter.com *blog* link).
    """
    m = TWEET_URL_RE.match(url)
    if not m:
        return None
    tweet_id = m.group(1)
    print(f"[x] detected a tweet (id {tweet_id}); using X's public syndication "
          f"API — no login, no JavaScript needed ...")
    data = fetch_tweet(tweet_id)
    if data is None:
        return None

    user = data.get("user") or {}
    name = (user.get("name") or "").strip()
    handle = (user.get("screen_name") or "").strip()
    author = f"{name} (@{handle})" if name and handle else (name or handle or "X")

    text = _expand_tweet_text(data)
    when = ""
    created = data.get("created_at") or ""
    try:  # ISO 8601 → "07 November 2012"
        when = time.strftime("%d %B %Y", time.strptime(created[:19],
                                                        "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        pass

    slug = re.sub(r"\s+", " ", text)[:60].strip()
    title = f"{name or handle} on X - {slug}" if slug else f"{author} on X"

    body = f"<h1>{xml(author)}</h1>" + _render_tweet_block(data)

    quoted = data.get("quoted_tweet")
    if isinstance(quoted, dict):
        q_user = quoted.get("user") or {}
        q_author = (f"{q_user.get('name', '')} "
                    f"(@{q_user.get('screen_name', '')})").strip()
        body += (f"<blockquote><p class='meta'>Quoting {xml(q_author)}:</p>"
                 f"{_render_tweet_block(quoted)}</blockquote>")

    meta = f"— {xml(author)}" + (f", {when}" if when else "")
    body += f"<p class='meta'>{meta} · source: {xml(url)}</p>"

    return {"title": title, "author": author,
            "article": BeautifulSoup(body, PARSER), "base_url": url}


# ----------------------------------------------------------------------------
# SECTION 7 — Junk removal
# ----------------------------------------------------------------------------
def clean_soup(soup: BeautifulSoup) -> BeautifulSoup:
    """Remove ads, navigation, cookie banners, social widgets, comments..."""
    for tag in soup.find_all(JUNK_TAGS):
        tag.decompose()

    junk_re = re.compile("|".join(re.escape(k) for k in JUNK_KEYWORDS), re.I)
    for tag in soup.find_all(True):
        # CRITICAL — skip already-decomposed nodes (see the bug note below).
        # find_all() captured a STATIC snapshot of every tag before we began
        # deleting. When we decompose() a junk container in this loop, bs4
        # >= 4.13 nulls out .attrs (and .name) on that node AND every one of
        # its descendants. Those dead descendants are still sitting in our
        # snapshot, so when the loop later reaches one, `tag.get(...)` becomes
        # `None.get(...)` and raises:
        #     AttributeError: 'NoneType' object has no attribute 'get'
        # This is the real cause of the "crashes on Wikipedia" bug. Note the
        # once-suggested `tag.get("class") or []` does NOT fix it — it still
        # dereferences the None .attrs. Skipping decomposed nodes is the fix.
        # getattr(..., False) keeps this a no-op on the OLDER bs4 bundled with
        # PyDroid 3 (which lacks .decomposed and never had the crash anyway).
        if getattr(tag, "decomposed", False):
            continue
        if tag.name in ("html", "body"):
            continue
        ident = " ".join(tag.get("class") or []) + " " + (tag.get("id") or "") \
                + " " + (tag.get("role") or "")
        if junk_re.search(ident):
            # PROTECT REAL CONTENT from a false-positive keyword match. Some
            # sites put a junk word right in the ARTICLE container's own class:
            # Substack wraps every post in <article class="newsletter-post">,
            # and "newsletter" is in JUNK_KEYWORDS — so the naive rule deleted
            # the whole article (14k chars → 238). Genuine junk (nav, ads,
            # share bars, cookie/subscribe widgets) is ALWAYS either small or
            # mostly links, so we refuse to delete a big, link-sparse block.
            if text_len(tag) > 300 and link_density(tag) < 0.5:
                continue
            tag.decompose()

    # Strip inline styles/handlers and other presentational leftovers.
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.startswith("on") or attr in (
                    "style", "align", "bgcolor", "width", "height", "border"):
                # keep width/height ON images (helps some readers scale)
                if tag.name == "img" and attr in ("width", "height"):
                    continue
                del tag.attrs[attr]

    for a in soup.find_all("a"): # unwrap image-links
        if a.find("img"):
            a.unwrap()

    for tag in soup.find_all(["p", "div", "span", "section"]): # empties
        if not tag.get_text(strip=True) and not tag.find("img"):
            tag.decompose()
    return soup


# ----------------------------------------------------------------------------
# SECTION 8 — Image embedding
# ----------------------------------------------------------------------------
IMG_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".bmp": "image/bmp",
}


def pick_image_url(img_tag) -> str:
    """Real URL of an <img>, looking through lazy-loading attributes."""
    for attr in ("data-src", "data-original", "data-lazy-src", "src"):
        val = img_tag.get(attr)
        if val and not val.startswith("data:"):
            return val
    srcset = img_tag.get("srcset") or img_tag.get("data-srcset")
    if srcset: # take the LAST (= largest) candidate
        return srcset.split(",")[-1].strip().split()[0]
    return ""


def collect_images(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str, bytes]]:
    """
    Download every <img>; rewrite its src to an internal EPUB path.
    Returns [(internal_path, mime_type, raw_bytes), ...].
    Failed images are removed from the article (better than broken icons).
    """
    images, seen, count = [], {}, 0
    for img in soup.find_all("img"):
        raw = pick_image_url(img)
        if not raw:
            img.decompose()
            continue
        full_url = urljoin(base_url, raw)
        if full_url in seen:
            img.attrs = {"src": seen[full_url], "alt": img.get("alt", "")}
            continue
        try:
            r = get_session().get(full_url, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.content
            if not data or len(data) > MAX_IMAGE_BYTES:
                raise ValueError("empty or oversized image")
            ext = os.path.splitext(urlparse(full_url).path)[1].lower()
            if ext not in IMG_MIME:
                ctype = r.headers.get("Content-Type", "").split(";")[0].strip()
                ext = {v: k for k, v in IMG_MIME.items()}.get(ctype, ".jpg")
            count += 1
            internal = f"images/img{count:03d}{ext}"
            images.append((internal, IMG_MIME[ext], data))
            seen[full_url] = internal
            img.attrs = {"src": internal, "alt": img.get("alt", "")}
            print(f" [img] embedded {full_url[:70]}")
        except Exception as exc:
            print(f" [img] skipped {full_url[:70]} ({exc})")
            img.decompose()
    return images


# ----------------------------------------------------------------------------
# SECTION 9 — Chapter splitting (document order — v1 weakness fixed)
# ----------------------------------------------------------------------------
SPLIT_MARK = "\x00URL2EPUB_SPLIT\x00" # control chars never occur in articles


def split_into_chapters(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """
    Returns [(chapter_title, chapter_html), ...].

    v2 strategy: insert an invisible marker BEFORE every h1/h2 wherever it
    sits in the tree (v1 required all headings to share one parent), then
    split the serialized HTML on the marker. Re-parsing each fragment with
    BeautifulSoup repairs any tags broken by the cut.
    """
    headings = soup.find_all(["h1", "h2"])
    if len(headings) < 2: # short article → one chapter
        return [("Article", str(soup))]

    titles = ["Introduction"]
    for h in headings:
        titles.append(h.get_text(" ", strip=True) or "Section")
        h.insert_before(SPLIT_MARK) # marker survives serialization

    fragments = str(soup).split(SPLIT_MARK)
    chapters = []
    for title, frag in zip(titles, fragments):
        repaired = BeautifulSoup(frag, PARSER) # fixes unbalanced tags
        if text_len(repaired) > 0 or repaired.find("img"):
            chapters.append((title, str(repaired)))
    return chapters or [("Article", str(soup))]


# ----------------------------------------------------------------------------
# SECTION 10 — Hand-rolled EPUB3 writer (standard library only)
# ----------------------------------------------------------------------------
# An EPUB is a ZIP archive with a fixed skeleton:
# mimetype ← MUST be the first file, MUST be uncompressed
# META-INF/container.xml ← points to the "package document" below
# EPUB/content.opf ← manifest (every file) + spine (reading order)
# EPUB/nav.xhtml ← modern EPUB3 table of contents
# EPUB/toc.ncx ← legacy TOC (older Kindles still read this)
# EPUB/*.xhtml, css, images ← the actual book
# Every .xhtml file must be WELL-FORMED XML (hence the xml() escaping and
# BeautifulSoup's self-closing output for <img/>, <br/>, <hr/>).

XHTML_SHELL = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>{title}</title>
<link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>{body}</body>
</html>"""

CONTAINER_XML = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="EPUB/content.opf"
 media-type="application/oebps-package+xml"/></rootfiles>
</container>"""


def soup_to_xhtml_body(html_fragment: str) -> str:
    """
    Re-serialize an HTML fragment through BeautifulSoup, which outputs
    XHTML-style void elements (<img/>, <br/>, <hr/>) and escapes & < > —
    exactly what EPUB's XML parser requires.
    """
    frag = BeautifulSoup(html_fragment, PARSER)
    for bad in frag.find_all(["html", "body", "head"]):
        bad.unwrap() # keep only the inner content
    return frag.decode()


def write_epub(path: str, title: str, author: str, source_url: str,
               chapters: list[tuple[str, str]],
               images: list[tuple[str, str, bytes]]) -> None:
    """Assemble and write the complete .epub file."""
    uid = f"url2epub-{int(time.time())}"
    modified = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    today = time.strftime("%d %B %Y")

    # ---- Title page --------------------------------------------------------
    author_html = f"<p class='meta'>by {xml(author)}</p>" if author else ""
    titlepage = XHTML_SHELL.format(
        title=xml(title),
        body=(f"<div class='titlepage'><h1>{xml(title)}</h1>{author_html}"
              f"<p class='meta'>Source: {xml(source_url)}</p>"
              f"<p class='meta'>Generated on {today} by url2epub</p></div>"))

    # ---- Chapter files -----------------------------------------------------
    chap_files = [] # (filename, xhtml_string, chapter_title)
    for i, (chap_title, chap_html) in enumerate(chapters, 1):
        body = soup_to_xhtml_body(chap_html)
        if not body.lstrip().startswith(("<h1", "<h2")):
            body = f"<h2>{xml(chap_title)}</h2>" + body
        chap_files.append((f"chap{i:02d}.xhtml",
                           XHTML_SHELL.format(title=xml(chap_title), body=body),
                           chap_title))

    # ---- nav.xhtml (EPUB3 TOC) --------------------------------------------
    nav_lis = "".join(f'<li><a href="{fn}">{xml(t)}</a></li>'
                      for fn, _, t in chap_files)
    nav = XHTML_SHELL.format(
        title="Table of Contents",
        body=(f'<nav epub:type="toc" id="toc"><h1>Contents</h1>'
              f"<ol>{nav_lis}</ol></nav>"))

    # ---- toc.ncx (legacy TOC for older Kindle/readers) ----------------------
    navpoints = "".join(
        f'<navPoint id="np{i}" playOrder="{i}"><navLabel><text>{xml(t)}</text>'
        f'</navLabel><content src="{fn}"/></navPoint>'
        for i, (fn, _, t) in enumerate(chap_files, 1))
    ncx = (f'<?xml version="1.0" encoding="utf-8"?>'
           f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
           f'<head><meta name="dtb:uid" content="{uid}"/></head>'
           f'<docTitle><text>{xml(title)}</text></docTitle>'
           f'<navMap>{navpoints}</navMap></ncx>')

    # ---- content.opf (manifest = file list, spine = reading order) ---------
    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
        '<item id="titlepage" href="titlepage.xhtml" media-type="application/xhtml+xml"/>',
    ]
    spine_items = ['<itemref idref="titlepage"/>', '<itemref idref="nav"/>']
    for i, (fn, _, _) in enumerate(chap_files, 1):
        manifest_items.append(
            f'<item id="ch{i}" href="{fn}" media-type="application/xhtml+xml"/>')
        spine_items.append(f'<itemref idref="ch{i}"/>')
    for j, (ipath, mime, _) in enumerate(images, 1):
        manifest_items.append(
            f'<item id="im{j}" href="{ipath}" media-type="{mime}"/>')

    creator = f"<dc:creator>{xml(author)}</dc:creator>" if author else ""
    opf = (f'<?xml version="1.0" encoding="utf-8"?>'
           f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
           f'unique-identifier="uid">'
           f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'<dc:identifier id="uid">{uid}</dc:identifier>'
           f'<dc:title>{xml(title)}</dc:title>'
           f'<dc:language>en</dc:language>{creator}'
           f'<meta property="dcterms:modified">{modified}</meta>'
           f'</metadata>'
           f'<manifest>{"".join(manifest_items)}</manifest>'
           f'<spine toc="ncx">{"".join(spine_items)}</spine></package>')

    # ---- Write the ZIP ------------------------------------------------------
    with zipfile.ZipFile(path, "w") as z:
        # Spec rule: 'mimetype' first and STORED (uncompressed), so readers
        # can sniff the file type from its raw first bytes.
        z.writestr("mimetype", "application/epub+zip",
                   compress_type=zipfile.ZIP_STORED)
        deflate = zipfile.ZIP_DEFLATED
        z.writestr("META-INF/container.xml", CONTAINER_XML, deflate)
        z.writestr("EPUB/content.opf", opf, deflate)
        z.writestr("EPUB/nav.xhtml", nav, deflate)
        z.writestr("EPUB/toc.ncx", ncx, deflate)
        z.writestr("EPUB/style.css", EPUB_CSS, deflate)
        z.writestr("EPUB/titlepage.xhtml", titlepage, deflate)
        for fn, content, _ in chap_files:
            z.writestr(f"EPUB/{fn}", content, deflate)
        for ipath, _, data in images:
            z.writestr(f"EPUB/{ipath}", data, deflate)


# ----------------------------------------------------------------------------
# SECTION 11 — Output location
# ----------------------------------------------------------------------------
def resolve_output_path(filename: str) -> str:
    """Prefer Android's Download folder; fall back to the script's folder."""
    if os.path.isdir(OUTPUT_DIR) and os.access(OUTPUT_DIR, os.W_OK):
        return os.path.join(OUTPUT_DIR, filename)
    print(f"[warn] {OUTPUT_DIR} is not writable "
          f"(grant Storage permission to PyDroid 3 in Android settings).")
    fallback = os.path.join(os.getcwd(), filename)
    print(f"[warn] Saving to: {fallback}")
    return fallback


# ----------------------------------------------------------------------------
# SECTION 12 — Main program flow
# ----------------------------------------------------------------------------
def resolve_article(url: str) -> "tuple[str, str, BeautifulSoup, str]":
    """
    Turn a URL into (title, author, article_soup, base_url_for_images).

    Order of attack:
      0. SPECIAL-SITE handlers (currently X/Twitter). Sites that never expose
         their text to a non-JavaScript fetch get their own dedicated extractor
         and skip the generic pipeline entirely.
      1. GENERIC pipeline — fetch the page, read its metadata, then run the
         four-stage extraction fallback chain from Section 6:
             Reader-Mode scorer → JSON-LD articleBody → AMP mirror
             → interactive (full cleaned page body, or abort).
    """
    # --- Step 0: special-site handlers ------------------------------------
    # Add future per-site handlers here (each returns the same dict or None).
    special = tweet_to_article(url)          # None for any non-tweet URL
    if special is not None:
        print(f"[meta ] title : {special['title']}")
        print(f"[meta ] author: {special['author'] or '(not found)'}")
        print(f"[x    ] tweet captured: "
              f"{text_len(special['article']):,} characters.")
        return (special["title"], special["author"],
                special["article"], special["base_url"])

    # --- Step 1: generic pipeline -----------------------------------------
    print(f"\n[fetch] downloading {url} ...")
    used_archive = False
    try:
        html, final_url = fetch_page(url)
    except FetchError as exc:
        # A blocked page (paywall/login/bot wall) is worth one archive.today
        # attempt before we give up; any other error is a hard stop.
        if exc.blocked:
            print(f"[fetch] {exc}")
            print("[archive] blocked — trying archive.today snapshot ...")
            snap = fetch_via_archive(url)
            if snap is None:
                sys.exit(f"ERROR: {exc}\n"
                         f"       No archive.today snapshot was available "
                         f"either — this page needs a login or a real browser.")
            html, final_url = snap
            used_archive = True
        else:
            sys.exit(f"ERROR: {exc}")
    if not used_archive and final_url != url:
        print(f"[fetch] redirected to {final_url}")

    full_soup = BeautifulSoup(html, PARSER)
    ld = find_jsonld_article(full_soup)
    title = detect_title(full_soup, ld)
    author = detect_author(full_soup, ld)
    print(f"[meta ] title : {title}")
    print(f"[meta ] author: {author or '(not found)'}")

    # Extraction fallback chain: scorer → JSON-LD → AMP → archive → interactive.
    article = extract_main_content(full_soup)
    if article is None or text_len(article) < MIN_GOOD_TEXT:
        print("[extract] DOM scoring weak — trying JSON-LD articleBody ...")
        ld_article = jsonld_body_to_soup(ld)
        if ld_article is not None:
            article = ld_article
            print("[extract] recovered full text from JSON-LD metadata.")

    if article is None or text_len(article) < MIN_GOOD_TEXT:
        amp = find_amp_url(full_soup, final_url)
        if amp and amp != final_url:
            print(f"[extract] trying AMP version: {amp}")
            try:
                amp_html, _ = fetch_page(amp, quiet=True)
                amp_article = extract_main_content(BeautifulSoup(amp_html, PARSER))
                if amp_article is not None and \
                        text_len(amp_article) >= MIN_GOOD_TEXT:
                    article = amp_article
                    final_url = amp  # images now resolve against AMP
                    print("[extract] AMP version extracted successfully.")
            except FetchError:
                pass  # AMP fetch failed → keep going

    # Soft-paywall / weak-extraction recovery via archive.today. Skipped when
    # the page was ALREADY loaded from a snapshot at fetch time (no point
    # re-fetching the same snapshot).
    if (article is None or text_len(article) < MIN_GOOD_TEXT) and not used_archive:
        print("[extract] still weak — trying archive.today snapshot ...")
        snap = fetch_via_archive(url)
        if snap is not None:
            snap_html, snap_url = snap
            snap_soup = BeautifulSoup(snap_html, PARSER)
            snap_article = extract_main_content(snap_soup)
            if snap_article is not None and text_len(snap_article) >= MIN_GOOD_TEXT:
                article = snap_article
                final_url = snap_url            # images resolve against snapshot
                snap_ld = find_jsonld_article(snap_soup)
                if title in ("", "Untitled Article"):
                    title = detect_title(snap_soup, snap_ld)
                if not author:
                    author = detect_author(snap_soup, snap_ld)
                print("[extract] recovered article from archive.today.")

    if article is None or text_len(article) < MIN_GOOD_TEXT:
        print("\n[!] Extraction looks WEAK (very little text found).")
        print("    Possible causes: JavaScript-only site, paywall, odd layout.")
        print("\n 1) Use the FULL cleaned page body instead (may include clutter)")
        print(" 2) Abort")
        if input(" Choose 1 or 2: ").strip() == "1":
            body = full_soup.body or full_soup
            article = clean_soup(BeautifulSoup(str(body), PARSER))
            if text_len(article) < 200:
                sys.exit("ERROR: even the full page has almost no text. "
                         "This site needs JavaScript or a login.")
        else:
            sys.exit("Aborted by user.")

    print(f"[extract] clean article text: {text_len(article):,} characters.")
    return title, author, article, final_url


def main() -> None:
    print("=" * 60)
    print(" url2epub v2 — turn any article into a Kindle EPUB")
    print("=" * 60)

    try:
        url = normalize_url(input("\nPaste the article URL: "))
    except ValueError as exc:
        sys.exit(f"ERROR: {exc}")

    title, author, article, final_url = resolve_article(url)

    # --- Build ---------------------------------------------------------------
    print("\n[build] downloading images ...")
    images = collect_images(article, final_url)
    print(f"[build] {len(images)} image(s) embedded.")
    chapters = split_into_chapters(article)
    print(f"[build] {len(chapters)} chapter(s) created.")

    out_path = resolve_output_path(sanitize_filename(title) + ".epub")
    try:
        write_epub(out_path, title, author, final_url, chapters, images)
    except PermissionError:
        sys.exit(f"ERROR: no permission to write {out_path}. "
                 f"Grant Storage permission to PyDroid 3 and retry.")

    size_kb = os.path.getsize(out_path) / 1024
    print("\n" + "=" * 60)
    print(f" DONE ✔ {out_path} ({size_kb:,.0f} KB)")
    print(" Send it to your Kindle via the 'Send to Kindle' app or email.")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCancelled.")