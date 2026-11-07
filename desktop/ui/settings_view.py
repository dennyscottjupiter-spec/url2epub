# ---
# purpose: Settings tab: output folder, theme, timeouts, image and folder options, save/reset
# exports: SettingsView
# depends: core/settings.py, core/paths.py, core/opener.py, ui/dialogs.py
# ---
import tkinter as tk
from tkinter import ttk

from core import opener, paths, settings
from ui import dialogs


def _int(text, fallback):
    try:
        return int(text)
    except ValueError:
        return fallback


class SettingsView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=12)
        self.app = app
        self.output_var = tk.StringVar()
        self.theme_var = tk.StringVar()
        self.timeout_var = tk.StringVar()
        self.image_var = tk.StringVar()
        self.embed_var = tk.BooleanVar()
        self.folder_var = tk.BooleanVar()
        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="Save books to").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 12))
        ttk.Entry(self, textvariable=self.output_var).grid(row=0, column=1, sticky="ew")
        self.browse_btn = ttk.Button(self, text="Browse…", command=self.browse)
        self.browse_btn.grid(row=0, column=2, padx=(8, 0))

        ttk.Label(self, text="Theme").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 12))
        themes = ttk.Frame(self)
        themes.grid(row=1, column=1, sticky="w")
        self.dark_rb = ttk.Radiobutton(themes, text="Dark", value="dark", variable=self.theme_var, command=self.pick_theme)
        self.light_rb = ttk.Radiobutton(themes, text="Light", value="light", variable=self.theme_var, command=self.pick_theme)
        self.dark_rb.pack(side="left", padx=(0, 16))
        self.light_rb.pack(side="left")

        ttk.Label(self, text="Page timeout (seconds)").grid(row=2, column=0, sticky="w", pady=4, padx=(0, 12))
        ttk.Spinbox(self, from_=5, to=120, textvariable=self.timeout_var, width=8).grid(row=2, column=1, sticky="w")

        ttk.Label(self, text="Largest image (MB)").grid(row=3, column=0, sticky="w", pady=4, padx=(0, 12))
        ttk.Spinbox(self, from_=1, to=50, textvariable=self.image_var, width=8).grid(row=3, column=1, sticky="w")

        self.embed_cb = ttk.Checkbutton(self, text="Include images", variable=self.embed_var)
        self.embed_cb.grid(row=4, column=0, columnspan=3, sticky="w", pady=4)
        self.folder_cb = ttk.Checkbutton(
            self, text="Show the book in its folder when done", variable=self.folder_var,
        )
        self.folder_cb.grid(row=5, column=0, columnspan=3, sticky="w", pady=4)

        ttk.Label(
            self, text="To read X (Twitter) Articles, save your x_cookies.txt in the output folder.",
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(16, 0))

        buttons = ttk.Frame(self)
        buttons.grid(row=7, column=0, columnspan=3, sticky="w", pady=(16, 0))
        self.save_btn = ttk.Button(buttons, text="Save settings", style="Accent.TButton", command=self.save)
        self.reset_btn = ttk.Button(buttons, text="Restore defaults", command=self.reset)
        self.appdata_btn = ttk.Button(buttons, text="Open settings folder", command=self.open_appdata)
        for btn in (self.save_btn, self.reset_btn, self.appdata_btn):
            btn.pack(side="left", padx=(0, 8))
        self.load_from(app.settings)

    def pick_theme(self):
        self.app.set_theme(self.theme_var.get())

    def browse(self):
        picked = dialogs.choose_folder(self, self.output_var.get())
        if picked:
            self.output_var.set(picked)

    def collect(self):
        cur = self.app.settings
        out = self.output_var.get().strip()
        # keep the "" default when the shown folder is still the default, so it follows Downloads
        output = "" if out in ("", str(paths.default_output_dir())) else out
        s = settings.Settings(
            output_dir=output,
            theme=self.theme_var.get(),
            timeout=_int(self.timeout_var.get(), cur.timeout),
            max_image_mb=_int(self.image_var.get(), cur.max_image_mb),
            embed_images=self.embed_var.get(),
            open_folder_after=self.folder_var.get(),
        )
        return settings.normalize(s)

    def save(self):
        s = self.collect()
        settings.save(s, self.app.settings_path)
        self.app.settings = s
        self.load_from(s)
        self.app.set_status(f"Settings saved. Books are saved to {s.resolved_output_dir()}")

    def reset(self):
        if not dialogs.confirm(self, "Restore defaults", "Reset every setting to its default value?"):
            return
        s = settings.Settings()
        settings.save(s, self.app.settings_path)
        self.app.settings = s
        self.load_from(s)
        self.app.set_theme(s.theme)

    def load_from(self, s):
        self.output_var.set(str(s.resolved_output_dir()))
        self.theme_var.set(s.theme)
        self.timeout_var.set(str(s.timeout))
        self.image_var.set(str(s.max_image_mb))
        self.embed_var.set(s.embed_images)
        self.folder_var.set(s.open_folder_after)

    def open_appdata(self):
        opener.open_path(paths.app_dir())
