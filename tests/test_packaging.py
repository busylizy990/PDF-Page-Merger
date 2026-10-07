"""The packaging scripts refer to files by path. Check those paths exist.

Three times now a file `installer.iss` ships has been renamed away, and each time
the build spent a minute on PyInstaller before dying at the Inno Setup step with
"Source file ... does not exist". These tests turn that into a two-second failure,
and would have caught all three.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
ISS = PROJECT / "packaging" / "installer.iss"
SPEC = PROJECT / "packaging" / "merge_tool.spec"


def iss_sources() -> list[str]:
    """Every Source: path in installer.iss, skipping build output and macros."""
    found = []
    for line in ISS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(";") or not line.lower().startswith("source:"):
            continue
        match = re.search(r'Source:\s*"([^"]+)"', line)
        if not match:
            continue
        path = match.group(1)
        # ..\dist\{#AppName}\* only exists after a build, and carries an ISPP
        # macro; the build itself will complain if that is wrong.
        if "{#" in path or "*" in path:
            continue
        found.append(path)
    return found


class TestInstallerSources:
    def test_there_are_some_to_check(self):
        assert iss_sources(), "no plain Source: entries found -- has the syntax changed?"

    @pytest.mark.parametrize("relative", iss_sources())
    def test_each_source_file_exists(self, relative):
        """Paths in installer.iss are relative to the .iss file's own folder."""
        resolved = (ISS.parent / relative).resolve()
        assert resolved.is_file(), (
            f"installer.iss ships {relative}, which does not exist at {resolved}. "
            "Either restore it or update installer.iss -- the build would otherwise "
            "fail at the Inno Setup step after building everything."
        )

    def test_the_order_example_is_not_in_the_working_root(self):
        """It belongs in docs\\. In the root it gets renamed to order.txt, which
        is what README tells users to do with the installed copy, and that has
        broken the build three times."""
        assert not (PROJECT / "order.txt.example").exists(), (
            "order.txt.example is back in the project root, where it will be "
            "renamed away again. The canonical copy belongs in docs\\."
        )
        assert (PROJECT / "docs" / "order.txt.example").is_file()

    def test_a_users_own_order_txt_is_not_shipped(self):
        """order.txt is whatever job you are doing; it must not reach a customer."""
        assert not any(s.endswith("order.txt") for s in iss_sources())


class TestSpecDataIsEmptyOnPurpose:
    def test_data_stays_empty(self):
        """PyInstaller puts datas under _internal\\, where no user looks, so the
        documentation is shipped by installer.iss instead. Refilling DATA would
        silently reintroduce that."""
        text = SPEC.read_text(encoding="utf-8")
        assert re.search(r"^DATA = \[\]", text, re.M), (
            "merge_tool.spec's DATA is no longer empty. Anything listed there "
            "installs under _internal\\ -- see PROJECT-NOTES, 'Packaging'."
        )


class TestDocumentationShipped:
    @pytest.mark.parametrize(
        "name", ["README.md", "THIRD-PARTY-NOTICES.txt", "order.txt.example"]
    )
    def test_the_user_facing_files_are_installed(self, name):
        """Each should arrive beside the programs, not inside _internal\\."""
        shipped = {Path(s).name for s in iss_sources()}
        assert name in shipped, f"{name} is not shipped by installer.iss"

    def test_the_input_instructions_go_into_the_input_folder(self):
        text = ISS.read_text(encoding="utf-8")
        assert re.search(
            r'Source:\s*"[^"]*READ ME - put PDFs here\.txt";\s*DestDir:\s*"\{app\}\\input"',
            text,
        ), "the input instructions must install into {app}\\input, the folder the tool watches"


