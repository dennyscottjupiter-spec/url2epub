# ---
# purpose: Every messagebox and file dialog in the app, in one module the tests can replace
# exports: ask_full_page(), error(), info(), confirm(), choose_folder(), save_as()
# ---
from tkinter import filedialog, messagebox


def ask_full_page(parent) -> bool:
    return messagebox.askyesno(
        "Very little text found",
        "This page gave almost no article text. It may need JavaScript or a login.\n\n"
        "Use the whole page instead? The book may include menus and other clutter.",
        parent=parent,
    )


def error(parent, title, message):
    messagebox.showerror(title, message, parent=parent)


def info(parent, title, message):
    messagebox.showinfo(title, message, parent=parent)


def confirm(parent, title, message) -> bool:
    return messagebox.askyesno(title, message, parent=parent)


def choose_folder(parent, initial) -> str:
    return filedialog.askdirectory(parent=parent, initialdir=initial or None) or ""


def save_as(parent, default_name, ext, filetypes) -> str:
    return filedialog.asksaveasfilename(
        parent=parent, initialfile=default_name, defaultextension=ext, filetypes=filetypes,
    ) or ""
