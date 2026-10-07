# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build for the PDF Page Merger.

Produces a folder containing two executables and a private copy of Python, so a
machine that receives it needs nothing installed:

    PDF Page Merger.exe   the window (no console)
    pdfmerge.exe          the command line

Built through packaging\\build.ps1 rather than directly, so that the signing and
installer steps happen in the right order:

    pyinstaller --clean --noconfirm packaging\\merge_tool.spec
"""

from pathlib import Path

PROJECT = Path(SPECPATH).resolve().parent      # SPECPATH comes from PyInstaller
ICON = str(PROJECT / "packaging" / "icon.ico")

APP_NAME = "PDF Page Merger"
VERSION = "1.0.0"

# Deliberately empty. Anything listed here is placed under _internal\ by
# PyInstaller 6, which is no use for documentation a user is meant to find --
# and worse for the input\ instructions, since when frozen BASE is the folder
# holding the .exe, so the folder the tool watches is <app>\input while the file
# explaining it would sit in _internal\input\. README.md, order.txt.example and
# the input\ instructions are therefore copied by installer.iss instead, straight
# to {app} and {app}\input. See PROJECT-NOTES.md, "Packaging".
DATA = []

# merge.py is reached through a runtime sys.path insert, which static analysis
# cannot see, so it is named explicitly. The Pillow pieces are imported lazily
# inside functions for the same reason.
HIDDEN = [
    "merge",
    "pypdf",
    "PIL.Image",
    "PIL.ImageOps",
    "PIL.ImageSequence",
]

# Nothing here uses these; leaving them out keeps the download a sensible size.
EXCLUDE = [
    "numpy", "pandas", "matplotlib", "scipy", "openpyxl", "docx", "pytest",
    "IPython", "notebook", "PyQt5", "PySide2", "setuptools", "pip",
]


def analyse(entry_point):
    return Analysis(
        [str(PROJECT / entry_point)],
        pathex=[str(PROJECT)],
        binaries=[],
        datas=DATA,
        hiddenimports=HIDDEN,
        hookspath=[],
        runtime_hooks=[],
        excludes=EXCLUDE,
        noarchive=False,
    )


gui_analysis = analyse("merge_gui.pyw")
cli_analysis = analyse("merge.py")

gui_pyz = PYZ(gui_analysis.pure, gui_analysis.zipped_data)
cli_pyz = PYZ(cli_analysis.pure, cli_analysis.zipped_data)

gui_exe = EXE(
    gui_pyz,
    gui_analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    strip=False,
    upx=False,                 # UPX-packed binaries get flagged by scanners
    console=False,             # windowed: no console flashing behind the GUI
    icon=ICON,
)

cli_exe = EXE(
    cli_pyz,
    cli_analysis.scripts,
    [],
    exclude_binaries=True,
    name="pdfmerge",
    debug=False,
    strip=False,
    upx=False,
    console=True,              # the command line needs its console
    icon=ICON,
)

COLLECT(
    gui_exe,
    gui_analysis.binaries,
    gui_analysis.datas,
    cli_exe,
    cli_analysis.binaries,
    cli_analysis.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