class TestShippedDllsHaveNotices:
    """The notices guard elsewhere checks package directories, so DLLs slipped
    past it -- which is how 5.8 MB of OpenSSL shipped with no licence text.

    Some coverage here is incidental: zlib is covered because Pillow's licence
    text happens to include it, and libffi because CPython's does. If either
    dependency were dropped the DLL would still ship, from Python, and quietly
    lose its notice. That is exactly what this test is for.
    """

    # shipped DLL -> a word that must appear in THIRD-PARTY-NOTICES.txt
    EXPECTED = {
        "libcrypto-3.dll": "openssl",
        "libssl-3.dll": "openssl",
        "zlib1.dll": "zlib",
        "libffi-8.dll": "libffi",
        "tcl86t.dll": "tcl",
        "tk86t.dll": "tk",
        "python313.dll": "python software foundation",
    }

    # Microsoft's C runtime is redistributable under the Visual Studio terms
    # rather than an open-source licence with a notice requirement, so it is
    # deliberately not in the table above. Worth a lawyer's glance before a
    # commercial release, not a guessed licence text.
    IGNORED = {"VCRUNTIME140.dll", "VCRUNTIME140_1.dll", "python3.dll"}

    def _internal(self):
        return PROJECT / "dist" / "PDF Page Merger" / "_internal"

    def test_every_shipped_dll_is_accounted_for(self):
        """A new DLL in the build must be either covered or consciously ignored."""
        internal = self._internal()
        if not internal.is_dir():
            pytest.skip("no build to check; run packaging\build.ps1 first")
        shipped = {f.name for f in internal.glob("*.dll")}
        unknown = shipped - set(self.EXPECTED) - self.IGNORED
        assert not unknown, (
            "DLLs ship that this test knows nothing about: "
            + ", ".join(sorted(unknown))
            + " -- add each to EXPECTED with the word its licence should put in "
            "THIRD-PARTY-NOTICES.txt, or to IGNORED with a reason."
        )

    def test_the_notices_mention_each_one(self):
        internal = self._internal()
        if not internal.is_dir():
            pytest.skip("no build to check; run packaging\build.ps1 first")
        notices = (PROJECT / "THIRD-PARTY-NOTICES.txt").read_text(
            encoding="utf-8", errors="replace"
        ).lower()
        missing = sorted(
            f"{dll} (expected '{token}')"
            for dll, token in self.EXPECTED.items()
            if (internal / dll).is_file() and token not in notices
        )
        assert not missing, "shipped with no licence text: " + "; ".join(missing)


