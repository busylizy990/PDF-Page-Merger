#!/usr/bin/env python3
"""
PDF Page Merger -- window version
=================================

A front end for merge.py. It builds the same command line the terminal takes and
hands it to the same code, so there is one merging engine and no second set of
behaviour to keep in step.

Run it by double-clicking "Merge GUI.bat", or drop files onto that file to start
with them already listed.
"""

from __future__ import annotations

import io
import json
import os
import queue
import subprocess
import sys
import threading
import traceback
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

# Packaged into an .exe, __file__ points inside a temporary unpack folder, so the
# tool's own folder is where the executable lives instead.
BASE = Path(
    sys.executable if getattr(sys, "frozen", False) else __file__
).resolve().parent
sys.path.insert(0, str(BASE))

import merge  # noqa: E402  (needs BASE on the path first)

KIND_NAMES = {"pdf": "PDF", "image": "Image", "word": "Word", "excel": "Spreadsheet"}
IMAGE_PAGE_CHOICES = ("match", "letter", "a4", "legal", "exact")
SETTINGS_NAME = "settings.json"

# What a preset covers: how a bundle is finished, not which files go in it or
# where it is saved -- those change every job.
PRESET_FIELDS = (
    "index", "index_title", "stamp", "stamp_format", "stamp_at", "image_page",
)

# Starting points, written into settings.json the first time the window runs.
# After that they are ordinary presets: rename, change or delete them freely.
BUILT_IN_PRESETS = {
    "Court bundle": {
        "index": True, "index_title": "Index",
        "stamp": True, "stamp_format": "{n}", "stamp_at": "bottom-center",
        "image_page": "match",
    },
    "Bates numbered": {
        "index": False, "index_title": "Contents",
        "stamp": True, "stamp_format": "ABC-{n:05d}", "stamp_at": "bottom-right",
        "image_page": "match",
    },
    "Candidate pack": {
        "index": True, "index_title": "Contents",
        "stamp": True, "stamp_format": "Page {n} of {total}",
        "stamp_at": "bottom-right", "image_page": "match",
    },
    "Plain merge": {
        "index": False, "index_title": "Contents",
        "stamp": False, "stamp_format": "{n}", "stamp_at": "bottom-right",
        "image_page": "match",
    },
}


def clean_preset(values) -> dict | None:
    """Keep only the fields a preset may carry, and only sane values."""
    if not isinstance(values, dict):
        return None
    tidy: dict = {}
    for field in PRESET_FIELDS:
        value = values.get(field)
        if field in ("index", "stamp"):
            if isinstance(value, bool):
                tidy[field] = value
        elif field == "stamp_at":
            if value in merge.STAMP_SPOTS:
                tidy[field] = value
        elif field == "image_page":
            if value in IMAGE_PAGE_CHOICES:
                tidy[field] = value
        elif isinstance(value, str) and value:
            tidy[field] = value
    return tidy or None


# --------------------------------------------------------------------------- #
# Remembering how you like things set
# --------------------------------------------------------------------------- #

def settings_path() -> Path:
    """Beside the tool, so settings travel with the folder.

    Falls back to the user's own profile when the folder is not writable, which
    is what happens if this ever gets installed somewhere like Program Files.
    Writability is tested by writing -- see merge.can_write_dir -- because
    os.access ignores ACLs on Windows and left this fallback unreachable.
    """
    local = BASE / SETTINGS_NAME
    if local.exists() or merge.can_write_dir(BASE):
        return local
    try:
        folder = Path(os.environ.get("APPDATA") or Path.home()) / "PDF Page Merger"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / SETTINGS_NAME
    except OSError:
        return local


