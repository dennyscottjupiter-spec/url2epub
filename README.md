---
title: url2epub
status: current
updated: 2026-11-11
---

# 📖 url2epub

**Turn any web article into a clean, Kindle-friendly EPUB — from your Android phone,
or from Windows with the desktop app.**

`url2epub` is a single self-contained Python script that downloads a web
article, strips away the ads / nav / cookie-banners / share-buttons, embeds the
images, splits it into chapters, and writes a valid **EPUB3** you can read on a
Kindle or any e-reader.

---

## 🤖 PLATFORM: Android only, via PyDroid 3

> ### ⚠️ This is built to run on an **Android phone** inside the **[PyDroid 3](https://play.google.com/store/apps/details?id=ru.iiec.pydroid3)** app.
> ### It is **NOT** a desktop tool — not for Windows, not for macOS, not for Linux.

Every design decision in this project exists **because the target is a phone**:

| Decision | Why (Android/PyDroid 3 reason) |
| --- | --- |
| **Zero compiled dependencies** | PyDroid 3 has no C compiler; anything that builds from source (lxml, Pillow, ebooklib…) fails to `pip install` on the phone. |
| **Only `requests` + `beautifulsoup4` (+ `xclienttransaction` for X Articles)** | All pure Python, so the runtime auto-install can never hit a compiler. |
| **Hand-rolled EPUB writer + `html.parser`** | Avoids `ebooklib` and `lxml` entirely (both compiled). |
| **Saves to `/storage/emulated/0/Download/`** | That's the phone's Downloads folder, where "Send to Kindle" and file managers can see it. |
| **Samsung Galaxy S24 request fingerprint** | We identify as a real modern Android phone so sites serve normal mobile HTML. |

Running `url2epub.py` itself under desktop Python is **not a supported use** —
there's no `/storage/emulated/0/Download/`, so the file just lands in the
current folder. On Windows, use the desktop app below instead.

---

## 🖥️ Windows desktop app (`desktop/`)

A separate tkinter app ("Bindery" design: midnight bookcloth + gilt, or e-ink
paper) that drives the **same** `url2epub.py` engine — the Android script stays
one untouched-by-desktop file. Pages switch instantly (Ctrl+1 … Ctrl+5).

| Page | What it does |
| --- | --- |
| **Convert** | Paste a link → **Convert to EPUB**. Live progress log; the finished book appears as a cloth-bound cover with **Open EPUB** / **Show in folder**. Ctrl+L jumps to the link field. |
| **History** | Every conversion (saved or failed) — open, show in folder, copy link, export CSV / Markdown, clear. |
| **Connections** | Checks that the sites url2epub relies on (Wayback, archive.today, Jina, X) are reachable. |
| **Settings** | Output folder (default: your Downloads), dark/light theme, page timeout, largest image size, include images, show the book in its folder when done. |
| **About** | What the app does, privacy, credits, and the full changelog. |

- **Run from source:** `python3 desktop/url2epub_gui.py` (needs `requests`,
  `beautifulsoup4`, `xclienttransaction`; no theme package).
- **Build the exe:** `powershell -NoProfile -File build_exe.ps1` (needs
  `pyinstaller`) → `dist\url2epub.exe`, one file, no Python needed to run it.
