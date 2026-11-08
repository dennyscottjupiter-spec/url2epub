# ---
# purpose: Changelog shown on the About page, newest first; one entry per release or engine update
# exports: ENTRIES
# gotcha: add a new entry at the TOP and bump ui/__init__.VERSION in the same commit
# ---
ENTRIES = [
    ("Version 1.1.0", "8 November 2026", [
        "Pages open instantly: the slow sv-ttk theme is gone. Switching pages went from about 2.5 s to under 0.1 s.",
        "New look, Bindery: midnight bookcloth with gilt in dark mode, e-ink paper in light mode.",
        "Raised, rounded buttons that press down when clicked, with a visible keyboard focus ring.",
        "Sidebar with Ctrl+1 to Ctrl+5 shortcuts, and Ctrl+L to jump to the link field.",
        "Finished books appear as a cloth-bound cover with a foil glint.",
        "New app icon: a book with a link.",
        "This About page and changelog.",
        "A dummy test article, used to check a full conversion end to end.",
    ]),
    ("Version 1.0.0", "7 November 2026", [
        "Windows desktop app: convert a link with a live log and a cover preview.",
        "History of every conversion, with CSV and Markdown export.",
        "Connections check for the sites url2epub depends on.",
        "Settings for output folder, theme, timeout, image size and folder reveal.",
        "One-file url2epub.exe that runs without Python installed.",
    ]),
    ("Converter updates", "7 November 2026", [
        "Fixed seven bugs found in an audit, with offline regression tests.",
        "Fixed EPUB reading issues found while reading books on a device.",
        "Bylines that are just the word by no longer become the author.",
        "Clearer error messages when an X Article needs a login.",
    ]),
    ("Converter updates", "31 July 2026", [
        "X Articles open from both kinds of link, with optional sign-in through x_cookies.txt.",
        "Keeps the best of several extraction methods instead of the first that looks long enough.",
        "Reads newsletters from their RSS feed when the page itself needs JavaScript.",
        "Recovers text from noscript blocks and from the page's embedded data.",
        "Falls back to the Wayback Machine and Jina Reader when a site blocks the download.",
    ]),
    ("Converter updates", "21 July 2026", [
        "Converts X (Twitter) Articles.",
        "Retries X when it is briefly unavailable instead of saving an empty book.",
    ]),
    ("Converter updates", "20 July 2026", [
        "Converts X (Twitter) posts, with images and quoted posts.",
        "Falls back to archive.today when a site blocks the download.",
        "Retries failed downloads automatically.",
        "Fixed a crash on Wikipedia pages with newer Beautiful Soup versions.",
    ]),
]
