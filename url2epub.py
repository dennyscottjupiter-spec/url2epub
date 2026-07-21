#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
url2epub.py (v2) — Web article -> Kindle-friendly EPUB3.

ANDROID ONLY (PyDroid 3 app), not Windows/macOS/Linux. Runs under desktop
CPython too, but only as a dev harness (Download path falls back to cwd).

Zero-compiled-dependencies rule: v1 used lxml (readability-lxml, ebooklib),
which fails to compile on Android. v2 replaces all of it with pure Python —
content scorer (Sec 6), hand-rolled EPUB writer (Sec 10), html.parser. Deps
are requests + beautifulsoup4 + xclienttransaction (all pure Python,
auto-installed by Sec 1; the 3rd is a deliberate, documented exception for
X Articles support only — see Sec 6C). Never add a compiled dependency
(lxml/Pillow/ebooklib/a JS engine).

Pipeline (resolve_article, Sec 12): special-site handlers first (Sec 6B
X/Twitter, Sec 6C X Articles), else generic fetch + 5-stage extraction
fallback (DOM scorer -> JSON-LD articleBody -> AMP mirror -> archive.today
-> interactive full-page choice). Pages needing JS or a hard paywall can't
be captured — no browser engine on PyDroid 3.

Output: /storage/emulated/0/Download/<Title>.epub, falls back to cwd.
Usage: open in PyDroid 3, press Run, paste the URL when prompted (stdin only).
"""

# ----------------------------------------------------------------------------
# SECTION 0 — Standard library imports
# ----------------------------------------------------------------------------
import importlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
import zipfile # EPUB = a zip file
from html import escape
from urllib.parse import urljoin, urlparse

# ----------------------------------------------------------------------------
# SECTION 1 — Auto-install (pure-Python packages only → cannot need a compiler)
# ----------------------------------------------------------------------------
REQUIRED_PACKAGES = { # { import name : pip package name }
    "requests": "requests",
    "bs4": "beautifulsoup4",
    # 3rd dependency, pure Python (depends only on bs4 itself — no compiler
    # risk). Exception to the 2-dep rule: no official API exists for reading
    # an X Article without a paid OAuth app, and there is no way to derive
    # the required x-client-transaction-id header (Section 6C) without
    # replicating ~300 lines of reverse-engineered logic that a maintained
    # library already does. Below the 1,000-star bar normally required for
    # unofficial deps — accepted deliberately for this one feature.
    "x_client_transaction": "xclienttransaction",
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
from x_client_transaction import ClientTransaction
from x_client_transaction.utils import get_ondemand_file_url
try:
    from urllib3.util.retry import Retry
except Exception:                       # very old/embedded urllib3
    from requests.packages.urllib3.util.retry import Retry

PARSER = "html.parser" # no compiled parser, ever

# ----------------------------------------------------------------------------
# SECTION 2 — Configuration
# ----------------------------------------------------------------------------
OUTPUT_DIR = "/storage/emulated/0/Download"
TIMEOUT = 30
MAX_IMAGE_BYTES = 10 * 1024 * 1024 # skip images larger than 10 MB
MIN_GOOD_TEXT = 500 # chars below this = "weak" extraction

# Samsung Galaxy S24 fingerprint (matches Sec-CH-UA client hints below) so
# UA-sniffing sites serve normal mobile HTML instead of a bot/unsupported page.
# No Accept-Encoding: requests advertises only codecs it can decode locally;
# hardcoding "br" would risk undecodable bytes on a stock PyDroid 3 install.
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
    """A page could not be downloaded. `blocked` = paywall/login/bot/rate-limit
       (401/402/403/429/451) — resolve_article() retries these via archive.today."""
    def __init__(self, message: str, status=None, blocked: bool = False):
        super().__init__(message)
        self.status = status
        self.blocked = blocked


def _make_retry() -> Retry:
    """Retry policy for transient failures. Handles the urllib3 kwarg rename
       (allowed_methods vs method_whitelist) across bundled versions."""
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
    """Recover a soft-paywalled/JS-gated article from archive.today's public
       snapshot. Returns (html, snapshot_url) or None — best-effort only:
       Cloudflare sometimes serves a JS challenge we can't solve, and only
       already-archived SOFT paywalls are recoverable at all."""
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
    """Yield every JSON-LD object on the page (flattens plain/list/@graph shapes)."""
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
    """Score how 'article-like' a container is (Readability/Arc90-style):
       long paragraphs + comma density help, sidebar/nav hints and link
       density hurt."""
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
    """Fallback #2: build article HTML from JSON-LD 'articleBody', which
       JS-rendered sites often ship in full even when the DOM is empty."""
    body = ld.get("articleBody", "")
    if not isinstance(body, str) or len(body.strip()) < MIN_GOOD_TEXT:
        return None
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
# SECTION 6B — Special-site handler: X / Twitter
# ----------------------------------------------------------------------------
# x.com is a login-gated JS SPA; a plain GET returns an empty shell, so the
# Reader-Mode scorer finds nothing. Workaround: X's public, unauthenticated
# "syndication" endpoint (powers embedded tweets) returns a tweet as clean
# JSON — text, author, media, quoted tweet — given just its id + a token
# derived by _tweet_token() (any non-empty token is currently accepted, but
# we compute the real one in case that changes).
# Scope: ONE tweet + its quoted tweet + media posters — no thread replies,
# no profiles/timelines (those need a real authenticated browser).

# .../<user>/status/<digits> on x.com, twitter.com, or nitter-style mirrors.
TWEET_URL_RE = re.compile(
    r"^https?://(?:[\w.-]+\.)?(?:twitter|x)\.com/[^/]+/status(?:es)?/(\d+)",
    re.IGNORECASE)

TWEET_ENDPOINT = "https://cdn.syndication.twimg.com/tweet-result"
_B36_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def _js_number_to_base36(x: float) -> str:
    """Port of JS's Number.prototype.toString(36) for a positive float —
       Python has no built-in for base-36 fractional digits."""
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
    for _ in range(30): # far more digits than a float can distinguish
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
        "features": ( # what X's own embed widget sends; unknown flags are ignored
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
    """Replace t.co shortlinks with display URLs; drop the trailing media shortlink."""
    text = data.get("text") or ""
    for u in (data.get("entities") or {}).get("urls", []) or []:
        short = u.get("url")
        shown = u.get("display_url") or u.get("expanded_url")
        if short and shown:
            text = text.replace(short, shown)
    return re.sub(r"https?://t\.co/\w+", "", text).strip()


def _tweet_media_html(data: dict) -> str:
    """<img> tags (as an HTML string) for a tweet's photos and video posters."""
    html = ""
    for m in data.get("mediaDetails") or []:
        src = m.get("media_url_https") or m.get("media_url")
        if not src:
            continue
        kind = m.get("type", "photo")
        note = "" if kind == "photo" else ( # EPUB is static: video/GIF -> poster only
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
    """Turn a tweet URL into {title, author, article, base_url} — the same
       shape the generic pipeline produces. None if not a tweet URL or fetch failed."""
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
# SECTION 6C — Special-site handler: X Articles (long-form posts)
# ----------------------------------------------------------------------------
# x.com/<user>/article/<id> is 100% client-rendered — no og:title, no
# JSON-LD, nothing (verified empirically) — and unlike a plain tweet there is
# no public syndication endpoint, so this goes through X's *internal*
# GraphQL API the same way X's own logged-out web client does:
#   1. A guest session: POST /1.1/guest/activate.json for a guest token, plus
#      a SELF-GENERATED csrf token echoed as both a ct0 cookie and an
#      x-csrf-token header (X only checks that the two match — it never
#      needs to issue one for a guest).
#   2. An x-client-transaction-id header X now requires on every GraphQL
#      call: a per-request signature derived from values embedded in X's own
#      obfuscated ondemand.s.<hash>.js bundle. We don't derive this
#      ourselves — the `xclienttransaction` pip package (Section 1) does, by
#      fetching x.com/home and that JS file once per run.
#   3. The GraphQL "doc_id" (query id) that selects TweetResultByRestId. X
#      rotates these every 2-4 weeks specifically to break scrapers that
#      hardcode one, so instead it's looked up LIVE from a community
#      registry (fa0311/TwitterInternalAPIDocument, regenerated daily) —
#      the one piece of this that's actually self-healing against rotation.
#
# An Article is a rich-text attachment on an ordinary tweet — its own
# "article id" is a DIFFERENT number from the tweet hosting it — so fetching
# one is just TweetResultByRestId on that tweet with fieldToggles asking for
# the article's Draft.js body alongside the normal tweet fields. Verified
# empirically against a real article on x.com/Write.
#
# HONEST DISCLOSURE: every piece above except the doc_id lookup is a fixed
# point that breaks the moment X reshuffles its obfuscation or GraphQL
# schema, with no way for this script to self-heal — only a new release of
# `xclienttransaction` (or a manual fix here) can. TRANSIENT failures (the
# common one: a 429 when X rate-limits guest activation) are retried with
# backoff (_ARTICLE_ATTEMPTS); a definitive miss returns None at once. When it
# ultimately returns None for a recognised X URL, resolve_article() does NOT
# fall through to the generic pipeline (that only yields a junk near-empty
# EPUB for X's JS-only shell) — it exits with a clear "try again" message.

ARTICLE_URL_RE = re.compile(
    r"^https?://(?:[\w.-]+\.)?x\.com/(?:[^/]+/article|i/article)/(\d+)",
    re.IGNORECASE)

# The public web client's own bearer token — stable for years, shared by
# every unauthenticated request X's logged-out site makes (rotating it would
# break x.com itself for logged-out visitors, not just scrapers).
_GRAPHQL_BEARER = ("Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8"
                    "xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA")
_GRAPHQL_REGISTRY = ("https://raw.githubusercontent.com/fa0311/"
                      "TwitterInternalAPIDocument/develop/docs/json/GraphQL.json")
_ARTICLE_FIELD_TOGGLES = {
    "withArticleRichContentState": True, "withArticlePlainText": False,
    "withArticleSummaryText": False, "withGrokAnalyze": False,
    "withDisallowedReplyControls": False, "withPayments": False,
    "withAuxiliaryUserLabels": False,
}

_gql_registry_cache = None


def is_article_url(url: str) -> bool:
    return bool(ARTICLE_URL_RE.match(url))


def _gql_operation(op_name: str) -> "tuple[str, dict] | None":
    """(doc_id, features) for a GraphQL operation, fetched LIVE each run so a
       rotated doc_id can't silently break this (see Section 6C banner)."""
    global _gql_registry_cache
    if _gql_registry_cache is None:
        try:
            _gql_registry_cache = get_session().get(
                _GRAPHQL_REGISTRY, timeout=TIMEOUT).json()
        except Exception:
            _gql_registry_cache = []
    for entry in _gql_registry_cache:
        exp = entry.get("exports", {})
        if exp.get("operationName") == op_name:
            features = {k: v["value"] == "true"
                        for k, v in exp["metadata"]["featureSwitch"].items()}
            return exp["queryId"], features
    return None


def _x_guest_client() -> "tuple[requests.Session, ClientTransaction] | None":
    """A logged-out X session ready to call the internal GraphQL API. Uses
       its OWN Session (not the shared get_session()) because it carries an
       X-specific Authorization/csrf header set that must never leak onto
       unrelated requests made later in the same run."""
    s = requests.Session()
    s.headers.update(HEADERS)
    adapter = HTTPAdapter(max_retries=_make_retry())   # same 429/5xx backoff as get_session()
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    try:
        home = s.get("https://x.com/home", timeout=TIMEOUT)
        home_soup = BeautifulSoup(home.content, PARSER)
        ondemand_url = get_ondemand_file_url(response=home_soup)
        ondemand = s.get(ondemand_url, timeout=TIMEOUT)
        ct = ClientTransaction(home_page_response=home_soup,
                               ondemand_file_response=ondemand.text)

        csrf_token = secrets.token_hex(16)
        s.cookies.set("ct0", csrf_token, domain=".x.com")
        s.headers["Authorization"] = _GRAPHQL_BEARER
        guest = s.post("https://api.x.com/1.1/guest/activate.json",
                       timeout=TIMEOUT).json()["guest_token"]
        s.cookies.set("gt", guest, domain=".x.com")
        s.headers.update({
            "x-guest-token": guest, "x-csrf-token": csrf_token,
            "x-twitter-active-user": "yes", "x-twitter-client-language": "en",
            "Referer": "https://x.com/", "content-type": "application/json",
        })
        return s, ct
    except Exception as exc:
        print(f"[article] could not establish an X session: {exc}")
        return None


def _gql_get(s: requests.Session, ct: ClientTransaction, op_name: str,
            variables: dict, field_toggles: dict = None) -> "dict | None":
    """One signed GraphQL GET: fresh transaction-id + live doc_id per call."""
    op = _gql_operation(op_name)
    if op is None:
        print(f"[article] '{op_name}' is missing from the live doc_id "
              f"registry — X's API may have changed.")
        return None
    doc_id, features = op
    params = {"variables": json.dumps(variables), "features": json.dumps(features)}
    if field_toggles:
        params["fieldToggles"] = json.dumps(field_toggles)
    url = f"https://x.com/i/api/graphql/{doc_id}/{op_name}"
    try:
        s.headers["x-client-transaction-id"] = ct.generate_transaction_id(
            method="GET", path=urlparse(url).path)
        r = s.get(url, params=params, timeout=TIMEOUT)
    except Exception as exc:
        print(f"[article] {op_name} request failed: {exc}")
        return None
    if not r.ok:
        print(f"[article] {op_name} request failed: HTTP {r.status_code}")
        return None
    return r.json()


_DRAFTJS_BLOCK_TAGS = {
    "header-one": "h1", "header-two": "h2", "header-three": "h3",
    "header-four": "h4", "header-five": "h5", "header-six": "h6",
    "blockquote": "blockquote", "code-block": "pre",
}
_DRAFTJS_INLINE_TAGS = {"BOLD": "b", "ITALIC": "i", "STRIKETHROUGH": "s", "CODE": "code"}


def _draftjs_block_html(block: dict, entity_map: dict) -> str:
    """One Draft.js block -> HTML, applying its inline style + link ranges."""
    text = block.get("text", "")
    ranges = block.get("inlineStyleRanges", []) + block.get("entityRanges", [])
    cuts = sorted({0, len(text)} | {r["offset"] for r in ranges}
                  | {r["offset"] + r["length"] for r in ranges})

    out = []
    for start, end in zip(cuts, cuts[1:]):
        chunk = xml(text[start:end])
        for r in block.get("inlineStyleRanges", []):
            if r["offset"] <= start and end <= r["offset"] + r["length"]:
                # X sends TitleCase ("Bold"), not Draft.js's usual "BOLD".
                tag = _DRAFTJS_INLINE_TAGS.get(r["style"].upper())
                if tag:
                    chunk = f"<{tag}>{chunk}</{tag}>"
        for r in block.get("entityRanges", []):
            if r["offset"] <= start and end <= r["offset"] + r["length"]:
                entity = entity_map.get(str(r["key"]), {})
                if entity.get("type") == "LINK":
                    href = xml(entity.get("data", {}).get("url", ""))
                    chunk = f'<a href="{href}">{chunk}</a>'
        out.append(chunk)
    return "".join(out)


def _draftjs_to_html(content_state: dict) -> str:
    """An Article's body (Draft.js blocks + entityMap) -> HTML."""
    entity_map = {e["key"]: e["value"] for e in content_state.get("entityMap", [])}
    html, list_tag = [], None
    for block in content_state.get("blocks", []):
        btype = block.get("type", "unstyled")
        wanted_list = ("ul" if btype == "unordered-list-item" else
                      "ol" if btype == "ordered-list-item" else None)
        if list_tag and list_tag != wanted_list:
            html.append(f"</{list_tag}>")
            list_tag = None
        if wanted_list and not list_tag:
            html.append(f"<{wanted_list}>")
            list_tag = wanted_list

        inner = _draftjs_block_html(block, entity_map)
        if wanted_list:
            html.append(f"<li>{inner}</li>")
        else:
            tag = _DRAFTJS_BLOCK_TAGS.get(btype, "p")
            html.append(f"<{tag}>{inner}</{tag}>")
    if list_tag:
        html.append(f"</{list_tag}>")
    return "".join(html)


class _ArticleTransient(Exception):
    """A retryable failure of the X Article path — a network blip, a rate-limit
       (429 on guest activation is common), or a transient GraphQL error. Raised
       by one attempt so article_to_article() can back off and try again, as
       opposed to a *definitive* miss (deleted/subscriber-only) which returns
       None straight away and must NOT be retried."""


_ARTICLE_ATTEMPTS = 3   # X rate-limits guest access hard; a couple of retries with backoff clears it


def _article_once(url: str, tweet_id: str) -> "dict | None":
    """One full X-Article fetch attempt. Returns the built dict on success,
       None if the id definitively has no readable article, or raises
       _ArticleTransient for a failure worth retrying."""
    client = _x_guest_client()
    if client is None:
        raise _ArticleTransient("could not establish an X guest session")
    s, ct = client

    data = _gql_get(s, ct, "TweetResultByRestId", {
        "tweetId": tweet_id, "withCommunity": False,
        "includePromotedContent": False, "withVoice": False,
    }, field_toggles=_ARTICLE_FIELD_TOGGLES)
    if data is None:
        raise _ArticleTransient("GraphQL request failed (HTTP error or rate limit)")

    tweet = (data.get("data") or {}).get("tweetResult", {}).get("result", {}) or {}
    if not tweet and data.get("errors"):
        # No result at all + an errors array => usually a rate-limit/auth blip,
        # not a genuinely article-less tweet. Worth another attempt.
        raise _ArticleTransient(
            f"X returned an error: {data['errors'][0].get('message', 'unknown')}")

    art = ((tweet.get("article") or {}).get("article_results") or {}).get("result")
    if not art:
        print("[article] no article content on that id — may be deleted, "
              "subscriber-only, or X changed its response shape.")
        return None

    user = ((tweet.get("core") or {}).get("user_results") or {}).get("result", {}) or {}
    core, legacy = user.get("core") or {}, user.get("legacy") or {}
    name = core.get("name") or legacy.get("name") or ""
    handle = core.get("screen_name") or legacy.get("screen_name") or ""
    author = f"{name} (@{handle})" if name and handle else (name or handle or "X")

    title = art.get("title") or "Untitled Article"
    cover = ((art.get("cover_media") or {}).get("media_info") or {}).get("original_img_url")
    body = f"<h1>{xml(title)}</h1><p class='meta'>by {xml(author)}</p>"
    if cover:
        body += f'<img src="{xml(cover)}" alt="cover"/>'
    body += _draftjs_to_html(art.get("content_state") or {})
    body += f"<p class='meta'>source: {xml(url)}</p>"

    n_blocks = len((art.get("content_state") or {}).get("blocks", []))
    print(f"[article] captured '{title}' — {n_blocks} block(s).")
    return {"title": title, "author": author,
            "article": BeautifulSoup(body, PARSER), "base_url": url}


def article_to_article(url: str) -> "dict | None":
    """Turn an x.com Article URL into {title, author, article, base_url} —
       same shape tweet_to_article() produces. Retries transient failures
       (X's guest API rate-limits aggressively) with backoff; returns None
       only on a definitive miss or after all attempts are exhausted, so
       resolve_article() can then react (see there — it no longer silently
       emits an empty EPUB for a recognised X URL)."""
    m = ARTICLE_URL_RE.match(url)
    if not m:
        return None
    tweet_id = m.group(1)
    print(f"[article] detected an X Article (tweet id {tweet_id}); "
          f"using X's internal GraphQL API — this is the fragile path, "
          f"see Section 6C ...")

    for attempt in range(1, _ARTICLE_ATTEMPTS + 1):
        try:
            return _article_once(url, tweet_id)     # dict on success, None if definitively no article
        except _ArticleTransient as exc:
            if attempt < _ARTICLE_ATTEMPTS:
                wait = 1.5 * attempt                # ~1.5s, 3s — lets X's rate limiter reset
                print(f"[article] {exc} — retrying in {wait:.0f}s "
                      f"(attempt {attempt + 1}/{_ARTICLE_ATTEMPTS}) ...")
                time.sleep(wait)
            else:
                print(f"[article] gave up after {_ARTICLE_ATTEMPTS} attempts: {exc}")
    return None


# ----------------------------------------------------------------------------
# SECTION 7 — Junk removal
# ----------------------------------------------------------------------------
def clean_soup(soup: BeautifulSoup) -> BeautifulSoup:
    """Remove ads, navigation, cookie banners, social widgets, comments..."""
    for tag in soup.find_all(JUNK_TAGS):
        tag.decompose()

    junk_re = re.compile("|".join(re.escape(k) for k in JUNK_KEYWORDS), re.I)
    for tag in soup.find_all(True):
        # bs4 >= 4.13 decompose()-in-loop gotcha — see CLAUDE.md. Skip dead nodes.
        if getattr(tag, "decomposed", False):
            continue
        if tag.name in ("html", "body"):
            continue
        ident = " ".join(tag.get("class") or []) + " " + (tag.get("id") or "") \
                + " " + (tag.get("role") or "")
        if junk_re.search(ident):
            # Don't wipe a real article whose class happens to match a junk
            # keyword (e.g. Substack's "newsletter-post"): junk is always
            # small or link-heavy, so protect big, link-sparse blocks.
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
    """Download every <img>, rewrite its src to an internal EPUB path, return
       [(internal_path, mime_type, raw_bytes), ...]. Failed images are dropped."""
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
    """[(chapter_title, chapter_html), ...]. Inserts an invisible marker before
       every h1/h2 (works regardless of tree position), splits the serialized
       HTML on it, then re-parses each fragment to repair broken tags."""
    headings = soup.find_all(["h1", "h2"])
    if len(headings) < 2: # short article -> one chapter
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
# An EPUB is a ZIP with a fixed skeleton: mimetype (first, uncompressed) ->
# META-INF/container.xml -> EPUB/content.opf (manifest+spine) -> nav.xhtml
# (EPUB3 TOC) + toc.ncx (legacy TOC) -> xhtml/css/image files. Every .xhtml
# must be well-formed XML (hence xml() escaping + bs4's self-closing tags).

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
    """Re-serialize through BeautifulSoup for XHTML-style void elements
       (<img/>, <br/>) and & < > escaping, as EPUB's XML parser requires."""
    frag = BeautifulSoup(html_fragment, PARSER)
    for bad in frag.find_all(["html", "body", "head"]):
        bad.unwrap()
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
    """Turn a URL into (title, author, article_soup, base_url_for_images).
       Special-site handlers (X/Twitter, X Articles) first, else the generic
       fetch + extraction fallback chain from Section 6."""
    # Add future per-site handlers here (each returns the same dict or None).
    special = tweet_to_article(url) or article_to_article(url)
    if special is not None:
        print(f"[meta ] title : {special['title']}")
        print(f"[meta ] author: {special['author'] or '(not found)'}")
        print(f"[x    ] captured {text_len(special['article']):,} characters.")
        return (special["title"], special["author"],
                special["article"], special["base_url"])

    # A recognised X post/article whose handler came back empty will NEVER
    # extract via the generic pipeline (X serves a JS-only shell), so falling
    # through would just emit a misleading near-empty EPUB. Fail loudly instead.
    if is_tweet_url(url) or is_article_url(url):
        sys.exit(
            "ERROR: this is an X/Twitter post, but X's internal API could not be\n"
            "       reached — it rate-limits guest access hard. The generic reader\n"
            "       cannot read X's JavaScript-only pages, so no usable EPUB would\n"
            "       be produced. Wait ~a minute and try again; the limit resets fast.")

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

    # Skip if already loaded from a snapshot at fetch time.
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
    """Interactive entry point: URL -> resolve_article -> build & write the .epub."""
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