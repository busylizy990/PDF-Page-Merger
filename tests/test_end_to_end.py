"""Whole merges through main(), the way a user actually invokes it.

These are the tests that would notice if the pieces stopped fitting together --
the unit tests above all pass happily while producing a broken PDF.
"""

from __future__ import annotations

import pytest
from pypdf import PdfReader

import merge


@pytest.fixture
def run(tmp_path, monkeypatch):
    """Run the command line in a scratch directory and read the result back."""

    def go(*argv: str, out: str = "merged.pdf") -> PdfReader:
        monkeypatch.chdir(tmp_path)
        code = merge.main([*argv, "-o", out, "--force"])
        assert code == 0, f"merge.main exited {code}"
        produced = tmp_path / out
        assert produced.is_file(), "no output file was produced"
        return PdfReader(str(produced))

    return go


class TestPlainMerges:
    def test_two_files_concatenate(self, blank_pdf, run):
        a, b = blank_pdf("a.pdf", 3), blank_pdf("b.pdf", 4)
        assert len(run(str(a), str(b)).pages) == 7

    def test_a_range_selects_pages(self, blank_pdf, run):
        a = blank_pdf("a.pdf", 10)
        assert len(run(f"{a}:2-4").pages) == 3

    def test_an_exclusion_drops_pages(self, blank_pdf, run):
        a = blank_pdf("a.pdf", 10)
        assert len(run(f"{a}:!5").pages) == 9

    def test_repetition_really_repeats(self, blank_pdf, run):
        a = blank_pdf("a.pdf", 3)
        assert len(run(f"{a}:1,1,1").pages) == 3

    def test_a_single_file_is_a_valid_merge(self, blank_pdf, run):
        a = blank_pdf("a.pdf", 2)
        assert len(run(str(a)).pages) == 2

    def test_output_always_ends_up_a_pdf(self, blank_pdf, tmp_path, monkeypatch):
        """Ask for bundle.xyz and you get bundle.pdf, not a mislabelled file."""
        monkeypatch.chdir(tmp_path)
        a = blank_pdf("a.pdf", 1)
        assert merge.main([str(a), "-o", "bundle.xyz", "--force"]) == 0
        assert (tmp_path / "bundle.pdf").is_file()
        assert not (tmp_path / "bundle.xyz").exists()


class TestBookmarks:
    def test_one_per_source_by_default(self, blank_pdf, run):
        a, b, c = blank_pdf("a.pdf", 1), blank_pdf("b.pdf", 1), blank_pdf("c.pdf", 1)
        assert len(run(str(a), str(b), str(c)).outline) == 3

    def test_they_can_be_turned_off(self, blank_pdf, run):
        a, b = blank_pdf("a.pdf", 1), blank_pdf("b.pdf", 1)
        assert len(run(str(a), str(b), "--no-bookmarks").outline) == 0

    def test_they_survive_an_index_being_inserted(self, blank_pdf, run):
        """The index shifts every page after it, so the bookmark targets have to
        move with it. PROJECT-NOTES records this as a thing that was got wrong once."""
        a, b = blank_pdf("a.pdf", 2), blank_pdf("b.pdf", 2)
        reader = run(str(a), str(b), "--index")
        assert len(reader.outline) == 2
        assert len(reader.pages) == 5  # 4 content + 1 index


class TestIndex:
    def test_it_adds_a_page(self, blank_pdf, run):
        a = blank_pdf("a.pdf", 3)
        assert len(run(str(a), "--index").pages) == 4

    def test_the_index_comes_first(self, blank_pdf, run):
        """Its text is drawn by hand, so the first page should carry the title."""
        a = blank_pdf("a.pdf", 2)
        reader = run(str(a), "--index", "--index-title", "Bundle Contents")
        assert "Bundle Contents" in reader.pages[0].extract_text()

    def test_entries_name_the_sources(self, blank_pdf, run):
        a, b = blank_pdf("witness.pdf", 1), blank_pdf("exhibit.pdf", 1)
        text = run(str(a), str(b), "--index").pages[0].extract_text()
        assert "witness" in text and "exhibit" in text


