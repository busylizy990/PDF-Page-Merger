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

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

PROJECT = Path(SPECPATH).resolve().parent      # SPECPATH comes from PyInstaller
ICON = str(PROJECT / "packaging" / "icon.ico")

APP_NAME = "PDF Page Merger"
VERSION = "1.0.0"

# Must match AppPublisher in installer.iss, and the subject on any code-signing
# certificate. TestTheTwoFilesAgree asserts the first of those; the second is
# checked by Windows when the signature is verified.
COMPANY = "Damreb Consultancy Ltd"
COPYRIGHT = f"Copyright (c) 2026 {COMPANY}. All rights reserved."


def version_resource(description: str, filename: str) -> VSVersionInfo:
    """The Windows version resource for one executable.

    Without this, Properties -> Details is blank on both programs: VERSION was
    declared here from the first build and never passed to EXE(). The installer
    looked fine because Inno Setup writes its own from AppPublisher and
    AppVersion, which is why the metadata note in PROJECT-NOTES was accurate --
    it was about Setup.exe, not about what Setup.exe installs.

    It matters beyond tidiness: a firm's IT will inventory software by
    FileVersion, and a blank one is a conversation nobody wants during
    procurement. Signing does not supply it -- a signed build with no version
    resource still shows nothing.
    """
    # Four parts, as the Win32 structure requires; the fourth is the build
    # number, which this project does not use.
    parts = tuple(int(n) for n in VERSION.split(".")) + (0,)
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=parts,
            prodvers=parts,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,      # VOS_NT_WINDOWS32
            fileType=0x1,    # VFT_APP
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            # 040904B0: US English, Unicode -- and the 1200 in VarStruct below
            # is the same code page in decimal. They have to agree or the
            # resource is ignored.
            StringFileInfo([
                StringTable("040904B0", [
                    StringStruct("CompanyName", COMPANY),
                    StringStruct("FileDescription", description),
                    StringStruct("FileVersion", VERSION),
                    StringStruct("InternalName", filename),
                    StringStruct("LegalCopyright", COPYRIGHT),
                    StringStruct("OriginalFilename", filename),
                    StringStruct("ProductName", APP_NAME),
                    StringStruct("ProductVersion", VERSION),
                ]),
            ]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )

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
    version=version_resource("PDF Page Merger", f"{APP_NAME}.exe"),
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
    version=version_resource("PDF Page Merger (command line)", "pdfmerge.exe"),
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
