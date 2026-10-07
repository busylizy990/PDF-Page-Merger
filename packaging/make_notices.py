#!/usr/bin/env python
"""Assemble THIRD-PARTY-NOTICES.txt from the licence texts actually installed.

The installer distributes a private copy of Python together with pypdf, Pillow
and Tcl/Tk, plus PyInstaller's bootloader inside each .exe. BSD-3, MIT-CMU, the
Tcl/Tk terms and the PSF licence all require their copyright notice and licence
text to travel with a binary distribution, so the file this produces is shipped
beside the programs by installer.iss.

Texts are read from the build interpreter rather than typed out, so they are
exactly what is being shipped. Re-run this whenever a dependency changes:

    .python\\python.exe packaging\\make_notices.py

Deliberately not included: setuptools, pip, altgraph, pefile, packaging and
pywin32-ctypes. Those are build-time only -- the spec excludes setuptools and
pip, and nothing imports the rest -- so they are not distributed and need no
notice. Verify with: findstr /s /i /m "altgraph" "dist\\PDF Page Merger\\*"
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
PY = PROJECT / ".python"
SITE = PY / "Lib" / "site-packages"
OUT = PROJECT / "THIRD-PARTY-NOTICES.txt"

HEADER = """\
THIRD PARTY NOTICES
PDF Page Merger
===============================================================================

This program is distributed with the components listed below. Each is used under
the licence reproduced here, and each licence requires that its text and
copyright notice accompany the software. Nothing in this file restricts your
licence to PDF Page Merger itself, which is granted separately.

The merger reads and writes PDF files only through pypdf and images only through
Pillow. It never uploads anything and never transmits document contents.

Word documents and spreadsheets are converted by whichever of Microsoft Office or
LibreOffice is installed on your own machine. Neither is distributed with this
program, and neither is covered by this file -- they remain under your own
licences.

Contents:
"""

# (display name, version, what it does, licence name, licence text path(s))
#
# MAINTAINED BY HAND, and nothing detects an omission: add an entry whenever a
# dependency starts being bundled. The test suite checks that every top-level
# package in a built dist\ has an entry here, which is the closest thing to a
# guard -- run the tests after changing requirements-build.txt.
COMPONENTS = [
    (
        "Python",
        "%d.%d.%d" % sys.version_info[:3],
        "the language runtime and standard library, bundled so the program needs "
        "no separate Python installation",
        "Python Software Foundation License Version 2",
        PY / "LICENSE.txt",
    ),
    (
        "pypdf",
        None,
        "reads and writes the PDF files; every page in a merged document is "
        "copied by it",
        "BSD 3-Clause",
        SITE / "pypdf-*.dist-info" / "licenses" / "LICENSE",
    ),
    (
        "Pillow",
        None,
        "decodes images so they can be placed on PDF pages. Its licence text "
        "also covers the image libraries Pillow itself bundles, such as libjpeg, "
        "libtiff, libwebp and zlib, which are shipped inside it",
        "MIT-CMU (HPND)",
        SITE / "pillow-*.dist-info" / "licenses" / "LICENSE",
    ),
    (
        "cryptography",
        None,
        "decrypts AES-encrypted PDFs. pypdf treats it as optional and cannot open "
        "an encrypted file without it -- including the common case of a document "
        "secured against editing but needing no password to read",
        "Apache License 2.0 OR BSD 3-Clause, at your option",
        (
            SITE / "cryptography-*.dist-info" / "licenses" / "LICENSE",
            SITE / "cryptography-*.dist-info" / "licenses" / "LICENSE.APACHE",
            SITE / "cryptography-*.dist-info" / "licenses" / "LICENSE.BSD",
        ),
    ),
    (
        "cffi",
        None,
        "the foreign-function interface cryptography builds on. Its compiled "
        "_cffi_backend is shipped; pycparser, which cffi needs only to generate "
        "bindings, is not",
        "MIT",
        SITE / "cffi-*.dist-info" / "licenses" / "LICENSE",
    ),
    (
        "OpenSSL",
        "3.0.19",
        "the TLS and cryptography library, shipped as libcrypto-3.dll and "
        "libssl-3.dll. It comes with the bundled Python, which uses it for its "
        "ssl and hashlib modules, and CPython's own licence file does not cover "
        "it -- so without this entry 5.8 MB of Apache-2.0 code would be "
        "distributed with no licence text. The version is the one the shipped "
        "DLLs report",
        "Apache License 2.0",
        (
            HERE / "licenses" / "OpenSSL-NOTICE.txt",
            HERE / "licenses" / "Apache-2.0.txt",
        ),
    ),
    (
        "Tcl/Tk",
        None,
        "draws the window. Shipped with the graphical version only, though both "
        "programs live in the same folder",
        "Tcl/Tk licence (BSD style)",
        PY / "tcl" / "tk8.6" / "license.terms",
    ),
    (
        "PyInstaller bootloader",
        None,
        "the small launcher embedded at the start of each .exe that unpacks and "
        "starts the program. PyInstaller is licensed GPL 2.0 WITH an exception "
        "that expressly permits distributing bundled applications under terms of "
        "your own choosing; that exception is reproduced with the licence below, "
        "and it is why this program is not itself GPL",
        "GPL 2.0 with the PyInstaller bootloader exception",
        SITE / "pyinstaller-*.dist-info" / "licenses" / "COPYING.txt",
    ),
]


def resolve(pattern: Path) -> Path:
    """Allow one '*' segment, so versions do not have to be hard-coded."""
    if "*" not in str(pattern):
        if not pattern.is_file():
            raise SystemExit(f"licence text not found: {pattern}")
        return pattern
    parts = pattern.relative_to(SITE).parts
    matches = sorted(SITE.glob(parts[0]))
    if not matches:
        raise SystemExit(f"no package directory matching {parts[0]}")
    found = matches[-1].joinpath(*parts[1:])
    if not found.is_file():
        raise SystemExit(f"licence text not found: {found}")
    return found


def version_of(path: Path) -> str:
    """Pull the version out of a dist-info directory name."""
    for part in path.parts:
        if part.endswith(".dist-info"):
            return part[: -len(".dist-info")].split("-")[-1]
    return "bundled with Python"


def main() -> None:
    resolved = []
    for name, version, purpose, licence, pattern in COMPONENTS:
        patterns = pattern if isinstance(pattern, tuple) else (pattern,)
        paths = [resolve(p) for p in patterns]
        resolved.append((name, version or version_of(paths[0]), purpose, licence, paths))

    lines = [HEADER]
    for i, (name, version, _, licence, _) in enumerate(resolved, 1):
        lines.append(f"  {i}. {name} {version} -- {licence}")
    lines.append("")

    for i, (name, version, purpose, licence, paths) in enumerate(resolved, 1):
        lines.append("=" * 79)
        lines.append(f"{i}. {name} {version}")
        lines.append("=" * 79)
        lines.append("")
        lines.append(f"Used for: {purpose}.")
        lines.append("")
        lines.append(f"Licence: {licence}")
        lines.append("")
        for path in paths:
            if len(paths) > 1:
                lines.append(f"--- {path.name} ---")
                lines.append("")
            text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
            lines.append(text.strip())
            lines.append("")
        lines.append("")

    OUT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\r\n")
    size = OUT.stat().st_size
    print(f"wrote {OUT.name}  ({size / 1024:.1f} KB)")
    for name, version, _, licence, paths in resolved:
        print(f"  {name} {version}: {licence}")
        for path in paths:
            print(f"      from {path.relative_to(PROJECT)}")


if __name__ == "__main__":
    main()
