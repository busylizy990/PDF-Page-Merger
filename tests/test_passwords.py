"""Supplying a password for an encrypted PDF.

The security property matters as much as the feature: a password must not end up
in the log, in the output, or in the command line the window echoes.
"""

from __future__ import annotations

import pytest
from pypdf import PdfReader, PdfWriter

import merge


@pytest.fixture
def locked_pdf(tmp_path):
    def make(name: str, password: str, pages: int = 2):
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=595, height=842)
        writer.encrypt(user_password=password, owner_password=password,
                       algorithm="AES-256")
        path = tmp_path / name
        with open(path, "wb") as handle:
            writer.write(handle)
        return path

    return make


class TestUnlock:
    def test_an_unencrypted_reader_needs_nothing(self, blank_pdf):
        assert merge.unlock(PdfReader(str(blank_pdf("a.pdf", 1)))) is True

    def test_the_empty_password_is_tried_first(self, tmp_path):
        """A document secured against editing opens with no password at all."""
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.encrypt(user_password="", owner_password="owner", algorithm="AES-256")
        path = tmp_path / "secured.pdf"
        with open(path, "wb") as handle:
            writer.write(handle)
        assert merge.unlock(PdfReader(str(path))) is True

    def test_the_right_password_opens_it(self, locked_pdf):
        reader = PdfReader(str(locked_pdf("x.pdf", "letmein")))
        assert merge.unlock(reader, ("letmein",)) is True

    def test_the_wrong_one_does_not(self, locked_pdf):
        reader = PdfReader(str(locked_pdf("x.pdf", "letmein")))
        assert merge.unlock(reader, ("nope",)) is False

    def test_it_tries_them_all(self, locked_pdf):
        reader = PdfReader(str(locked_pdf("x.pdf", "third")))
        assert merge.unlock(reader, ("first", "second", "third")) is True

    def test_it_never_raises(self, locked_pdf):
        """A wrong password should cost one file, not end the merge."""
        reader = PdfReader(str(locked_pdf("x.pdf", "letmein")))
        assert merge.unlock(reader, ("", None.__class__.__name__, "x" * 500)) is False


class TestResolvePasswords:
    def _args(self, **kw):
        args = merge.build_parser().parse_args([])
        for key, value in kw.items():
            setattr(args, key, value)
        return args

    def test_nothing_supplied_is_an_empty_tuple(self):
        assert merge.resolve_passwords(self._args()) == ()

    def test_the_keyword_argument_comes_first(self):
        assert merge.resolve_passwords(self._args(), ["a", "b"]) == ("a", "b")

    def test_duplicates_are_dropped_and_order_kept(self):
        got = merge.resolve_passwords(self._args(password=["b", "a", "b"]), ["a"])
        assert got == ("a", "b")

    def test_read_from_a_file_ignoring_comments_and_blanks(self, tmp_path):
        path = tmp_path / "pw.txt"
        path.write_text("# notes\n\nfirst\nsecond\n", encoding="utf-8")
        assert merge.resolve_passwords(self._args(password_file=str(path))) == (
            "first",
            "second",
        )

    def test_a_bom_on_the_password_file_is_tolerated(self, tmp_path):
        path = tmp_path / "pw.txt"
        path.write_text("letmein\n", encoding="utf-8-sig")
        assert merge.resolve_passwords(self._args(password_file=str(path))) == ("letmein",)

    def test_a_missing_file_is_a_clean_exit_not_a_traceback(self, tmp_path):
        with pytest.raises(SystemExit, match="Could not read"):
            merge.resolve_passwords(self._args(password_file=str(tmp_path / "nope.txt")))


