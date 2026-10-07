"""Encrypted PDFs.

Reported 5 October 2026: a merge failed with "could not read (cryptography>=3.1
is required for AES algorithm)". The intent was already in merge.py -- it tries an
empty password, which opens a document secured against editing but readable
without one -- but pypdf cannot decrypt AES at all unless `cryptography` is
installed, and it was not. AES has been the default since Acrobat 7, so most
modern "secured" PDFs hit it.
"""

from __future__ import annotations

import pytest
from pypdf import PdfReader, PdfWriter

import merge


@pytest.fixture
def encrypted_pdf(tmp_path):
    """Make an encrypted PDF. An empty user_password means no password to open."""

    def make(name: str, pages: int = 2, user_password: str = "",
             algorithm: str = "AES-256") -> "object":
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=595, height=842)
        writer.encrypt(
            user_password=user_password,
            owner_password="owner-only",
            algorithm=algorithm,
        )
        path = tmp_path / name
        with open(path, "wb") as handle:
            writer.write(handle)
        return path

    return make


class TestDependencyIsPresent:
    def test_cryptography_is_importable(self):
        """Without it every AES-encrypted PDF is unreadable. pypdf calls it
        optional; for this tool it is not."""
        import cryptography  # noqa: F401

    @pytest.mark.parametrize("algorithm", ["AES-128", "AES-256", "RC4-128"])
    def test_pypdf_can_decrypt_each_algorithm(self, encrypted_pdf, algorithm):
        path = encrypted_pdf(f"enc-{algorithm}.pdf", algorithm=algorithm)
        reader = PdfReader(str(path))
        assert reader.is_encrypted
        assert reader.decrypt("")  # the empty-password case
        assert len(reader.pages) == 2


class TestSecuredButReadable:
    """The reported case: secured against editing, no password to read."""

    @pytest.mark.parametrize("algorithm", ["AES-128", "AES-256", "RC4-128"])
    def test_it_merges(self, encrypted_pdf, blank_pdf, tmp_path, monkeypatch, algorithm):
        monkeypatch.chdir(tmp_path)
        plain = blank_pdf("plain.pdf", 2)
        secured = encrypted_pdf("secured.pdf", pages=3, algorithm=algorithm)
        assert merge.main([str(plain), str(secured), "-o", "out.pdf", "--force"]) == 0
        assert len(PdfReader(str(tmp_path / "out.pdf")).pages) == 5

    def test_page_ranges_still_work_on_it(self, encrypted_pdf, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        secured = encrypted_pdf("secured.pdf", pages=6)
        assert merge.main([f"{secured}:2-4", "-o", "out.pdf", "--force"]) == 0
        assert len(PdfReader(str(tmp_path / "out.pdf")).pages) == 3

    def test_and_so_do_exclusions(self, encrypted_pdf, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        secured = encrypted_pdf("secured.pdf", pages=5)
        assert merge.main([f"{secured}:!3", "-o", "out.pdf", "--force"]) == 0
        assert len(PdfReader(str(tmp_path / "out.pdf")).pages) == 4

    def test_the_output_is_not_itself_encrypted(self, encrypted_pdf, tmp_path, monkeypatch):
        """A merged bundle should open normally even if a source was secured."""
        monkeypatch.chdir(tmp_path)
        secured = encrypted_pdf("secured.pdf", pages=2)
        merge.main([str(secured), "-o", "out.pdf", "--force"])
        assert PdfReader(str(tmp_path / "out.pdf")).is_encrypted is False


class TestGenuinelyPasswordProtected:
    def test_it_is_skipped_with_a_plain_reason(
        self, encrypted_pdf, tmp_path, monkeypatch, capsys
    ):
        """Not a stack trace and not a library error message."""
        monkeypatch.chdir(tmp_path)
        locked = encrypted_pdf("locked.pdf", user_password="letmein")
        merge.main([str(locked), "-o", "out.pdf", "--force"])
        out = capsys.readouterr().out
        assert "password protected" in out
        assert "cryptography" not in out, "the library error should not reach the user"

    def test_the_rest_of_the_merge_still_completes(
        self, encrypted_pdf, blank_pdf, tmp_path, monkeypatch
    ):
        """One locked exhibit must not cost you the whole bundle."""
        monkeypatch.chdir(tmp_path)
        plain = blank_pdf("plain.pdf", 3)
        locked = encrypted_pdf("locked.pdf", user_password="letmein")
        merge.main([str(plain), str(locked), "-o", "out.pdf", "--force"])
        assert len(PdfReader(str(tmp_path / "out.pdf")).pages) == 3


class TestNoticesCoverWhatIsShipped:
    """The guard promised in make_notices.py's own comment.

    Its component list is maintained by hand, so a newly bundled dependency would
    otherwise ship with no licence text and nothing would say so. cryptography
    arrived exactly that way.
    """

    def test_every_bundled_package_has_a_notice(self):
        from pathlib import Path

        internal = Path(merge.__file__).parent / "dist" / "PDF Page Merger" / "_internal"
        if not internal.is_dir():
            pytest.skip("no build to check; run packaging\\build.ps1 first")

        notices = (Path(merge.__file__).parent / "THIRD-PARTY-NOTICES.txt").read_text(
            encoding="utf-8", errors="replace"
        ).lower()

        # Top-level package directories that ship inside the build. .dist-info
        # directories are metadata about a package, not the package, and the
        # package itself is checked separately.
        ignore = {"_tk_data", "tcl8", "share", "lib2to3", "certifi"}
        shipped = {
            d.name
            for d in internal.iterdir()
            if d.is_dir()
            and not d.name.startswith("_")
            and not d.name.endswith((".dist-info", ".egg-info"))
            and d.name not in ignore
        }

        missing = sorted(name for name in shipped if name.lower() not in notices)
        assert not missing, (
            "bundled but absent from THIRD-PARTY-NOTICES.txt: "
            + ", ".join(missing)
            + " -- add them to COMPONENTS in packaging/make_notices.py"
        )