class TestStamping:
    def test_every_page_is_numbered(self, blank_pdf, run):
        a = blank_pdf("a.pdf", 3)
        reader = run(str(a), "--stamp")
        for n, page in enumerate(reader.pages, start=1):
            assert str(n) in page.extract_text()

    def test_numbering_can_start_anywhere(self, blank_pdf, run):
        a = blank_pdf("a.pdf", 2)
        reader = run(str(a), "--stamp", "--stamp-start", "100")
        assert "100" in reader.pages[0].extract_text()
        assert "101" in reader.pages[1].extract_text()

    def test_a_bates_style_format(self, blank_pdf, run):
        a = blank_pdf("a.pdf", 2)
        reader = run(str(a), "--stamp", "ABC-{n:04d}")
        assert "ABC-0001" in reader.pages[0].extract_text()

    @pytest.mark.parametrize(
        "spot",
        ["bottom-right", "bottom-center", "bottom-left", "top-right", "top-center", "top-left"],
    )
    def test_all_six_positions_produce_a_number(self, blank_pdf, run, spot):
        a = blank_pdf("a.pdf", 1)
        reader = run(str(a), "--stamp", "--stamp-at", spot)
        assert "1" in reader.pages[0].extract_text()

    def test_the_index_is_numbered_too(self, blank_pdf, run):
        """The contents page is part of the bundle, so it gets a number as well."""
        a = blank_pdf("a.pdf", 2)
        reader = run(str(a), "--index", "--stamp")
        assert len(reader.pages) == 3
        assert "1" in reader.pages[0].extract_text()


class TestImages:
    @pytest.fixture
    def picture(self, tmp_path):
        from PIL import Image

        def make(name: str, size=(800, 600), colour=(200, 60, 60)):
            path = tmp_path / name
            Image.new("RGB", size, colour).save(path)
            return path

        return make

    def test_an_image_becomes_a_page(self, picture, blank_pdf, run):
        a, pic = blank_pdf("a.pdf", 1), picture("shot.png")
        assert len(run(str(a), str(pic)).pages) == 2

    def test_it_takes_the_size_of_the_pdf_pages(self, picture, blank_pdf, run):
        """Matching is the default so a bundle is one consistent size throughout."""
        a, pic = blank_pdf("a.pdf", 2, 595.0, 842.0), picture("shot.png")
        reader = run(str(a), str(pic))
        first, image_page = reader.pages[0], reader.pages[2]
        assert round(float(image_page.mediabox.width)) == round(float(first.mediabox.width))
        assert round(float(image_page.mediabox.height)) == round(float(first.mediabox.height))

    def test_a_fixed_size_can_be_demanded(self, picture, run):
        """A4 regardless of orientation -- see the rotation tests below."""
        reader = run(str(picture("tall.png", size=(600, 800))), "--image-page", "a4")
        box = reader.pages[0].mediabox
        assert sorted(round(float(v)) for v in (box.width, box.height)) == [595, 842]

    def test_a_fixed_size_auto_rotates_for_a_landscape_image(self, picture, run):
        """PROJECT-NOTES: the fixed sizes turn the sheet sideways, unlike 'match'."""
        reader = run(str(picture("wide.png", size=(800, 600))), "--image-page", "a4")
        box = reader.pages[0].mediabox
        assert float(box.width) > float(box.height), "expected landscape A4"
        assert sorted(round(float(v)) for v in (box.width, box.height)) == [595, 842]

    def test_match_does_not_turn_the_sheet_sideways(self, picture, blank_pdf, run):
        """Turning it would defeat the point of matching, so a landscape image is
        fitted inside the portrait page instead."""
        a = blank_pdf("a.pdf", 2, 595.0, 842.0)
        reader = run(str(a), str(picture("wide.png", size=(800, 600))))
        box = reader.pages[2].mediabox
        assert float(box.width) < float(box.height), "expected the page to stay portrait"

    def test_an_image_on_its_own_is_a_valid_merge(self, picture, run):
        assert len(run(str(picture("shot.png"))).pages) == 1


class TestRefusals:
    def test_a_bad_range_is_reported_not_crashed(self, blank_pdf, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        a = blank_pdf("a.pdf", 2)
        merge.main([f"{a}:99", "-o", "out.pdf", "--force"])
        assert "exceeds" in capsys.readouterr().out

    def test_a_missing_file_is_reported_not_crashed(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        merge.main(["no-such-file.pdf", "-o", "out.pdf", "--force"])
        assert "Nothing to merge" in capsys.readouterr().out

    def test_a_non_pdf_is_skipped_with_a_reason(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "notes.txt").write_text("not a pdf", encoding="utf-8")
        merge.main(["notes.txt", "-o", "out.pdf", "--force"])
        assert "skip" in capsys.readouterr().out.lower()
