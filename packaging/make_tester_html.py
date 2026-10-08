"""Render docs\\tester-note.md as a self-contained HTML page.

The tester note is handed to friends, family and anyone else trying the program
informally -- usually on a USB stick alongside the installer. They double-click
whatever they are given.

Markdown is the wrong thing to hand them: a .md file opens in Notepad as raw
markup, asterisks and bracket-checkboxes and all, which rather undercuts a note
whose job is to be reassuring about an installer Windows has just called
"Unknown".

RTF was the obvious alternative, since this project already renders Markdown to
RTF in make_eula.py for the installer's licence page. It was rejected because
**Windows 11 removed WordPad**: on a machine without Word, an .rtf now opens in
nothing at all.

HTML opens in a browser on every Windows machine there has ever been. The page
produced here embeds its own styles and uses no scripts, no web fonts and no
external stylesheet, so it renders identically from a USB stick on a computer
with no network.

Usage:
    .python\\python.exe packaging\\make_tester_html.py

The result is committed, so the ready-to-copy file is always in the repository.
tests/test_packaging.py asserts it matches what this script renders, so editing
the Markdown and forgetting to re-run this fails the suite rather than reaching
a tester as a stale page.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SOURCE = PROJECT / "docs" / "tester-note.md"
TARGET = PROJECT / "docs" / "tester-note.html"

# Embedded rather than linked, for the reason in the module docstring: this file
# has to render correctly from removable media with no network.
STYLES = """\
  :root { color-scheme: light; }
  body {
    font-family: "Segoe UI", system-ui, sans-serif;
    font-size: 17px;
    line-height: 1.6;
    color: #1a1a1a;
    background: #fbfbfa;
    margin: 0;
    padding: 2.5rem 1rem 4rem;
  }
  main { max-width: 38rem; margin: 0 auto; }
  h1 { font-size: 1.7rem; line-height: 1.25; margin: 0 0 1.5rem; }
  h2 { font-size: 1.2rem; margin: 2.4rem 0 .6rem; }
  h3 { font-size: 1.05rem; margin: 1.8rem 0 .5rem; }
  p, li { margin: 0 0 .9rem; }
  hr { border: 0; border-top: 1px solid #e0ded9; margin: 2.2rem 0; }
  code {
    font-family: Consolas, ui-monospace, monospace;
    font-size: .9em;
    background: #efeee9;
    padding: .1em .35em;
    border-radius: 3px;
  }
  ul { padding-left: 1.3rem; }
  ul.tasks { list-style: none; padding-left: 0; }
  ul.tasks li { position: relative; padding-left: 2rem; margin-bottom: 1rem; }
  .box {
    position: absolute; left: 0; top: .25em;
    width: 1.05em; height: 1.05em;
    border: 1.5px solid #9a968d; border-radius: 3px; background: #fff;
  }
  strong { font-weight: 600; }
  @media print { body { background: #fff; padding: 0; } }"""

CHECKBOX_ITEM = re.compile(r"^-\s+\[([ xX])\]\s+(.*)$")
PLAIN_ITEM = re.compile(r"^-\s+(?!\[)(.*)$")
HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
CONTINUATION = re.compile(r"^\s{4,}\S")


def inline(text: str) -> str:
    """Escape everything, then restore the few inline markers the note uses.

    Escaping first means a stray < or & in the Markdown cannot produce broken
    HTML, and the replacements below only ever introduce tags of our own.
    """
    out = html.escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", out)
    return out


def render_body(markdown: str) -> str:
    lines = markdown.splitlines()
    parts: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None   # None, 'tasks' or 'plain'

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            parts.append("<p>" + inline(" ".join(paragraph)) + "</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            parts.append("</ul>")
            list_kind = None

    def open_list(kind: str) -> None:
        # Switching between a checklist and a plain list starts a new <ul>, so a
        # mixed run does not inherit the wrong styling.
        nonlocal list_kind
        if list_kind != kind:
            close_list()
            parts.append('<ul class="tasks">' if kind == "tasks" else "<ul>")
            list_kind = kind

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if not stripped:
            flush_paragraph()
            close_list()
            i += 1
            continue

        if stripped == "---":
            flush_paragraph()
            close_list()
            parts.append("<hr>")
            i += 1
            continue

        heading = HEADING.match(stripped)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            parts.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        checkbox = CHECKBOX_ITEM.match(stripped)
        plain = None if checkbox else PLAIN_ITEM.match(stripped)
        if checkbox or plain:
            flush_paragraph()
            open_list("tasks" if checkbox else "plain")
            body = checkbox.group(2) if checkbox else plain.group(1)
            # A wrapped list item continues on following indented lines.
            continued = []
            while i + 1 < len(lines) and CONTINUATION.match(lines[i + 1]):
                continued.append(lines[i + 1].strip())
                i += 1
            mark = '<span class="box"></span>' if checkbox else ""
            parts.append(f"<li>{mark}{inline(' '.join([body] + continued))}</li>")
            i += 1
            continue

        paragraph.append(stripped)
        i += 1

    flush_paragraph()
    close_list()
    return "\n".join(parts)


def render(markdown: str) -> str:
    first = markdown.splitlines()[0] if markdown.splitlines() else "PDF Page Merger"
    title = first.lstrip("# ").strip()
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
{STYLES}
</style>
</head>
<body>
<main>
{render_body(markdown)}
</main>
</body>
</html>
"""


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"{SOURCE.name} is missing; there is nothing to render.")
    page = render(SOURCE.read_text(encoding="utf-8"))
    TARGET.write_text(page, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.name}  ({len(page) / 1024:.1f} KB)")
    print("Copy it to the USB stick beside the installer. Markdown is not what a")
    print("tester should be handed, and Windows 11 has no WordPad for RTF.")


if __name__ == "__main__":
    main()