def load_settings() -> dict:
    """Whatever was saved last time. A missing or damaged file is simply ignored.

    Read as utf-8-sig, not utf-8: this file is hand-editable, and a byte-order
    mark -- which Notepad can add and which Windows PowerShell's
    `Out-File -Encoding utf8` always adds -- would otherwise make json.loads
    raise and silently discard every saved preference. order.txt and the Office
    result file are read the same way.
    """
    try:
        loaded = json.loads(settings_path().read_text(encoding="utf-8-sig"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(values: dict) -> bool:
    try:
        settings_path().write_text(
            json.dumps(values, indent=2) + "\n", encoding="utf-8"
        )
        return True
    except OSError:
        return False  # never let a read-only folder get in the way of merging


# --------------------------------------------------------------------------- #
# Dropping files onto the window
# --------------------------------------------------------------------------- #

def enable_file_drop(window: tk.Misc, on_drop) -> bool:
    """Let Windows drop files onto this window. True if it took.

    Done through the shell's own WM_DROPFILES message rather than a drag-and-drop
    add-on, so there is nothing extra to install -- which also means anyone given
    a copy of this folder gets working drag and drop straight away.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)

        WM_DROPFILES = 0x0233
        GWLP_WNDPROC = -4
        LRESULT = ctypes.c_ssize_t
        LONG_PTR = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )

        setter = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
        setter.restype = LONG_PTR
        setter.argtypes = [wintypes.HWND, ctypes.c_int, WNDPROC]
        user32.CallWindowProcW.restype = LRESULT
        user32.CallWindowProcW.argtypes = [
            LONG_PTR, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragQueryFileW.argtypes = [
            wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT
        ]
        # Declared explicitly: ctypes assumes a 32-bit int return otherwise, which
        # silently truncates handles on 64-bit Windows.
        user32.GetParent.restype = wintypes.HWND
        user32.GetParent.argtypes = [wintypes.HWND]
        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        shell32.DragFinish.argtypes = [wintypes.HANDLE]

        # winfo_id gives Tk's own frame; the window with the title bar is its parent.
        hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()

        def handler(hwnd_in, message, wparam, lparam):
            if message == WM_DROPFILES:
                dropped = ctypes.c_void_p(wparam)
                names = []
                try:
                    count = shell32.DragQueryFileW(dropped, 0xFFFFFFFF, None, 0)
                    for index in range(count):
                        size = shell32.DragQueryFileW(dropped, index, None, 0)
                        buffer = ctypes.create_unicode_buffer(size + 1)
                        shell32.DragQueryFileW(dropped, index, buffer, size + 1)
                        names.append(buffer.value)
                finally:
                    shell32.DragFinish(dropped)
                # Hand back to Tk rather than doing the work inside the window
                # procedure, which must return promptly.
                window.after(0, lambda: on_drop([Path(n) for n in names]))
                return 0
            return user32.CallWindowProcW(
                previous, hwnd_in, message, wparam, lparam
            )

        callback = WNDPROC(handler)
        previous = setter(hwnd, GWLP_WNDPROC, callback)
        if not previous:
            return False
        shell32.DragAcceptFiles(hwnd, True)

        # Both must outlive the window or the process walks into freed memory.
        window._drop_callback = callback        # type: ignore[attr-defined]
        window._drop_previous = previous        # type: ignore[attr-defined]
        return True
    except Exception:
        return False


def kind_of(path: Path) -> str:
    if merge.is_image(path):
        return "image"
    if merge.is_word(path):
        return "word"
    if merge.is_excel(path):
        return "excel"
    return "pdf"


def file_dialog_types() -> list[tuple[str, str]]:
    """Filters for the Add files dialog, taken from what merge.py supports."""
    every = " ".join(f"*{e}" for e in sorted(merge.SOURCE_EXTS))
    images = " ".join(f"*{e}" for e in sorted(merge.IMAGE_EXTS))
    office = " ".join(f"*{e}" for e in sorted(merge.OFFICE_EXTS))
    return [
        ("Everything it can merge", every),
        ("PDF files", "*.pdf"),
        ("Images", images),
        ("Word and Excel files", office),
        ("All files", "*.*"),
    ]


class Row:
    """One source in the list: a file plus an optional page spec."""

    def __init__(self, path: Path, spec: str = "") -> None:
        self.path = path
        self.spec = spec

    def token(self) -> str:
        """How merge.py wants it on the command line."""
        return f"{self.path}:{self.spec}" if self.spec.strip() else str(self.path)


class MergerWindow(ttk.Frame):
    def __init__(self, master: tk.Tk, initial: list[Path] | None = None) -> None:
        super().__init__(master, padding=10)
        self.master = master
        self.rows: list[Row] = []
        self.messages: queue.Queue[str] = queue.Queue()
        self.busy = False
        self.last_output: Path | None = None
        self.written_here: set[str] = set()  # outputs this session already owns
        self._drain_job: str | None = None
        # Passwords for encrypted PDFs, for this session only. Never saved to
        # settings.json, never logged, never put in the command line.
        self.passwords: list[str] = []

        master.title("PDF Page Merger")
        master.minsize(760, 620)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._build_sources()
        self._build_options()
        self._build_actions()
        self._build_log()

        self.settings = load_settings()
        self.apply_settings()
        master.protocol("WM_DELETE_WINDOW", self.close)
        # Belt and braces: whatever tears the window down, stop the log poller,
        # or Tk keeps firing it at a widget that no longer exists.
        master.bind("<Destroy>", self._stop_draining, add="+")

        self.drop_works = False
        # Deferred: Tk has not created the real top-level window yet during
        # __init__, and the drop has to be registered against that, not the
        # child frame that exists this early.
        self.after(0, self._enable_drop)

        for path in initial or []:
            self.add_path(path)
        self._refresh()
        self._drain_job = self.after(100, self._drain)

    def _enable_drop(self) -> None:
        self.master.update_idletasks()
        self.drop_works = enable_file_drop(self.master, self.files_dropped)
        if self.drop_works:
            self.drop_hint.configure(text="Drag files straight onto this window.")

    # ------------------------------------------------------------------ #
    # Settings
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # Presets
    # ------------------------------------------------------------------ #

    def current_finishing(self) -> dict:
        return {
            "index": self.index_on.get(),
            "index_title": self.index_title.get(),
            "stamp": self.stamp_on.get(),
            "stamp_format": self.stamp_format.get(),
            "stamp_at": self.stamp_at.get(),
            "image_page": self.image_page.get(),
        }

    def _option_changed(self, *_args) -> None:
        """A hand edit means the named preset no longer describes the settings."""
        if not self._applying_preset and self.preset_name.get():
            self.preset_name.set("")
            self.preset_delete.configure(state="disabled")

    def _reload_preset_menu(self) -> None:
        self.preset_menu.configure(values=sorted(self.presets))
        chosen = self.preset_name.get()
        self.preset_delete.configure(
            state="normal" if chosen and chosen in self.presets else "disabled"
        )

    def _preset_chosen(self, _event=None) -> None:
        self.apply_preset(self.preset_name.get())

    def apply_preset(self, name: str) -> None:
        values = self.presets.get(name)
        if not values:
            return
        self._applying_preset = True
        try:
            if "index" in values:
                self.index_on.set(values["index"])
            if "index_title" in values:
                self.index_title.set(values["index_title"])
            if "stamp" in values:
                self.stamp_on.set(values["stamp"])
            if "stamp_format" in values:
                self.stamp_format.set(values["stamp_format"])
            if "stamp_at" in values:
                self.stamp_at.set(values["stamp_at"])
            if "image_page" in values:
                self.image_page.set(values["image_page"])
            self.preset_name.set(name)
        finally:
            self._applying_preset = False
        self._reload_preset_menu()
        self._refresh()
        self.status.set(f"Preset '{name}' applied.")

    def save_preset(self) -> None:
        suggested = self.preset_name.get() or ""
        name = simpledialog.askstring(
            "Save preset",
            "Name this set of finishing options:",
            initialvalue=suggested,
            parent=self,
        )
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showerror("Save preset", "It needs a name.", parent=self)
            return
        if name in self.presets and not messagebox.askyesno(
            "Replace preset?", f"'{name}' already exists. Replace it?", parent=self
        ):
            return
        self.presets[name] = self.current_finishing()
        self._applying_preset = True
        self.preset_name.set(name)
        self._applying_preset = False
        self._reload_preset_menu()
        self.remember()
        self.status.set(f"Preset '{name}' saved.")

    def delete_preset(self) -> None:
        name = self.preset_name.get()
        if name not in self.presets:
            return
        if not messagebox.askyesno(
            "Delete preset?", f"Delete the preset '{name}'?", parent=self
        ):
            return
        del self.presets[name]
        self._applying_preset = True
        self.preset_name.set("")
        self._applying_preset = False
        self._reload_preset_menu()
        self.remember()
        self.status.set(f"Preset '{name}' deleted.")

    def apply_settings(self) -> None:
        """Restore the saved choices, ignoring anything that looks wrong."""
        saved = self.settings

        def restore_flag(key: str, variable: tk.BooleanVar) -> None:
            if isinstance(saved.get(key), bool):
                variable.set(saved[key])

        def restore_text(key: str, variable: tk.StringVar, allowed=None) -> None:
            value = saved.get(key)
            if isinstance(value, str) and value and (allowed is None or value in allowed):
                variable.set(value)

        # Presets first: a saved set is seeded on the very first run, and the
        # individual settings below then override whatever was last in use.
        self.presets = {}
        stored = saved.get("presets")
        if not isinstance(stored, dict) or not stored:
            stored = BUILT_IN_PRESETS
        for name, values in stored.items():
            tidy = clean_preset(values)
            if isinstance(name, str) and name.strip() and tidy:
                self.presets[name.strip()] = tidy
        if not self.presets:
            self.presets = {n: dict(v) for n, v in BUILT_IN_PRESETS.items()}

        self._applying_preset = True
        restore_flag("index", self.index_on)
        restore_text("index_title", self.index_title)
        restore_flag("stamp", self.stamp_on)
        restore_text("stamp_format", self.stamp_format)
        restore_text("stamp_at", self.stamp_at, merge.STAMP_SPOTS)
        restore_text("image_page", self.image_page, IMAGE_PAGE_CHOICES)
        restore_text("out_path", self.out_path)

        # Only claim a preset is in force if the settings still match it.
        last = saved.get("last_preset")
        if isinstance(last, str) and self.presets.get(last) == self.current_finishing():
            self.preset_name.set(last)
        self._applying_preset = False
        self._reload_preset_menu()

        # Size only, never position: a remembered position can land the window on
        # a monitor that is no longer there.
        size = saved.get("window_size")
        if isinstance(size, list) and len(size) == 2:
            try:
                width, height = int(size[0]), int(size[1])
                if width >= 700 and height >= 560:
                    self.master.geometry(f"{width}x{height}")
            except (TypeError, ValueError):
                pass

    def collect_settings(self) -> dict:
        return {
            "index": self.index_on.get(),
            "index_title": self.index_title.get(),
            "stamp": self.stamp_on.get(),
            "stamp_format": self.stamp_format.get(),
            "stamp_at": self.stamp_at.get(),
            "image_page": self.image_page.get(),
            "out_path": self.out_path.get(),
            "window_size": [self.master.winfo_width(), self.master.winfo_height()],
            "presets": self.presets,
            "last_preset": self.preset_name.get(),
        }

    def remember(self) -> None:
        self.settings = self.collect_settings()
        save_settings(self.settings)

    def _stop_draining(self, event=None) -> None:
        if event is not None and event.widget is not self.master:
            return  # a child widget going away, not the window
        if self._drain_job is not None:
            try:
                self.after_cancel(self._drain_job)
            except tk.TclError:
                pass
            self._drain_job = None

    def close(self) -> None:
        self.remember()
        self._stop_draining()
        self.master.destroy()

    def files_dropped(self, paths: list[Path]) -> None:
        """Files were dragged onto the window."""
        added = ignored = 0
        for path in paths:
            gained, skipped = self.add_path(path)
            added += gained
            ignored += skipped
        self._refresh()
        self.status.set(self._added_message(added, ignored))

    @staticmethod
    def _added_message(added: int, ignored: int) -> str:
        if not added and not ignored:
            return "Nothing there it can merge."
        parts = []
        if added:
            parts.append(f"Added {added} document{'' if added == 1 else 's'}")
        if ignored:
            parts.append(
                f"ignored {ignored} file{'' if ignored == 1 else 's'} it cannot merge"
            )
        message = ", ".join(parts) + "."
        return message[0].upper() + message[1:]

    # ------------------------------------------------------------------ #
    # Layout
    # ------------------------------------------------------------------ #

    def _build_sources(self) -> None:
        box = ttk.LabelFrame(self, text="Documents to merge, in order", padding=8)
        box.grid(row=0, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        bar = ttk.Frame(box)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(bar, text="Add files...", command=self.pick_files).pack(side="left")
        ttk.Button(bar, text="Add folder...", command=self.pick_folder).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(bar, text="Remove", command=self.remove_selected).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(bar, text="Clear", command=self.clear_all).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Move up", command=lambda: self.nudge(-1)).pack(
            side="right"
        )
        ttk.Button(bar, text="Move down", command=lambda: self.nudge(1)).pack(
            side="right", padx=(0, 6)
        )
        self.drop_hint = ttk.Label(bar, text="", foreground="#666666")
        self.drop_hint.pack(side="left", padx=(12, 0))

        columns = ("name", "kind", "pages", "where")
        self.tree = ttk.Treeview(box, columns=columns, show="headings", height=9)
        for key, title, width, anchor in (
            ("name", "File", 300, "w"),
            ("kind", "Type", 90, "w"),
            ("pages", "Pages", 110, "w"),
            ("where", "Folder", 240, "w"),
        ):
            self.tree.heading(key, text=title, anchor=anchor)
            self.tree.column(key, width=width, anchor=anchor)
        self.tree.grid(row=1, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)

        scroll = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)

        picker = ttk.Frame(box)
        picker.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(picker, text="Pages to merge from the selected file:").pack(side="left")
        self.spec_var = tk.StringVar()
        self.spec_entry = ttk.Entry(picker, textvariable=self.spec_var, width=22)
        self.spec_entry.pack(side="left", padx=(6, 6))
        self.spec_entry.bind("<Return>", lambda _e: self.apply_spec())
        ttk.Button(picker, text="Apply", command=self.apply_spec).pack(side="left")

        # The hint sits on its own line rather than after the Apply button. On one
        # line the row needs 884px, and the window's minimum is 760 -- so the end
        # of the hint was clipped, losing the "!4" example, which is the least
        # guessable of the three.
        ttk.Label(
            box,
            text="Blank = All Pages      Custom Pages e.g. 1-3,7 = Pages 1-3 & 7"
                 "      7- = Page 7 to the end      !4 = All pages except page 4",
            foreground="#666666",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def _build_options(self) -> None:
        box = ttk.LabelFrame(self, text="Finishing", padding=8)
        box.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        box.columnconfigure(5, weight=1)

        ttk.Label(box, text="Preset:").grid(row=0, column=0, sticky="w")
        self.preset_name = tk.StringVar()
        self.preset_menu = ttk.Combobox(
            box, textvariable=self.preset_name, state="readonly", width=24
        )
        self.preset_menu.grid(row=0, column=1, columnspan=2, sticky="w", padx=(12, 6))
        self.preset_menu.bind("<<ComboboxSelected>>", self._preset_chosen)
        ttk.Button(box, text="Save as...", command=self.save_preset).grid(
            row=0, column=3, sticky="w"
        )
        self.preset_delete = ttk.Button(
            box, text="Delete", command=self.delete_preset, state="disabled"
        )
        self.preset_delete.grid(row=0, column=4, sticky="w", padx=(6, 0))

        ttk.Separator(box, orient="horizontal").grid(
            row=1, column=0, columnspan=6, sticky="ew", pady=8
        )

        self.index_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            box, text="Contents page", variable=self.index_on, command=self._refresh
        ).grid(row=2, column=0, sticky="w")
        ttk.Label(box, text="Heading:").grid(row=2, column=1, sticky="e", padx=(12, 4))
        self.index_title = tk.StringVar(value="Contents")
        self.index_entry = ttk.Entry(box, textvariable=self.index_title, width=24)
        self.index_entry.grid(row=2, column=2, sticky="w", columnspan=2)

        self.stamp_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            box, text="Number the pages", variable=self.stamp_on, command=self._refresh
        ).grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Label(box, text="Format:").grid(row=3, column=1, sticky="e", padx=(12, 4),
                                            pady=(6, 0))
        self.stamp_format = tk.StringVar(value="{n}")
        self.stamp_entry = ttk.Entry(box, textvariable=self.stamp_format, width=24)
        self.stamp_entry.grid(row=3, column=2, sticky="w", pady=(6, 0))
        ttk.Label(box, text="Position:").grid(row=3, column=3, sticky="e", padx=(12, 4),
                                              pady=(6, 0))
        self.stamp_at = tk.StringVar(value="bottom-right")
        self.stamp_menu = ttk.Combobox(
            box, textvariable=self.stamp_at, values=list(merge.STAMP_SPOTS),
            state="readonly", width=15,
        )
        self.stamp_menu.grid(row=3, column=4, sticky="w", pady=(6, 0))
        ttk.Label(
            box,
            text="{n} is the page number, {total} the count.  DF-{n:04d} gives DF-0001.",
            foreground="#666666",
        ).grid(row=4, column=0, columnspan=6, sticky="w", pady=(6, 0))

        ttk.Separator(box, orient="horizontal").grid(
            row=5, column=0, columnspan=6, sticky="ew", pady=8
        )

        ttk.Label(box, text="Image page size:").grid(row=6, column=0, sticky="w")
        self.image_page = tk.StringVar(value="match")
        ttk.Combobox(
            box, textvariable=self.image_page, values=list(IMAGE_PAGE_CHOICES),
            state="readonly", width=12,
        ).grid(row=6, column=1, columnspan=2, sticky="w", padx=(12, 0))
        ttk.Label(
            box, text="match = same size as the PDF pages", foreground="#666666"
        ).grid(row=6, column=3, columnspan=3, sticky="w", padx=(12, 0))

        ttk.Label(box, text="Save as:").grid(row=7, column=0, sticky="w", pady=(8, 0))
        self.out_path = tk.StringVar(value=str(merge.writable_output_dir() / "merged.pdf"))
        ttk.Entry(box, textvariable=self.out_path).grid(
            row=7, column=1, columnspan=4, sticky="ew", padx=(12, 6), pady=(8, 0)
        )
        ttk.Button(box, text="Browse...", command=self.pick_output).grid(
            row=7, column=5, sticky="e", pady=(8, 0)
        )

        # Touching any of these by hand means you are no longer on the preset.
        self._applying_preset = False
        for variable in (self.index_on, self.index_title, self.stamp_on,
                         self.stamp_format, self.stamp_at, self.image_page):
            variable.trace_add("write", self._option_changed)

    def _build_actions(self) -> None:
        bar = ttk.Frame(self)
        bar.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        bar.columnconfigure(1, weight=1)

        self.merge_button = ttk.Button(bar, text="Merge", command=self.start_merge)
        self.merge_button.grid(row=0, column=0)
        self.password_button = ttk.Button(
            bar, text="Password...", command=self.ask_password
        )
        self.password_button.grid(row=0, column=4, padx=(6, 0))
        self.status = tk.StringVar(value="Add some documents to begin.")
        ttk.Label(bar, textvariable=self.status).grid(row=0, column=1, sticky="w",
                                                     padx=(10, 0))
        self.open_button = ttk.Button(
            bar, text="Open result", command=self.open_result, state="disabled"
        )
        self.open_button.grid(row=0, column=2)
        self.folder_button = ttk.Button(
            bar, text="Open folder", command=self.open_folder, state="disabled"
        )
        self.folder_button.grid(row=0, column=3, padx=(6, 0))

    # ------------------------------------------------------------------ #
    # Passwords for encrypted PDFs
    # ------------------------------------------------------------------ #

    def ask_password(self) -> None:
        """Collect a password for this session only.

        Held in memory on the window and never written anywhere: not into
        settings.json, not into the log, and not into the command line the log
        echoes. Several can be added for a bundle where files differ; each is
        tried in turn, after the empty password.
        """
        top = tk.Toplevel(self)
        top.title("Password")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        frame = ttk.Frame(top, padding=12)
        frame.grid(sticky="nsew")

        ttk.Label(
            frame,
            text=(
                "Password for an encrypted PDF.\n\n"
                "Kept in memory for this session only -- it is not saved and does\n"
                "not appear in the log. Add more than one if files differ."
            ),
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        entry = ttk.Entry(frame, show="\u2022", width=32)
        entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        entry.focus_set()

        def keep(_event=None) -> None:
            value = entry.get()
            if value and value not in self.passwords:
                self.passwords.append(value)
            entry.delete(0, "end")
            self._refresh_password_button()
            top.destroy()

        ttk.Button(frame, text="Add", command=keep).grid(row=2, column=0, sticky="w")
        ttk.Button(frame, text="Cancel", command=top.destroy).grid(
            row=2, column=1, sticky="e"
        )
        if self.passwords:
            ttk.Button(frame, text="Forget all", command=lambda: self.forget_passwords(top)).grid(
                row=3, column=0, columnspan=2, sticky="w", pady=(8, 0)
            )

        entry.bind("<Return>", keep)
        top.bind("<Escape>", lambda _e: top.destroy())
        top.grab_set()

    def forget_passwords(self, window=None) -> None:
        self.passwords.clear()
        self._refresh_password_button()
        if window is not None:
            window.destroy()

    def _refresh_password_button(self) -> None:
        """Show how many are held, never what they are."""
        count = len(self.passwords)
        self.password_button.configure(
            text="Password..." if not count else f"Password ({count})"
        )

    def _build_log(self) -> None:
        box = ttk.LabelFrame(self, text="What happened", padding=6)
        box.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        self.log = tk.Text(box, height=9, wrap="none", state="disabled",
                           font=("Consolas", 9))
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

    # ------------------------------------------------------------------ #
    # The list
    # ------------------------------------------------------------------ #

    def add_path(self, path: Path) -> tuple[int, int]:
        """Add a file, or every usable file in a folder. Returns (added, ignored)."""
        if path.is_dir():
            usable = sorted(
                (p for p in path.iterdir()
                 if p.is_file() and p.suffix.lower() in merge.SOURCE_EXTS),
                key=merge.natural_key,
            )
            self.rows.extend(Row(p) for p in usable)
            return len(usable), 0
        if path.is_file():
            # Checked here rather than at merge time: better to refuse a stray
            # file as it arrives than to fail halfway through a merge.
            if path.suffix.lower() not in merge.SOURCE_EXTS:
                return 0, 1
            self.rows.append(Row(path))
            return 1, 0
        return 0, 0

    def pick_files(self) -> None:
        chosen = filedialog.askopenfilenames(
            title="Add documents", filetypes=file_dialog_types()
        )
        if not chosen:
            return
        added = ignored = 0
        for name in chosen:
            gained, skipped = self.add_path(Path(name))
            added += gained
            ignored += skipped
        self._refresh()
        self.status.set(self._added_message(added, ignored))

    def pick_folder(self) -> None:
        folder = filedialog.askdirectory(title="Add every document in a folder")
        if not folder:
            return
        added, ignored = self.add_path(Path(folder))
        self._refresh()
        self.status.set(self._added_message(added, ignored))

    def pick_output(self) -> None:
        name = filedialog.asksaveasfilename(
            title="Save the merged PDF as",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile=Path(self.out_path.get()).name,
            initialdir=str(Path(self.out_path.get()).parent),
        )
        if name:
            self.out_path.set(name)

    def _selected_indexes(self) -> list[int]:
        return sorted(int(item) for item in self.tree.selection())

    def remove_selected(self) -> None:
        for index in reversed(self._selected_indexes()):
            del self.rows[index]
        self._refresh()

    def clear_all(self) -> None:
        self.rows.clear()
        self._refresh()

    def nudge(self, step: int) -> None:
        picked = self._selected_indexes()
        if not picked:
            return
        order = picked if step < 0 else list(reversed(picked))
        moved = []
        for index in order:
            target = index + step
            if 0 <= target < len(self.rows):
                self.rows[index], self.rows[target] = self.rows[target], self.rows[index]
                moved.append(target)
            else:
                moved.append(index)
        self._refresh(select=moved)

    def _selection_changed(self, _event=None) -> None:
        picked = self._selected_indexes()
        if len(picked) == 1:
            self.spec_var.set(self.rows[picked[0]].spec)

    def apply_spec(self) -> None:
        picked = self._selected_indexes()
        if not picked:
            messagebox.showinfo(
                "Nothing selected", "Pick a file in the list first.", parent=self
            )
            return
        spec = self.spec_var.get().strip()
        if spec and not merge.RANGE_RE.match(spec):
            messagebox.showerror(
                "Not a page range",
                # Same wording as the hint under the field, one per line: a
                # dialog has the vertical room the hint does not, and somebody
                # reading this has already got it wrong once.
                f"{spec!r} is not a page range.\n\n"
                "Blank = All Pages\n"
                "1 = Page 1\n"
                "2-5 = Pages 2 to 5\n"
                "1-3,7 = Pages 1-3 & 7\n"
                "7- = Page 7 to the end\n"
                "!4 = All pages except page 4",
                parent=self,
            )
            return
        for index in picked:
            self.rows[index].spec = spec
        self._refresh(select=picked)

    def _refresh(self, select: list[int] | None = None) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.rows):
            self.tree.insert(
                "", "end", iid=str(index),
                values=(
                    row.path.name,
                    KIND_NAMES[kind_of(row.path)],
                    row.spec or "all",
                    str(row.path.parent),
                ),
            )
        if select:
            keep = [str(i) for i in select if 0 <= i < len(self.rows)]
            if keep:
                self.tree.selection_set(keep)

        self.index_entry.configure(state="normal" if self.index_on.get() else "disabled")
        for widget in (self.stamp_entry, self.stamp_menu):
            widget.configure(state="normal" if self.stamp_on.get() else "disabled")
        self.stamp_menu.configure(
            state="readonly" if self.stamp_on.get() else "disabled"
        )
        self.merge_button.configure(
            state="normal" if self.rows and not self.busy else "disabled"
        )
        if not self.busy:
            count = len(self.rows)
            self.status.set(
                "Add some documents to begin."
                if not count
                else f"{count} document{'' if count == 1 else 's'} ready."
            )

    # ------------------------------------------------------------------ #
    # Running the merge
    # ------------------------------------------------------------------ #

    def build_argv(self) -> list[str]:
        """The exact command line this window stands for."""
        argv = [row.token() for row in self.rows]
        argv += ["--out", self.out_path.get(), "--force"]
        argv += ["--image-page", self.image_page.get()]
        if self.index_on.get():
            argv += ["--index", "--index-title", self.index_title.get()]
        if self.stamp_on.get():
            argv += ["--stamp", self.stamp_format.get(),
                     "--stamp-at", self.stamp_at.get()]
        return argv

    def start_merge(self) -> None:
        if self.busy or not self.rows:
            return

        # The merge always overwrites, so ask before replacing a file this
        # session did not create. Once it is ours, stop asking.
        produced = Path(self.out_path.get())
        if produced.exists() and str(produced) not in self.written_here:
            replace = messagebox.askyesno(
                "Replace that file?",
                f"{produced.name} already exists in\n{produced.parent}\n\nReplace it?",
                parent=self,
            )
            if not replace:
                return

        argv = self.build_argv()
        self.busy = True
        self.last_output = None
        self.open_button.configure(state="disabled")
        self.folder_button.configure(state="disabled")
        self.merge_button.configure(state="disabled")
        self.status.set("Merging...")
        self._write_log(f"> python merge.py {' '.join(argv)}\n", clear=True)
        if self.passwords:
            # Say that one is in use, never which. The line above is the real
            # command and deliberately does not contain it.
            self._write_log(
                f"  ({len(self.passwords)} password(s) supplied, not shown)\n"
            )
        threading.Thread(
            target=self._worker, args=(argv, tuple(self.passwords)), daemon=True
        ).start()

    def _worker(self, argv: list[str], passwords: tuple = ()) -> None:
        """Runs merge.py's own main() and captures whatever it prints."""
        buffer = io.StringIO()
        code = 1
        try:
            with redirect_stdout(buffer), redirect_stderr(buffer):
                code = merge.main(argv, passwords=passwords)
        except SystemExit as exit_code:          # argparse rejecting something
            code = int(getattr(exit_code, "code", 1) or 0)
        except Exception:
            buffer.write("\n" + traceback.format_exc())
        self.messages.put(buffer.getvalue())
        self.messages.put(f"\0done:{code}")

    def _drain(self) -> None:
        """Move anything the worker printed into the log, on the UI thread."""
        try:
            while True:
                chunk = self.messages.get_nowait()
                if chunk.startswith("\0done:"):
                    self._finished(int(chunk.split(":", 1)[1]))
                else:
                    self._write_log(chunk)
        except queue.Empty:
            pass
        self._drain_job = self.after(120, self._drain)

    def _finished(self, code: int) -> None:
        self.busy = False
        self._refresh()  # re-enables the buttons, and resets the status line...
        produced = Path(self.out_path.get())
        # ...so the outcome is reported after it, not before.
        if code in (0, 2) and produced.exists():
            self.last_output = produced
            self.written_here.add(str(produced))
            self.status.set(
                f"Done -- {produced.name}"
                if code == 0
                else "Merged, but some files were skipped -- see below."
            )
            self.open_button.configure(state="normal")
            self.folder_button.configure(state="normal")
            # Saved now as well as on closing, so a good run is never lost.
            self.remember()
        else:
            self.status.set("Nothing was written -- see below.")

    def _write_log(self, text: str, clear: bool = False) -> None:
        if not text:
            return
        self.log.configure(state="normal")
        if clear:
            self.log.delete("1.0", "end")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _reveal(self, target: Path) -> None:
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(target)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as exc:
            messagebox.showerror("Could not open", str(exc), parent=self)

    def open_result(self) -> None:
        if self.last_output:
            self._reveal(self.last_output)

    def open_folder(self) -> None:
        if self.last_output:
            self._reveal(self.last_output.parent)


def main() -> None:
    dropped = [Path(a) for a in sys.argv[1:] if Path(a).exists()]
    root = tk.Tk()
    try:
        root.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
    except tk.TclError:
        pass
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    MergerWindow(root, dropped)
    root.mainloop()


if __name__ == "__main__":
    main()
