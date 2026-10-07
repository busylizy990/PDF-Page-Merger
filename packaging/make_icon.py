#!/usr/bin/env python3
"""
Draw the application icon.

Generated rather than shipped as a binary, so it can be adjusted in one place and
regenerated. Needs Pillow, which the tool already uses for images.

    python packaging\\make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
TARGET = HERE / "icon.ico"

# Sizes Windows actually asks for, largest first.
SIZES = (256, 128, 64, 48, 32, 24, 16)

PAPER = (252, 252, 250)
PAPER_EDGE = (176, 178, 184)
BACK_PAPER = (226, 228, 232)
ACCENT = (176, 42, 42)       # the dog-eared corner
RULE = (150, 154, 162)


def draw_icon(size: int) -> Image.Image:
    """One square icon, drawn at 4x and shrunk so the edges stay smooth."""
    scale = 4
    box = size * scale
    image = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)

    unit = box / 32.0          # design on a 32x32 grid, then scale
    radius = max(1, int(unit * 1.2))

    # The sheet behind, peeking out at the top left.
    pen.rounded_rectangle(
        [unit * 5, unit * 3, unit * 23, unit * 27],
        radius=radius, fill=BACK_PAPER, outline=PAPER_EDGE, width=max(1, int(unit * 0.35)),
    )

    # The front sheet, offset down and right.
    left, top, right, bottom = unit * 9, unit * 6, unit * 27, unit * 29
    pen.rounded_rectangle(
        [left, top, right, bottom],
        radius=radius, fill=PAPER, outline=PAPER_EDGE, width=max(1, int(unit * 0.35)),
    )

    # Folded corner, top right of the front sheet.
    fold = unit * 6
    pen.polygon(
        [(right - fold, top), (right, top + fold), (right - fold, top + fold)],
        fill=ACCENT,
    )

    # A few ruled lines. Below about 32px they turn to mush, so drop them.
    if size >= 32:
        line_left = left + unit * 2.5
        line_right = right - unit * 2.5
        thickness = max(1, int(unit * 0.8))
        for step in range(4):
            y = top + unit * (11 + step * 3.6)
            end = line_right if step < 3 else line_right - unit * 4
            pen.line([(line_left, y), (end, y)], fill=RULE, width=thickness)

    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    frames = [draw_icon(size) for size in SIZES]
    frames[0].save(TARGET, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"wrote {TARGET}  ({TARGET.stat().st_size:,} bytes, sizes: "
          f"{', '.join(str(s) for s in SIZES)})")


if __name__ == "__main__":
    main()