- Settings and history live in `%APPDATA%\url2epub\`.
- To read X Articles, put `x_cookies.txt` (see Troubleshooting) in the output folder.
- **Tests:** `python3 -m pytest tests -q` — offline; covers the engine, the
  desktop core, every UI button, and a full conversion of a dummy test article.
- Icon: built from Microsoft [Fluent Emoji](https://github.com/microsoft/fluentui-emoji)
  (MIT): the blue book and the link.

---

## ✨ What it handles

✅ **Normal articles & blogs** — news sites, Wikipedia, personal blogs, old
   table-based HTML (e.g. Paul Graham essays).
✅ **X / Twitter posts** 🐦 — a plain fetch of `x.com` gets nothing (it's a
   login-gated JavaScript app), so url2epub routes tweet links to X's **public
   syndication API** and rebuilds the post — text, author, photos, video poster
   frames, and any quoted tweet — with **no login and no JavaScript**.
✅ **Substack & Medium** 📰 — full article text, even though their class names
   try to trip up naive readers.
✅ **JS-rendered sites that ship JSON-LD** — many single-page apps still embed
   the full article text in `<script type="application/ld+json">` for SEO;
   we mine it.
✅ **AMP mirrors** — if the normal page is thin, we try its `amphtml` version.
✅ **Soft paywalls & blocked pages** 🗄️ — we try a public **archive.today**
   snapshot, then the **Wayback Machine**, then **Jina Reader** (best-effort;
   see limits below).

## 🚫 What it can't do (honest limits)

- ❌ **Whole X/Twitter profiles or timelines**, or downstream **thread replies**
  — the public endpoint only returns one post (plus its quoted post & media).
- ❌ **Hard, subscriber-only paywalls** — archive.today only helps *soft*
  paywalls someone already archived, and it aggressively rate-limits bots.
- ❌ **Pure JavaScript-only pages** with no JSON-LD / AMP / server HTML — there
  is no browser engine on PyDroid 3 to run their scripts.

---

## 🚀 Install & run (on the phone)

1. Install **PyDroid 3** from the Google Play Store.
2. Copy `url2epub.py` onto the phone (paste it into a new file in PyDroid 3, or
   download it into the app's folder).
3. Grant PyDroid 3 the **Storage** permission (Android Settings → Apps →
   PyDroid 3 → Permissions) so it can save into **Downloads**.
4. Open `url2epub.py` in PyDroid 3 and press the yellow **▶ Run** button.
   - On first run it will `pip install` `requests`, `beautifulsoup4` and
     `xclienttransaction` automatically. If that fails, use PyDroid 3's **menu → Pip** to install
     them by hand, then run again.
5. **Paste the article URL** when prompted and press Enter.
6. Find the finished `.epub` in your **Downloads** folder → open it with your
   reader, or share it to **Send to Kindle**. 🎉

> The script is interactive (it reads the URL from the prompt) and takes **no
> command-line arguments**.

---

## 🧠 How it works (30-second tour)

The whole program is one file, organized into numbered `SECTION 0…12` banners
that follow the runtime order:

```
URL ─▶ normalize ─▶ [special handler? e.g. X/Twitter] ─▶ fetch (retrying,
      Galaxy-S24 headers) ─▶ read title/author (JSON-LD ▸ og: ▸ <h1> ▸ <title>)
      ─▶ extract main content:
             best of: Reader-Mode scorer ▸ JSON-LD body ▸ noscript ▸
             embedded state ▸ RSS feed
             then if weak/cut off: AMP ▸ archive.today ▸ Wayback ▸ Jina ▸ ask
      ─▶ clean junk ─▶ embed images ─▶ split into chapters
      ─▶ write EPUB3 (a ZIP of XML) ─▶ save to Downloads
```

The **content scorer** rewards long paragraphs and comma-rich prose, weights by
class/id hints (`article`/`content` up, `sidebar`/`comment` down), and punishes
link-heavy blocks (menus, footers) — then climbs parent nodes to reunite an
article split across sibling `<div>`s.

## 🛠️ Troubleshooting

| Symptom | Fix |
| --- | --- |
| `could not install 'requests'/'beautifulsoup4'` | PyDroid 3 → **menu → Pip** → install each by name, then re-run. |
| Saved to the script folder instead of Downloads | Grant PyDroid 3 the **Storage** permission and re-run. |
| `HTTP 403 — access refused` | The site blocks bots or needs a login; url2epub will try archive.today, but some pages simply can't be fetched. |
| An X link produces nothing | The post may be deleted, protected, or age-restricted (the API returns a "tombstone"). |
| X **Article** fails | `x.com/i/article/…` needs a logged-in session: save `x_cookies.txt` (two lines, `auth_token=…` and `ct0=…`, from x.com devtools → Application → Cookies) next to the script or in the output folder. As of 2026-11 X's page change also breaks the `xclienttransaction` library this path relies on, until it ships an update. |
| Extraction looks weak / wrong | Choose **1** at the prompt to embed the full cleaned page body instead. |

---

## ⚙️ For contributors

The single most important rule: **never introduce a dependency that needs a
compiler, and never switch the parser off `html.parser`.** If a task seems to
need lxml / Pillow / ebooklib / a JS engine, solve it with the standard library
or a pure-Python approach instead. See [`CLAUDE.md`](./CLAUDE.md) for the full
architecture and design constraints.

## 📄 License

[MIT](./LICENSE) — do whatever you like; no warranty.
