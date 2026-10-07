#!/usr/bin/env python
"""Render LICENCE-TERMS.md into packaging\\EULA.rtf for the installer's licence page.

Inno Setup's LicenseFile shows an accept/decline page and will not continue
without acceptance. It reads RTF, which is why this exists: the terms are
written once, in Markdown, and the formatted copy the installer displays is
generated from them.

The same reasoning as make_notices.py, for the same reason. A second,
hand-formatted copy of a legal document is a copy that will eventually disagree
with the first, and disagreeing copies of the terms you sell on are worse than
no formatting at all. build.ps1 regenerates this before every Inno Setup run and
says so if the result differs from what was committed.

    .python\\python.exe packaging\\make_eula.py

Only the Markdown this document actually uses is supported -- headings, wrapped
paragraphs, bullet lists, bold, italic and code spans, and the --- rule. Tables,
links, nested lists and block quotes are not; add them here before using them in
LICENCE-TERMS.md, or they will come out as literal text.
"""

from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
SOURCE = PROJECT / "LICENCE-TERMS.md"
OUT = HERE / "EULA.rtf"

# Half-points, because that is the unit RTF uses for \fs.
BODY_SIZE = 19       # 9.5pt -- the licence box is small and the document is long
H1_SIZE = 30
H2_SIZE = 23

PREAMBLE = (
    r"{\rtf1\ansi\ansicpg1252\deff0\uc1"
    r"{\fonttbl{\f0\fswiss\fcharset0 Segoe UI;}{\f1\fmodern\fcharset0 Consolas;}}"
    r"{\colortbl;\red0\green0\blue0;\red90\green90\blue90;}"
    "\n\\f0\\fs%d\\cf1\n" % BODY_SIZE
)

INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\*[^*]+\*)")

# A bracketed span still to be filled in -- [CONTACT EMAIL], and also the ones
# carrying lower case around a choice, such as "[a company registered in England
# and Wales under number [NUMBER] / a sole trader]". One level of nesting is
# allowed so that outer span is reported whole rather than as its inner part,
# and a run of capitals is required so an ordinary bracketed aside is not
# mistaken for a blank. build.ps1 uses the same pattern to refuse a signed build.
PLACEHOLDER = re.compile(r"\[(?:[^\[\]]|\[[^\]]*\])*\]")


def find_placeholders(markdown: str) -> list[str]:
    # Soft-wrapped so that one of them spans two source lines; collapse the
    # whitespace so it is reported on one.
    return [
        " ".join(m.split())
        for m in PLACEHOLDER.findall(markdown)
        if re.search(r"[A-Z]{2,}", m)
    ]


def escape(text: str) -> str:
    """Make a run of plain text safe to drop into RTF.

    Backslash and braces are RTF's own syntax. Everything outside ASCII goes out
    as \\uNNNN with a '?' fallback for readers that cannot handle it -- the
    document is full of em dashes and curly quotes, and cp1252 byte escapes
    would be guesswork about the reader's codepage.
    """
    out = []
    for ch in text:
        if ch in "\\{}":
            out.append("\\" + ch)
        elif ord(ch) < 128:
            out.append(ch)
        else:
            out.append("\\u%d?" % ord(ch))
    return "".join(out)


def inline(text: str) -> str:
    """Convert **bold**, *italic* and `code` spans, escaping everything else.

    Bold and italic recurse, because an emphasised run can contain a code span
    -- the closing line of the terms is a whole italic paragraph that mentions
    `THIRD-PARTY-NOTICES.txt`, and without recursion its backticks reach the
    customer as backticks.
    """
    parts = []
    for token in INLINE.split(text):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**"):
            parts.append(r"{\b %s}" % inline(token[2:-2]))
        elif token.startswith("`") and token.endswith("`"):
            parts.append(r"{\f1 %s}" % escape(token[1:-1]))
        elif token.startswith("*") and token.endswith("*"):
            parts.append(r"{\i %s}" % inline(token[1:-1]))
        else:
            parts.append(escape(token))
    return "".join(parts)


def blocks(lines: list[str]):
    """Group the Markdown into (kind, text) blocks, unwrapping soft line breaks.

    Markdown wraps paragraphs across lines for the benefit of the person editing
    them; RTF wraps them itself, so a wrapped paragraph has to be rejoined into
    one run or every source line becomes its own paragraph.
    """
    para: list[str] = []
    kind = "p"

    def flush():
        nonlocal para, kind
        if para:
            yield kind, " ".join(para)
            para = []
        kind = "p"

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            yield from flush()
            continue

        if stripped == "---":
            yield from flush()
            yield "rule", ""
            continue

        if stripped.startswith("#"):
            yield from flush()
            level = len(stripped) - len(stripped.lstrip("#"))
            yield "h%d" % min(level, 2), stripped.lstrip("#").strip()
            continue

        if stripped.startswith("- "):
            yield from flush()
            kind = "li"
            para = [stripped[2:].strip()]
            continue

        # An indented line under a bullet continues that bullet; anything else
        # continues the paragraph.
        para.append(stripped)

    yield from flush()


def render(markdown: str) -> str:
    out = [PREAMBLE]
    for kind, text in blocks(markdown.splitlines()):
        if kind == "rule":
            out.append(r"\pard\sa100\qc\cf2 " + r"\u8212?\u8212?\u8212?" + "\\par\\cf1\n")
        elif kind == "h1":
            out.append(r"\pard\sa160\keepn\fs%d{\b %s}\par\fs%d" % (
                H1_SIZE, inline(text), BODY_SIZE) + "\n")
        elif kind == "h2":
            out.append(r"\pard\sb220\sa110\keepn\fs%d{\b %s}\par\fs%d" % (
                H2_SIZE, inline(text), BODY_SIZE) + "\n")
        elif kind == "li":
            out.append(r"\pard\fi-240\li360\sa70 \u8226?\tab " + inline(text) + "\\par\n")
        else:
            out.append(r"\pard\sa110\sl260\slmult1 " + inline(text) + "\\par\n")
    out.append("}\n")
    return "".join(out)


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit("LICENCE-TERMS.md not found at %s" % SOURCE)

    markdown = SOURCE.read_text(encoding="utf-8")
    rtf = render(markdown)

    # RTF is ASCII by construction here: escape() turns everything else into
    # \uNNNN. Write it as such so no editor can silently re-encode it.
    OUT.write_text(rtf, encoding="ascii", newline="\r\n")

    placeholders = sorted(set(find_placeholders(markdown)))
    print("wrote %s  (%.1f KB)" % (OUT.name, OUT.stat().st_size / 1024))
    if placeholders:
        print("  STILL TO FILL IN before a build anyone receives:")
        for item in placeholders:
            print("      %s" % item)


if __name__ == "__main__":
    main()