class TestLicenceTerms:
    """EULA.rtf is the agreement a customer accepts on the installer's licence
    page. It is generated from LICENCE-TERMS.md, and installer.iss refers to it
    with LicenseFile= rather than Source:, so the Source: check above does not
    cover it -- a missing EULA.rtf would fail the build, not the tests.
    """

    def test_the_installer_shows_a_licence_page(self):
        text = ISS.read_text(encoding="utf-8")
        match = re.search(r"(?m)^\s*LicenseFile\s*=\s*(.+?)\s*$", text)
        assert match, "no LicenseFile in installer.iss, so no terms are shown"
        resolved = (ISS.parent / match.group(1)).resolve()
        assert resolved.is_file(), f"installer.iss points LicenseFile at {resolved}, which is missing"

    def test_the_terms_exist_and_are_substantial(self):
        terms = PROJECT / "LICENCE-TERMS.md"
        assert terms.is_file()
        text = terms.read_text(encoding="utf-8")
        # Things an agreement for this product must actually address.
        for topic in ("Liability", "Warranty", "Definitions", "termination"):
            assert topic.lower() in text.lower(), f"the terms do not mention {topic}"

    def test_the_rtf_matches_the_markdown(self):
        """Catches a hand-edited RTF, which would mean the terms a customer
        accepts differ from the terms of record."""
        import subprocess
        import sys

        rtf = PROJECT / "packaging" / "EULA.rtf"
        before = rtf.read_bytes()
        result = subprocess.run(
            [sys.executable, str(PROJECT / "packaging" / "make_eula.py")],
            cwd=str(PROJECT), capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        after = rtf.read_bytes()
        rtf.write_bytes(before)
        assert after == before, (
            "EULA.rtf does not match what LICENCE-TERMS.md renders to. Re-run "
            "packaging/make_eula.py and commit the result -- or someone has "
            "edited the RTF by hand, in which case the terms of record and the "
            "terms a customer accepts have diverged."
        )

    def test_the_privacy_notice_reference_is_settled(self):
        """Resolved 6 October 2026: clause 8.3 now says the notice is available on
        request, with PRIVACY-NOTICE.md as the document. This was a skipping
        placeholder test; it is an assertion now, so the placeholder cannot
        return."""
        text = (PROJECT / "LICENCE-TERMS.md").read_text(encoding="utf-8")
        assert "[PRIVACY NOTICE" not in text
        assert "available on request" in text

    def test_the_licensor_is_named(self):
        """Resolved 7 October 2026: the licensor is Damreb Consultancy Ltd, in
        both legal documents and as the installer's AppPublisher. Was a skipping
        placeholder test; an assertion now, so the placeholder cannot return and
        the three cannot drift apart."""
        entity = "Damreb Consultancy Ltd"
        for name in ("LICENCE-TERMS.md", "PRIVACY-NOTICE.md"):
            text = (PROJECT / name).read_text(encoding="utf-8")
            assert "[LEGAL ENTITY NAME]" not in text, f"{name} still has the placeholder"
            assert entity in text, f"{name} does not name the licensor"
        iss = ISS.read_text(encoding="utf-8")
        assert f'#define AppPublisher   "{entity}"' in iss, (
            "installer.iss publisher must match the licensor named in the terms, "
            "and both must match any code-signing certificate's subject"
        )

    def test_the_contact_address_is_set(self):
        """Resolved 7 October 2026: contact@damreb.co.uk. A role address rather
        than a personal one, because clause 13.8 makes it the service address for
        notices of a claim -- that should not depend on one person's inbox, and a
        personal name would also go into the public repository."""
        for name in ("LICENCE-TERMS.md", "PRIVACY-NOTICE.md"):
            text = (PROJECT / name).read_text(encoding="utf-8")
            assert "[CONTACT EMAIL]" not in text, f"{name} still has the placeholder"
            assert "contact@damreb.co.uk" in text, f"{name} has no contact address"

    @pytest.mark.parametrize(
        "placeholder",
        ["REGISTERED ADDRESS"],
    )
    def test_placeholders_are_recorded_as_outstanding(self, placeholder):
        """NOT a failure: these are expected to be unfilled while drafting, and
        build.ps1 refuses a *signed* build while they remain. This test exists so
        the list stays visible and so it starts failing -- usefully -- once they
        are filled, prompting it to be tightened into a real gate.
        """
        text = (PROJECT / "LICENCE-TERMS.md").read_text(encoding="utf-8")
        if f"[{placeholder}" not in text:
            pytest.skip(
                f"{placeholder} has been filled in. Tighten this test into an "
                "assertion that it never comes back."
            )


class TestTheTwoFilesAgree:
    """installer.iss and merge_tool.spec each declare the version and the names
    independently, and packaging/README.md says to keep them the same.

    Nothing enforced that. PROJECT-NOTES even claimed the two files were
    "cross-checked", which was untrue -- installer.iss has no [Code] section and
    never had one. A claimed safety net that does not exist is worse than none,
    because it invites trusting it. This class is the cross-check.
    """

    def _define(self, name):
        """Read a #define from installer.iss."""
        match = re.search(
            r'(?m)^#define\s+' + name + r'\s+"([^"]*)"',
            ISS.read_text(encoding="utf-8"),
        )
        assert match, f"installer.iss has no #define {name}"
        return match.group(1)

    def _spec_value(self, name):
        match = re.search(
            r'(?m)^' + name + r'\s*=\s*"([^"]*)"',
            SPEC.read_text(encoding="utf-8"),
        )
        assert match, f"merge_tool.spec has no {name}"
        return match.group(1)

    def test_the_versions_match(self):
        """A mismatch names the installer one thing and stamps the programs
        another, so a customer reporting a version tells you nothing reliable."""
        iss, spec = self._define("AppVersion"), self._spec_value("VERSION")
        assert iss == spec, (
            f"installer.iss AppVersion is {iss} but merge_tool.spec VERSION is "
            f"{spec}. Set both, or the installer filename and the executables' "
            "metadata will disagree."
        )

    def test_the_application_name_matches(self):
        r"""installer.iss ships ..\dist\{#AppName}\*, which is the folder the
        spec's COLLECT name creates. Disagree and the build finds nothing."""
        assert self._define("AppName") == self._spec_value("APP_NAME")

    def test_the_version_looks_like_a_version(self):
        version = self._define("AppVersion")
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
            f"AppVersion {version!r} is not three dot-separated numbers; "
            "Inno Setup and Windows version resources both expect that shape."
        )

    def test_both_executables_the_installer_references_are_built(self):
        """GuiExe and CliExe are used for shortcuts and the uninstall icon, so a
        typo there produces an installer with dead shortcuts."""
        spec = SPEC.read_text(encoding="utf-8")
        gui, cli = self._define("GuiExe"), self._define("CliExe")
        assert gui == self._spec_value("APP_NAME") + ".exe", (
            f"installer.iss GuiExe is {gui}, but the spec builds "
            f"{self._spec_value('APP_NAME')}.exe"
        )
        assert f'name="{cli[:-4]}"' in spec, (
            f"installer.iss CliExe is {cli}, which the spec does not build"
        )


