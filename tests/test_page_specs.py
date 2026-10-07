"""Page specs: the part users type by hand, so the part most worth pinning down.

Covers the keep/drop distinction that PROJECT-NOTES calls out as deliberate, and
the Windows-path case that makes splitting on the last colon fiddly.
"""

from __future__ import annotations

import pytest

import merge


class TestSplitSpec:
    @pytest.mark.parametrize(
        "token, expected",
        [
            ("file.pdf:1-3", ("file.pdf", "1-3")),
            ("file.pdf:7", ("file.pdf", "7")),
            ("file.pdf:!7", ("file.pdf", "!7")),
            ("file.pdf:~2-4", ("file.pdf", "~2-4")),
            ("file.pdf:all", ("file.pdf", "all")),
            ("file.pdf", ("file.pdf", None)),
            ('"file.pdf"', ("file.pdf", None)),
            ("  file.pdf:2  ", ("file.pdf", "2")),
        ],
    )
    def test_splits_on_a_real_spec(self, token, expected):
        assert merge.split_spec(token) == expected

    @pytest.mark.parametrize(
        "token",
        [
            r"C:\docs\file.pdf",
            r"C:\docs\My Bundle\file.pdf",
            "D:/exhibits/file.pdf",
        ],
    )
    def test_leaves_windows_paths_alone(self, token):
        """A drive letter is a colon too; it must not be read as a page spec."""
        path, spec = merge.split_spec(token)
        assert spec is None
        assert path == token

    def test_drive_letter_plus_a_real_spec(self):
        path, spec = merge.split_spec(r"C:\docs\file.pdf:2-4")
        assert path == r"C:\docs\file.pdf"
        assert spec == "2-4"


class TestParseLine:
    @pytest.mark.parametrize("line", ["", "   ", "# a comment", "   # indented comment"])
    def test_blanks_and_comments_are_skipped(self, line):
        assert merge.parse_line(line) is None

    def test_trailing_comment_is_stripped(self):
        assert merge.parse_line("file.pdf:1-3  # the good bit") == ("file.pdf", "1-3")

    def test_whitespace_form(self):
        """order.txt.example documents 'my file.pdf   1-3,7' as well as a colon."""
        assert merge.parse_line("my file.pdf   1-3,7") == ("my file.pdf", "1-3,7")

    def test_space_in_name_without_a_spec_is_not_mistaken_for_one(self):
        assert merge.parse_line("Witness Statement.pdf") == ("Witness Statement.pdf", None)


class TestParseRangesKeeping:
    @pytest.mark.parametrize("spec", [None, "", "   ", "all", "ALL", "*"])
    def test_everything(self, spec):
        assert merge.parse_ranges(spec, 5, "f") == [0, 1, 2, 3, 4]

    def test_single_page_is_zero_based(self):
        assert merge.parse_ranges("1", 5, "f") == [0]
        assert merge.parse_ranges("5", 5, "f") == [4]

    def test_inclusive_range(self):
        assert merge.parse_ranges("2-4", 5, "f") == [1, 2, 3]

    def test_open_ended_start_and_end(self):
        assert merge.parse_ranges("3-", 5, "f") == [2, 3, 4]
        assert merge.parse_ranges("-3", 5, "f") == [0, 1, 2]

    def test_order_is_preserved_so_a_spec_reorders(self):
        assert merge.parse_ranges("3,1", 5, "f") == [2, 0]

    def test_repetition_is_allowed(self):
        """A cover page used twice is a feature, not a mistake."""
        assert merge.parse_ranges("1,1,2", 5, "f") == [0, 0, 1]

    def test_whitespace_is_tolerated(self):
        assert merge.parse_ranges(" 1 , 3 - 4 ", 5, "f") == [0, 2, 3]


class TestParseRangesDropping:
    @pytest.mark.parametrize("marker", ["!", "~"])
    def test_both_markers_drop(self, marker):
        assert merge.parse_ranges(f"{marker}2", 4, "f") == [0, 2, 3]

    def test_dropping_preserves_original_order(self):
        """Unlike a keep-list, an exclusion never reorders."""
        assert merge.parse_ranges("!3,1", 5, "f") == [1, 3, 4]

    def test_dropping_a_range(self):
        assert merge.parse_ranges("!2-4", 6, "f") == [0, 4, 5]

    def test_dropping_everything_is_refused(self):
        with pytest.raises(ValueError, match="would leave nothing"):
            merge.parse_ranges("!1-3", 3, "f")

    def test_bare_marker_is_refused(self):
        with pytest.raises(ValueError, match="nothing to drop"):
            merge.parse_ranges("!", 3, "f")


class TestParseRangesRejections:
    def test_beyond_the_end(self):
        with pytest.raises(ValueError, match="exceeds"):
            merge.parse_ranges("9", 5, "f")

    def test_backwards_range(self):
        with pytest.raises(ValueError, match="invalid page range"):
            merge.parse_ranges("4-2", 5, "f")

    def test_page_zero(self):
        with pytest.raises(ValueError, match="invalid page range"):
            merge.parse_ranges("0", 5, "f")

    def test_the_label_appears_so_the_user_knows_which_file(self):
        with pytest.raises(ValueError, match="bundle.pdf"):
            merge.parse_ranges("99", 2, "bundle.pdf")


class TestDescribeSpec:
    @pytest.mark.parametrize(
        "spec, pages, expected",
        [
            (None, 7, "1-7"),
            ("", 7, "1-7"),
            ("2-4", 7, "2-4"),
            ("!7", 7, "all except 7"),
            ("~2-4", 7, "all except 2-4"),
        ],
    )
    def test_reads_as_the_summary_prints_it(self, spec, pages, expected):
        assert merge.describe_spec(spec, pages) == expected


class TestNaturalKey:
    def test_page2_sorts_before_page10(self):
        from pathlib import Path

        names = [Path("page10.pdf"), Path("page2.pdf"), Path("page1.pdf")]
        assert [p.name for p in sorted(names, key=merge.natural_key)] == [
            "page1.pdf",
            "page2.pdf",
            "page10.pdf",
        ]
