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


class TestTheGuiHelpTextIsTrue:
    """The hint under the page field, and the dialog shown when a spec is
    rejected, both promise specific behaviour. These assert the parser delivers
    it, in both directions: a documented form must work, and the documentation
    must still be in the window.
    """

    # The forms the hint under the field must name: the ones nobody would
    # guess. `1` and `2-5` are not among them -- anyone wanting pages 2 to 5
    # will type `2-5` and be right -- and all six on one line measures 807px
    # against 720px of usable width, so the hint would clip.
    HINT_MUST_SHOW = ["1-3,7", "7-", "!4"]

    # Everything the GUI promises anywhere, and what a 9-page document gives.
    DOCUMENTED = [
        ("", [1, 2, 3, 4, 5, 6, 7, 8, 9]),          # Blank = All Pages
        ("1", [1]),                                  # 1 = Page 1
        ("2-5", [2, 3, 4, 5]),                       # 2-5 = Pages 2 to 5
        ("1-3,7", [1, 2, 3, 7]),                     # 1-3,7 = Pages 1-3 & 7
        ("7-", [7, 8, 9]),                           # 7- = Page 7 to the end
        ("!4", [1, 2, 3, 5, 6, 7, 8, 9]),            # !4 = All except page 4
    ]

    @staticmethod
    def _gui_strings() -> list[str]:
        """Every string literal in merge_gui.pyw, with implicit concatenation
        already joined.

        Read with `ast` rather than grepped. Both strings under test are built
        from several adjacent literals, and the rejection dialog starts with an
        f-string, so it parses as a JoinedStr whose pieces are separate
        constants. `ast` reassembles exactly what Python would; a regex would
        have to reimplement string syntax to match it.
        """
        import ast
        from pathlib import Path

        gui = Path(__file__).resolve().parent.parent / "merge_gui.pyw"
        assert gui.is_file(), "merge_gui.pyw is missing"
        tree = ast.parse(gui.read_text(encoding="utf-8"))

        # An f-string's own literal pieces are Constant nodes inside the
        # JoinedStr, so walking naively counts the same text twice -- once
        # joined and once in pieces. Collect the inner ones first and skip them.
        inner = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                for part in node.values:
                    if isinstance(part, ast.Constant):
                        inner.add(id(part))

        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                # Keep the literal parts, which is where the help text lives.
                # {spec!r} and friends are not of interest.
                found.append("".join(
                    part.value for part in node.values
                    if isinstance(part, ast.Constant) and isinstance(part.value, str)
                ))
            elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
                  and id(node) not in inner):
                found.append(node.value)
        return found

    def _one_string_containing(self, needle: str) -> str:
        """The single GUI string containing `needle`.

        Insisting on exactly one is part of the test: two strings describing the
        same syntax is how the window came to document `7-` in its error dialog
        and not in its hint.
        """
        matches = [text for text in self._gui_strings() if needle in text]
        assert len(matches) == 1, (
            f"expected exactly one GUI string containing {needle!r}, found "
            f"{len(matches)}"
        )
        return matches[0]

    @pytest.mark.parametrize("spec, expected", DOCUMENTED)
    def test_each_documented_form_does_what_it_says(self, spec, expected):
        """A form the help text shows must select the pages it claims. Typing
        what the window tells you to type and getting an error is the worst kind
        of bug, because the user did nothing wrong."""
        assert [p + 1 for p in merge.parse_ranges(spec, 9, "doc.pdf")] == expected

    @pytest.mark.parametrize("spec, _expected", [(s, e) for s, e in DOCUMENTED if s])
    def test_each_documented_form_passes_the_gui_validator(self, spec, _expected):
        """apply_spec() rejects anything RANGE_RE does not match before the
        parser ever sees it, so a form can be parseable and still be refused at
        the point of entry."""
        assert merge.RANGE_RE.match(spec), (
            f"the GUI documents {spec!r} but its own validator rejects it"
        )

    def test_the_hint_still_shows_every_form(self):
        """If the syntax changes, the hint has to change with it. The hint is
        where users learn this language -- there is no manual in front of them.

        Checked against the hint string alone, not the whole file. The first
        version of this test searched the source and so passed with the hint
        gutted, because the forms were still named in the error dialog -- which
        only somebody who has already guessed wrong ever sees.
        """
        hint = self._one_string_containing("Custom Pages e.g.")
        for spec in self.HINT_MUST_SHOW:
            assert spec in hint, (
                f"{spec!r} is not in the hint under the page field. Either it "
                "was dropped, or the syntax changed and the hint was not "
                f"updated. The hint reads: {hint!r}"
            )
        assert "Blank = All Pages" in hint, "the hint must say what blank means"

    def test_nothing_is_explained_only_in_the_hint(self):
        """The hint and the dialog may differ -- they do different jobs -- but
        only in one direction. A form named in the hint and absent from the
        dialog would leave somebody who mistyped it with no explanation of the
        thing they were just told to use."""
        hint = self._one_string_containing("Custom Pages e.g.")
        dialog = self._one_string_containing("is not a page range")
        for spec in self.HINT_MUST_SHOW:
            if spec in hint:
                assert spec in dialog, (
                    f"the hint names {spec!r} but the rejection dialog does "
                    "not, so a user who mistypes it is told nothing about it"
                )

    def test_the_rejection_dialog_explains_rather_than_just_refusing(self):
        """Somebody reading it has already got it wrong once, so it lists every
        form, one per line, in the same words as the hint. Two vocabularies for
        one syntax is how users end up guessing."""
        dialog = self._one_string_containing("is not a page range")
        # Every form, not just the non-obvious ones: this is the reference, and
        # the reader has already been refused once.
        for spec, _ in self.DOCUMENTED:
            if not spec:
                continue
            assert spec in dialog, (
                f"the rejection dialog does not mention {spec!r}, so somebody "
                "who guessed wrong is not told about it"
            )
        assert "Blank = All Pages" in dialog
        # One per line: a dialog has the vertical room the hint does not.
        assert dialog.count("\n") >= 6, (
            "the dialog should list the forms on separate lines rather than "
            "running them together as the old wording did"
        )
