"""Shared fixtures.

The project is a pair of scripts rather than an installed package, so the tests
put the project root on sys.path the same way merge_gui.pyw does. merge_gui is
imported under a module name of its own because the .pyw extension keeps the
normal import machinery from finding it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

import merge  # noqa: E402


@pytest.fixture(scope="session")
def gui():
    """merge_gui, imported despite its .pyw extension."""
    spec = importlib.util.spec_from_file_location(
        "merge_gui_under_test", PROJECT / "merge_gui.pyw"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def blank_pdf(tmp_path):
    """Make a PDF of n blank A4 pages. Returns a factory."""
    from pypdf import PdfWriter

    def make(name: str, pages: int, width: float = 595.0, height: float = 842.0) -> Path:
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=width, height=height)
        path = tmp_path / name
        with open(path, "wb") as handle:
            writer.write(handle)
        return path

    return make


@pytest.fixture
def default_args():
    """The parser's own defaults, so tests cannot drift from the real ones."""
    return merge.build_parser().parse_args([])