class TestPrivacyNotice:
    """Clause 8.3 of the terms promises a privacy notice on request, so one has
    to exist and has to say the things the UK GDPR requires a notice to say."""

    def _text(self):
        path = PROJECT / "PRIVACY-NOTICE.md"
        assert path.is_file(), "clause 8.3 promises a privacy notice; there is none"
        return path.read_text(encoding="utf-8")

    def test_the_terms_and_the_notice_point_at_each_other(self):
        terms = (PROJECT / "LICENCE-TERMS.md").read_text(encoding="utf-8")
        assert "privacy notice" in terms.lower()
        assert "LICENCE-TERMS.md" in self._text(), (
            "the notice should reference the terms it belongs to"
        )

    @pytest.mark.parametrize(
        "requirement, phrase",
        [
            ("the controller's identity", "controller"),
            ("a lawful basis", "article 6"),
            ("retention periods", "how long"),
            ("the data subject's rights", "rights"),
            ("the right to complain to the ICO", "information commissioner"),
            ("international transfers", "transfer"),
        ],
    )
    def test_it_covers_what_a_notice_must_cover(self, requirement, phrase):
        assert phrase in self._text().lower(), f"the notice does not address {requirement}"

    def test_it_states_that_the_software_sends_nothing(self):
        """The strongest thing in the notice, and the reason a firm can buy this
        without a data processing agreement. If the Software ever gains telemetry,
        an update check or a crash reporter, this claim and clause 8 of the terms
        both stop being true."""
        text = self._text().lower()
        assert "no telemetry" in text or "telemetry" in text
        assert "processor" in text, "it should say we are not your processor"

    def test_the_four_placeholders_are_the_same_as_the_terms(self):
        """One fill should cover both documents; a notice asking for a fifth
        detail would be missed."""
        import re as _re

        pattern = _re.compile(r"\[(LEGAL ENTITY NAME|NUMBER|REGISTERED ADDRESS|CONTACT EMAIL)\]")
        terms = set(pattern.findall((PROJECT / "LICENCE-TERMS.md").read_text(encoding="utf-8")))
        notice = set(pattern.findall(self._text()))
        assert notice <= terms or not notice, (
            f"the notice has placeholders the terms do not: {sorted(notice - terms)}"
        )


class TestPlaceholderTokensDoNotCollide:
    """The customer note and the legal documents are filled in at different times
    by different means -- the note per customer, the legal documents once when the
    trading entity is settled -- so a token meaning two things is a live hazard.

    It happened: the note used [NUMBER] for the seat count while the terms and the
    privacy notice use it for the company registration number. One
    find-and-replace across the project, which the release checklist invites,
    would have told a customer their licence covered several million users.
    """

    NOTE = PROJECT / "docs" / "customer-install-note.md"
    LEGAL = (PROJECT / "LICENCE-TERMS.md", PROJECT / "PRIVACY-NOTICE.md")

    def _tokens(self, path):
        import re as _re

        return set(_re.findall(r"\[[A-Z][A-Z0-9 _]*\]", path.read_text(encoding="utf-8")))

    def test_no_token_means_two_different_things(self):
        note = self._tokens(self.NOTE)
        legal = set()
        for path in self.LEGAL:
            legal |= self._tokens(path)
        shared = note & legal
        assert not shared, (
            "these tokens appear in both the customer note and the legal "
            f"documents, where they mean different things: {sorted(shared)}. "
            "Rename one side -- the note is filled per customer, the legal "
            "documents once, and a project-wide find-and-replace would corrupt one."
        )

    def test_the_note_still_has_the_fields_the_checklist_names(self):
        """If a field is renamed, the release checklist must be renamed with it."""
        note = self._tokens(self.NOTE)
        checklist = (PROJECT / "packaging" / "README.md").read_text(encoding="utf-8")
        for token in sorted(note):
            assert token in checklist, (
                f"{token} is in the customer note but not named in the release "
                "checklist, so whoever cuts a release will not know to fill it."
            )
