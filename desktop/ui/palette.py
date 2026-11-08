# ---
# purpose: Design tokens: "Bindery" palettes (midnight bookcloth + gilt, e-ink paper + ink) and fonts
# exports: PALETTES, FONT_*, COVER
# ---
DARK = {
    "sidebar": "#111A31", "bg": "#172240", "raised": "#1F2C51", "field": "#131D37",
    "border": "#34446F", "text": "#ECE7D9", "muted": "#9CA6C4", "faint": "#5E6A8E",
    "accent": "#D7AE55", "accent_hover": "#E6C276", "accent_down": "#B98F37", "on_accent": "#1E1607",
    "accent_lip": "#8C6A22", "lip": "#0C1328", "ribbon": "#D7AE55", "select": "#2D3D6B",
    "ok": "#86C29A", "bad": "#E58B7B", "focus": "#E6C276",
}
LIGHT = {
    "sidebar": "#DDDFD7", "bg": "#ECEDE6", "raised": "#F8F8F4", "field": "#FFFFFF",
    "border": "#BFC3B6", "text": "#1C2340", "muted": "#596079", "faint": "#9AA0A8",
    "accent": "#26305C", "accent_hover": "#344078", "accent_down": "#1B2347", "on_accent": "#F4EEDC",
    "accent_lip": "#10162F", "lip": "#B9BDB0", "ribbon": "#B8862B", "select": "#D5DAE8",
    "ok": "#2F7A4A", "bad": "#B2432F", "focus": "#B8862B",
}
PALETTES = {"dark": DARK, "light": LIGHT}

# the book cover is the same oxblood-cloth-and-gilt object in both themes, so it pops off either page
COVER = {
    "cloth": "#6A2231", "spine": "#4E1724", "gilt": "#E4BE66", "gilt_soft": "#C9A15A",
    "pages": "#E9E4D4", "pages_edge": "#C9C2AC", "shadow_dark": "#0B1124", "shadow_light": "#C6C9BD",
}

FONT_UI = ("Segoe UI Variable Text", 10)
FONT_UI_BOLD = ("Segoe UI Variable Text", 10, "bold")
FONT_SMALL = ("Segoe UI Variable Text", 9)
FONT_ENTRY = ("Segoe UI Variable Text", 12)
FONT_NAV = ("Segoe UI Variable Text", 11)
FONT_TITLE = ("Sitka Display", 22)
FONT_SUBTITLE = ("Segoe UI Variable Text", 10)
FONT_SECTION = ("Sitka Heading", 14, "bold")
FONT_WORDMARK = ("Sitka Banner", 20, "bold")
FONT_MONO = ("Cascadia Mono", 9)
FONT_COVER_TITLE = ("Sitka Banner", 15, "bold")
FONT_COVER_AUTHOR = ("Sitka Text", 10, "italic")
FONT_COVER_ORNAMENT = ("Sitka Text", 11)