class TestThroughTheCommandLine:
    def test_the_password_unlocks_the_file(self, locked_pdf, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        locked = locked_pdf("locked.pdf", "letmein", pages=3)
        assert merge.main([str(locked), "--password", "letmein",
                           "-o", "out.pdf", "--force"]) == 0
        assert len(PdfReader(str(tmp_path / "out.pdf")).pages) == 3

    def test_several_passwords_for_a_mixed_bundle(self, locked_pdf, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        one = locked_pdf("one.pdf", "alpha", pages=2)
        two = locked_pdf("two.pdf", "beta", pages=3)
        assert merge.main([str(one), str(two), "--password", "alpha",
                           "--password", "beta", "-o", "out.pdf", "--force"]) == 0
        assert len(PdfReader(str(tmp_path / "out.pdf")).pages) == 5

    def test_a_wrong_password_still_skips_cleanly(self, locked_pdf, tmp_path,
                                                 monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        locked = locked_pdf("locked.pdf", "letmein")
        merge.main([str(locked), "--password", "wrong", "-o", "out.pdf", "--force"])
        assert "password protected" in capsys.readouterr().out

    def test_the_hint_appears_only_when_no_password_was_given(self, locked_pdf, tmp_path,
                                                             monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        locked = locked_pdf("locked.pdf", "letmein")
        merge.main([str(locked), "-o", "a.pdf", "--force"])
        assert "try --password" in capsys.readouterr().out
        merge.main([str(locked), "--password", "wrong", "-o", "b.pdf", "--force"])
        assert "try --password" not in capsys.readouterr().out

    def test_ranges_work_on_an_unlocked_file(self, locked_pdf, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        locked = locked_pdf("locked.pdf", "letmein", pages=6)
        merge.main([f"{locked}:2-4", "--password", "letmein", "-o", "out.pdf", "--force"])
        assert len(PdfReader(str(tmp_path / "out.pdf")).pages) == 3


class TestOutOfBand:
    def test_main_accepts_passwords_as_a_keyword(self, locked_pdf, tmp_path, monkeypatch):
        """How the window passes them, so they never reach argv."""
        monkeypatch.chdir(tmp_path)
        locked = locked_pdf("locked.pdf", "letmein", pages=2)
        code = merge.main([str(locked), "-o", "out.pdf", "--force"],
                          passwords=("letmein",))
        assert code == 0
        assert len(PdfReader(str(tmp_path / "out.pdf")).pages) == 2


class TestItIsNotLeaked:
    SECRET = "Sup3rSecret-Passphrase"

    def test_not_printed_when_it_works(self, locked_pdf, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        locked = locked_pdf("locked.pdf", self.SECRET)
        merge.main([str(locked), "--password", self.SECRET, "-o", "out.pdf", "--force"])
        assert self.SECRET not in capsys.readouterr().out

    def test_not_printed_when_it_fails(self, locked_pdf, tmp_path, monkeypatch, capsys):
        """pypdf's own exception text can carry it; unlock() swallows that."""
        monkeypatch.chdir(tmp_path)
        locked = locked_pdf("locked.pdf", "the-real-one")
        merge.main([str(locked), "--password", self.SECRET, "-o", "out.pdf", "--force"])
        captured = capsys.readouterr()
        assert self.SECRET not in captured.out
        assert self.SECRET not in captured.err

    def test_not_written_into_the_merged_pdf(self, locked_pdf, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        locked = locked_pdf("locked.pdf", self.SECRET)
        merge.main([str(locked), "--password", self.SECRET, "-o", "out.pdf", "--force"])
        assert self.SECRET.encode() not in (tmp_path / "out.pdf").read_bytes()

    def test_the_window_does_not_put_it_in_the_command_line(self):
        """build_argv is echoed into the log, so it must never carry a password."""
        import inspect
        import importlib.util
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "gui_argv_check", Path(merge.__file__).parent / "merge_gui.pyw"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = inspect.getsource(module.MergerWindow.build_argv)
        assert "password" not in source.lower()

    def test_a_password_is_not_a_preset_field(self, gui):
        """Presets are written to settings.json, which is plain text on disk."""
        assert not any("password" in field.lower() for field in gui.PRESET_FIELDS)
        assert gui.clean_preset({"password": "x"}) is None
