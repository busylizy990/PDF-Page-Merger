"""The finishing logic: contents page, page numbering, image sizing, naming.

The index is the interesting one. A contents page shifts every page after it,
including the numbers printed on itself, so index_page_count() has to settle its
own length before anything is laid out. PROJECT-NOTES records that as verified
against a 2-page index; this pins it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import merge

A4 = (595.276, 841.89)


class TestIndexPageCount:
    def test_a_short_index_is_one_page(self, default_args):
        assert merge.index_page_count(3, A4, default_args) == 1

    def test_it_grows_to_two_pages_when_it_has_to(self, default_args):
        """Find the boundary rather than hard-coding a row count, so the test
        survives a change of default font size or leading."""
        first_page_capacity = merge._index_rows_per_page(A4[1], default_args, first=True)
        assert merge.index_page_count(first_page_capacity, A4, default_args) == 1
        assert merge.index_page_count(first_page_capacity + 1, A4, default_args) == 2

    def test_it_keeps_growing(self, default_args):
        first = merge._index_rows_per_page(A4[1], default_args, first=True)
        rest = merge._index_rows_per_page(A4[1], default_args, first=False)
        assert merge.index_page_count(first + rest, A4, default_args) == 2
        assert merge.index_page_count(first + rest + 1, A4, default_args) == 3

    def test_the_first_page_holds_fewer_because_of_the_heading(self, default_args):
        first = merge._index_rows_per_page(A4[1], default_args, first=True)
        rest = merge._index_rows_per_page(A4[1], default_args, first=False)
        assert first < rest

    def test_never_zero_rows_even_with_absurd_settings(self, default_args):
        default_args.index_leading = 10_000.0
        assert merge._index_rows_per_page(A4[1], default_args, first=True) >= 1

    def test_a_single_entry_is_always_one_page(self, default_args):
        assert merge.index_page_count(1, A4, default_args) == 1


class TestTextWidth:
    def test_digits_are_all_the_same_width(self):
        """Right-aligned page numbers are only exact because this is true of
        Helvetica -- every digit is 556 units wide."""
        widths = {merge.text_width(d, 10.0) for d in "0123456789"}
        assert len(widths) == 1

    def test_width_is_proportional_to_length(self):
        one = merge.text_width("1", 10.0)
        assert merge.text_width("11", 10.0) == pytest.approx(2 * one)
        assert merge.text_width("111", 10.0) == pytest.approx(3 * one)

    def test_width_scales_with_point_size(self):
        assert merge.text_width("1", 20.0) == pytest.approx(2 * merge.text_width("1", 10.0))

    def test_empty_string_is_zero(self):
        assert merge.text_width("", 12.0) == 0


class TestUniqueOutput:
    def test_an_unused_name_is_left_alone(self, tmp_path):
        target = tmp_path / "merged.pdf"
        assert merge.unique_output(target) == target

    def test_it_steps_aside_rather_than_clobbering(self, tmp_path):
        target = tmp_path / "merged.pdf"
        target.write_bytes(b"%PDF-1.7\n")
        assert merge.unique_output(target) == tmp_path / "merged-2.pdf"

    def test_it_keeps_counting(self, tmp_path):
        (tmp_path / "merged.pdf").write_bytes(b"x")
        (tmp_path / "merged-2.pdf").write_bytes(b"x")
        (tmp_path / "merged-3.pdf").write_bytes(b"x")
        assert merge.unique_output(tmp_path / "merged.pdf") == tmp_path / "merged-4.pdf"

    def test_the_suffix_is_preserved(self, tmp_path):
        target = tmp_path / "bundle.pdf"
        target.write_bytes(b"x")
        assert merge.unique_output(target).suffix == ".pdf"


class TestDominantPageSize:
    def test_the_majority_size_wins(self, blank_pdf, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        a4 = blank_pdf("a4.pdf", 3, 595.0, 842.0)
        letter = blank_pdf("letter.pdf", 1, 612.0, 792.0)
        items = [(str(a4), None), (str(letter), None)]
        width, height = merge.dominant_page_size(items, {})
        assert (round(width), round(height)) == (595, 842)

    def test_only_the_pages_actually_merged_are_counted(self, blank_pdf, monkeypatch, tmp_path):
        """Three A4 pages lose to two Letter pages once the spec drops two of them."""
        monkeypatch.chdir(tmp_path)
        a4 = blank_pdf("a4.pdf", 3, 595.0, 842.0)
        letter = blank_pdf("letter.pdf", 2, 612.0, 792.0)
        items = [(str(a4), "1"), (str(letter), None)]
        width, _ = merge.dominant_page_size(items, {})
        assert round(width) == 612

    def test_none_when_there_are_no_pdf_pages(self):
        assert merge.dominant_page_size([], {}) is None


class TestFileKinds:
    @pytest.mark.parametrize("name", ["a.jpg", "a.JPEG", "a.png", "a.tif", "a.webp", "a.heic"])
    def test_images(self, name):
        assert merge.is_image(Path(name))

    @pytest.mark.parametrize("name", ["a.docx", "a.doc", "a.rtf", "a.odt"])
    def test_word(self, name):
        assert merge.is_word(Path(name))
        assert merge.office_app_for(Path(name)) == "WORD"

    @pytest.mark.parametrize("name", ["a.xlsx", "a.xls", "a.csv", "a.ods"])
    def test_excel(self, name):
        assert merge.is_excel(Path(name))
        assert merge.office_app_for(Path(name)) == "EXCEL"

    @pytest.mark.parametrize("name", ["a.pdf", "a.txt", "a.zip"])
    def test_not_converted(self, name):
        assert not merge.needs_conversion(Path(name))

    def test_extension_case_is_ignored(self):
        assert merge.is_excel(Path("LEDGER.XLSX"))
        assert merge.is_word(Path("Statement.DOCX"))
