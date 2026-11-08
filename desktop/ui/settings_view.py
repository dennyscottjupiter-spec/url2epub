# ---
# purpose: Settings page in sections: saving (incl. X cookies note), appearance, fetching; save/reset
# exports: SettingsView
# depends: core/settings.py, core/paths.py, core/opener.py, ui/dialogs.py, ui/widgets.py
# ---
import tkinter as tk
from tkinter import ttk

from core import opener, paths, settings
from ui import dialogs
from ui.widgets import Button, header


def _int(text, fallback):
    try:
        return int(text)
    except ValueError:
        return fallback


class SettingsView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.output_var = tk.StringVar()
        self.theme_var = tk.StringVar()
        self.timeout_var = tk.StringVar()
        self.image_var = tk.StringVar()
        self.embed_var = tk.BooleanVar()
        self.folder_var = tk.BooleanVar()
        header(self, "Settings", "Changes apply to the next conversion once you save them.")

        form = ttk.Frame(self)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        self._row = 0

        self._section(form, "Saving")
        self._label(form, "Save books to")
        folder = ttk.Frame(form)
        folder.grid(row=self._row, column=1, sticky="ew", pady=4)
        ttk.Entry(folder, textvariable=self.output_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.browse_btn = Button(folder, text="Browse…", command=self.browse)
        self.browse_btn.pack(side="left")
        self._next()
        self.folder_cb = ttk.Checkbutton(form, text="Show the book in its folder when done", variable=self.folder_var)
        self.folder_cb.grid(row=self._row, column=1, sticky="w", pady=2)
        self._next()
        ttk.Label(
            form, style="Small.TLabel", wraplength=560, justify="left",
            text="Some X (Twitter) Articles need a signed-in session. To convert those, put your x_cookies.txt "
                 "in this folder.",
        ).grid(row=self._row, column=1, sticky="w", pady=(2, 0))
        self._next()

        self._section(form, "Appearance")
        self._label(form, "Theme")
        themes = ttk.Frame(form)
        themes.grid(row=self._row, column=1, sticky="w", pady=4)
        self.dark_rb = ttk.Radiobutton(themes, text="Bookcloth (dark)", value="dark", variable=self.theme_var,
                                       command=self.pick_theme, style="Segment.Toolbutton")
        self.light_rb = ttk.Radiobutton(themes, text="E-ink paper (light)", value="light", variable=self.theme_var,
                                        command=self.pick_theme, style="Segment.Toolbutton")
        self.dark_rb.pack(side="left")
        self.light_rb.pack(side="left")
        self._next()

        self._section(form, "Fetching")
        self._label(form, "Page timeout")
        self._spin(form, self.timeout_var, 5, 120, "seconds")
        self._label(form, "Largest image")
        self._spin(form, self.image_var, 1, 50, "MB")
        self.embed_cb = ttk.Checkbutton(form, text="Include images in the book", variable=self.embed_var)
        self.embed_cb.grid(row=self._row, column=1, sticky="w", pady=2)
        self._next()

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=(22, 0))
        self.save_btn = Button(buttons, text="Save settings", command=self.save, variant="accent")
        self.reset_btn = Button(buttons, text="Restore defaults", command=self.reset)
        self.appdata_btn = Button(buttons, text="Open settings folder", command=self.open_appdata)
        for btn in (self.save_btn, self.reset_btn, self.appdata_btn):
            btn.pack(side="left", padx=(0, 6))
        self.load_from(app.settings)

    def _next(self):
        self._row += 1

    def _section(self, form, text):
        pad = (0, 4) if self._row == 0 else (16, 4)
        ttk.Label(form, text=text, style="Section.TLabel").grid(row=self._row, column=0, columnspan=2,
                                                                sticky="w", pady=pad)
        self._next()

    def _label(self, form, text):
        ttk.Label(form, text=text, style="Muted.TLabel").grid(row=self._row, column=0, sticky="w", padx=(0, 24))

    def _spin(self, form, var, low, high, unit):
        cell = ttk.Frame(form)
        cell.grid(row=self._row, column=1, sticky="w", pady=4)
        ttk.Spinbox(cell, from_=low, to=high, textvariable=var, width=6).pack(side="left")
        ttk.Label(cell, text=unit, style="Muted.TLabel").pack(side="left", padx=(8, 0))
        self._next()

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
