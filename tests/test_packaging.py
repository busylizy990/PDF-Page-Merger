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
NOT_PUBLISHED = PROJECT / "packaging" / "not-published.txt"

# The trading entity, settled 7 October 2026. Named here once because three
# places have to agree: both legal documents, installer.iss's AppPublisher,
# and the subject on whatever code-signing certificate is eventually bought.
ENTITY = "Damreb Consultancy Ltd"


def not_published() -> list[str]:
    """The paths deliberately kept out of the public repository.

    The licence terms and the privacy notice must identify the contracting party
    by registered office, which is a residential address; they are issued with
    each order instead. A clone of the public repository therefore has to build
    and test without them -- see packaging/not-published.txt.
    """
    if not NOT_PUBLISHED.is_file():
        return []
    return [
        line.strip()
        for line in NOT_PUBLISHED.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def unpublished_or_missing(relative: str) -> bool:
    """True when `relative` is absent *and* that absence is by design.

    A test may skip on this. It may not skip merely because a file is missing:
    that is how a lost document turns into a passing suite.
    """
    return relative in not_published() and not (PROJECT / relative).is_file()


def needs(relative: str):
    return pytest.mark.skipif(
        unpublished_or_missing(relative),
        reason=f"{relative} is not published -- see packaging/not-published.txt",
    )


def iss_source_lines() -> list[tuple[str, str]]:
    r"""Every (path, flags) from a plain Source: line, skipping build output.

    ..\dist\{#AppName}\* only exists after a build and carries an ISPP macro;
    the build itself will complain if that is wrong.
    """
    found = []
    for line in ISS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(";") or not line.lower().startswith("source:"):
            continue
        match = re.search(r'Source:\s*"([^"]+)"', line)
        if not match:
            continue
        path = match.group(1)
        if "{#" in path or "*" in path:
            continue
        flags = re.search(r"(?i)Flags:\s*([^;]*)", line)
        found.append((path, flags.group(1).strip() if flags else ""))
    return found


def iss_sources() -> list[str]:
    """The Source: paths that must exist for the build to work.

    Entries flagged skipifsourcedoesntexist are left out, because Inno Setup is
    entitled to skip them -- but only the not-published paths may carry that
    flag, which TestWhatIsNotPublished enforces. Weakening this check was the
    thing to get right: it exists because order.txt.example was renamed away
    three times and each time the build died at the Inno step after building
    everything else.
    """
    return [
        path
        for path, flags in iss_source_lines()
        if "skipifsourcedoesntexist" not in flags.lower()
    ]


class TestThePublisher:
    """AppPublisher is what Windows shows in the UAC prompt, in Programs and
    Features, and on the signature. It has to match the licensor named in the
    terms, and both have to match the certificate's subject, or a customer sees
    one name in the contract and another in the prompt."""

    def test_the_installer_names_the_publisher(self):
        iss = ISS.read_text(encoding="utf-8")
        assert f'#define AppPublisher   "{ENTITY}"' in iss, (
            f"installer.iss must set AppPublisher to {ENTITY} -- the licensor in "
            "the terms, and the subject any code-signing certificate must carry"
        )


class TestWhatIsNotPublished:
    """The licence terms and the privacy notice are issued with each order rather
    than published, because they must give the company's registered office and
    that is a residential address. packaging/not-published.txt is the list.

    This class exists to stop the mechanism being abused. Tests are allowed to
    skip for a file on that list, and installer.iss is allowed to flag one with
    skipifsourcedoesntexist. Neither is allowed for anything else -- otherwise
    "add the flag" becomes the way to silence a genuinely broken Source: path,
    which is the failure the Source: check was written for.
    """

    def test_the_list_exists_and_says_why(self):
        assert NOT_PUBLISHED.is_file(), (
            "packaging/not-published.txt is the single record of what is held "
            "back from the public repository; publish.ps1 and the tests both "
            "read it, and neither works without it"
        )
        text = NOT_PUBLISHED.read_text(encoding="utf-8")
        assert "#" in text, "the list should explain itself; a bare list of paths will not"
        assert not_published(), "the list names nothing"

    def test_a_signed_build_refuses_without_the_terms(self):
        """The one real protection, and the reason the skips above are safe.

        A document on the list could be *lost* rather than withheld, and a test
        that skips would hide it. Nothing in the tree can tell the difference --
        the public clone is a legitimate clone with the files absent, so an
        existence assertion here would be false in half the places it runs. (It
        was, briefly: that is how this test came to exist.)

        What can be checked is the gate that stops a build without the documents
        reaching anybody. build.ps1 writes a placeholder licence page when the
        terms are absent, and throws if it is also asked to sign.
        """
        build = (PROJECT / "packaging" / "build.ps1").read_text(encoding="utf-8")
        guard = build[build.index("Regenerating the licence agreement"):]
        guard = guard[: guard.index("Write-Step", 1)]
        assert "if (-not (Test-Path $termsFile))" in guard, (
            "build.ps1 no longer checks whether the terms are present before "
            "rendering the licence page"
        )
        assert "if ($signing)" in guard and "throw" in guard, (
            "build.ps1 must refuse to sign a build whose licence page is a "
            "placeholder. Signing is what makes an installer distributable, so "
            "it is the only place the refusal belongs -- and with it gone, the "
            "skips in this suite would let a lost document through to a customer. "
            "Note $signing, not $certificate: see TestTheTwoSigningRoutes."
        )

    def test_the_installer_flags_exactly_the_unpublished_files(self):
        flagged = {
            path.replace("\\", "/").lstrip("./")
            for path, flags in iss_source_lines()
            if "skipifsourcedoesntexist" in flags.lower()
        }
        expected = {p for p in not_published() if not p.startswith("packaging/")}
        assert flagged == expected, (
            f"installer.iss flags {sorted(flagged)} as optional, but the files "
            f"kept out of the public repository are {sorted(expected)}. Any other "
            "use of skipifsourcedoesntexist hides a build that would have failed."
        )


class TestTheTwoSigningRoutes:
    """build.ps1 can sign with a local certificate (Set-AuthenticodeSignature,
    no Windows SDK) or with Azure Artifact Signing (signtool plus Microsoft's
    dlib, key in their HSM, no local certificate at all).

    The second route is why these tests exist. Every gate in the script used to
    ask "is $certificate set" as shorthand for "is this build being signed", and
    on the Azure route that is never true -- so the placeholder scan, the
    missing-document refusal and the EULA guard would all have passed an
    Azure-signed build through while reporting success. That build is the one
    that goes to a customer.
    """

    BUILD = PROJECT / "packaging" / "build.ps1"

    def _text(self):
        return self.BUILD.read_text(encoding="utf-8")

    def test_no_gate_keys_off_the_certificate_object(self):
        """The invariant, and the bug this change nearly shipped.

        `if ($certificate)` is always false on the Azure route. Using it as a
        gate is not a style problem; it silently disables the gate for one of
        the two ways this project can produce a distributable build.
        """
        assert "if ($certificate)" not in self._text(), (
            "a gate in build.ps1 tests the certificate object. The Azure route "
            "has no certificate, so that gate does not run for Azure-signed "
            "builds -- which are exactly the builds that reach customers. Ask "
            "$signing instead; the certificate belongs only to the other route."
        )

    def test_signing_is_decided_once_for_both_routes(self):
        text = self._text()
        assert "$signing     = -not $SkipSign" in text, (
            "$signing should be set from -SkipSign alone, so that it means "
            "'this build is being signed' regardless of how"
        )
        assert "$azureRoute  = [bool]$AzureSigningAccount" in text

    def test_the_routes_cannot_both_apply(self):
        """Passing a thumbprint and an Azure account asks for two different
        signing mechanisms. Picking one silently would sign with whichever the
        code happened to check first."""
        text = self._text()
        assert "not both" in text and "different signing routes" in text, (
            "build.ps1 should refuse a certificate and an Azure account together"
        )

    def test_both_artifacts_are_signed_on_both_routes(self):
        """The ordering comment at the top of build.ps1 explains why: signing
        only the installer leaves the programs inside it unsigned, so the first
        thing a user runs after installing is unsigned. That has to hold for the
        Azure route too, not just the one it was written for."""
        text = self._text()
        assert text.count("Invoke-SignToolSigning -Paths") == 2, (
            "the Azure route must sign the programs and the installer, as the "
            "certificate route does -- two calls, not one"
        )
        assert text.count("Invoke-Signing -Paths") == 2

    def test_the_azure_route_uses_microsofts_timestamp_authority(self):
        """Azure Artifact Signing requires its own timestamp authority; the
        DigiCert default belongs to the certificate route. Without a timestamp
        every copy ever shipped stops validating when the certificate expires.
        """
        text = self._text()
        assert "timestamp.acs.microsoft.com" in text, (
            "the Azure route needs Microsoft's timestamp authority"
        )
        assert "$PSBoundParameters.ContainsKey('TimestampUrl')" in text, (
            "the Azure default must not override a -TimestampUrl the caller "
            "actually passed"
        )

    def test_the_publisher_is_checked_against_the_signature(self):
        """packaging/README.md says nothing can check AppPublisher against a
        certificate that has not been bought. True before signing -- but after
        signing the subject is there to compare, and a mismatch reaches the
        customer as one name in the terms and another in the UAC prompt."""
        text = self._text()
        assert "function Assert-PublisherMatches" in text
        assert "Assert-PublisherMatches -Path" in text, (
            "the publisher check is defined but never called"
        )
        assert "$check.Status -eq 'Valid'" in text, (
            "it must only throw on a Valid signature: a self-signed test "
            "certificate reads as UnknownError and will not carry the company "
            "name, and failing there would break the documented test workflow"
        )

    def test_the_metadata_file_is_cleaned_up(self):
        """It names the signing account, and it is written next to nothing in
        particular. A stray copy is the kind of file that gets committed."""
        text = self._text()
        assert "Remove-Item -LiteralPath $metadata" in text, (
            "the signtool metadata file should be deleted after signing"
        )
        assert "finally {" in text


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


@needs("LICENCE-TERMS.md")
class TestLicenceTerms:
    """EULA.rtf is the agreement a customer accepts on the installer's licence
    page. It is generated from LICENCE-TERMS.md, and installer.iss refers to it
    with LicenseFile= rather than Source:, so the Source: check above does not
    cover it -- a missing EULA.rtf would fail the build, not the tests.
    """

    def test_the_installer_shows_a_licence_page(self):
        """LicenseFile= has no skipifsourcedoesntexist equivalent, so build.ps1
        writes a placeholder EULA.rtf in a clone without the terms rather than
        letting Inno fail. This asserts the page is configured at all."""
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
        both legal documents. Was a skipping placeholder test; an assertion now,
        so the placeholder cannot return.

        The matching assertion about installer.iss lives in TestThePublisher,
        outside this class -- it is a check on the installer, and it should still
        run in a clone that has no licence documents."""
        for name in ("LICENCE-TERMS.md", "PRIVACY-NOTICE.md"):
            text = (PROJECT / name).read_text(encoding="utf-8")
            assert "[LEGAL ENTITY NAME]" not in text, f"{name} still has the placeholder"
            assert ENTITY in text, f"{name} does not name the licensor"

    def test_the_contact_address_is_set(self):
        """Resolved 7 October 2026: contact@damreb.co.uk. A role address rather
        than a personal one, because clause 13.8 makes it the service address for
        notices of a claim -- that should not depend on one person's inbox, and a
        personal name would also go into the public repository."""
        for name in ("LICENCE-TERMS.md", "PRIVACY-NOTICE.md"):
            text = (PROJECT / name).read_text(encoding="utf-8")
            assert "[CONTACT EMAIL]" not in text, f"{name} still has the placeholder"
            assert "contact@damreb.co.uk" in text, f"{name} has no contact address"

    def test_the_entity_details_are_set(self):
        """Resolved 7 October 2026: the company number and the registered office
        are filled in. This was the last skipping placeholder test, kept so that
        it would start failing once the details arrived and prompt its own
        tightening. It did, so here it is as a gate.

        It checks the *shape* and not the values, deliberately. This file is
        published; the documents are not, precisely because they carry the
        registered office. An assertion naming the address would put the address
        in the public repository through the back door -- which is exactly what
        the first version of this test did, and what the postcode sweep in
        publish.ps1 failed to catch, there being no postcode in a test file.

        Shape is also all this test was ever for: catching the placeholder coming
        back, not proof-reading the address.
        """
        for name in ("LICENCE-TERMS.md", "PRIVACY-NOTICE.md"):
            text = (PROJECT / name).read_text(encoding="utf-8")
            for token in ("[NUMBER]", "[REGISTERED ADDRESS]"):
                assert token not in text, f"{name} still has {token}"
            assert re.search(r"under number\s+\d{8}", text), (
                f"{name} should give an eight-digit company registration number"
            )
            office = re.search(r"registered office is at\s+(.+?)\n\n", text, re.S)
            assert office, f"{name} should give a registered office address"
            # Shape, not content: several lines of something with a number and
            # commas in it. Enough to catch an empty or token address, and it
            # names nothing.
            line = " ".join(office.group(1).split())
            assert len(line) >= 25 and "," in line and any(c.isdigit() for c in line), (
                f"{name} gives {len(line)} characters for the registered office, "
                "which does not look like an address"
            )
        terms = (PROJECT / "LICENCE-TERMS.md").read_text(encoding="utf-8")
        assert "a sole trader" not in terms, (
            "the licensor clause offered a company/sole-trader alternative while "
            "the trading entity was undecided. It is decided -- a company -- and "
            "an executed contract cannot offer the reader a choice of counterparty."
        )

    def test_the_email_provider_is_named(self):
        """Section 6 of the notice makes a specific claim about where mailbox data
        sits, which is only checkable if the provider is named. Naming it is also
        what a firm's compliance team asks for first.

        Zoho is not UK-hosted, so the notice keeps its transfer wording: zoho.eu
        stores in the EEA, which UK adequacy covers, but Zoho's group companies
        outside the EEA may access it. Storage needs no safeguard; that access
        does. If the mailbox ever moves provider, section 6 moves with it.
        """
        text = (PROJECT / "PRIVACY-NOTICE.md").read_text(encoding="utf-8")
        assert "[EMAIL HOST" not in text, "the email-host note is still unresolved"
        assert "Zoho" in text, "the notice does not name the email provider"
        assert "International Data Transfer Agreement" in text, (
            "the provider stores inside the EEA but allows group access from "
            "outside it, so the notice must still describe a transfer safeguard"
        )

    def test_neither_document_carries_drafting_notes(self):
        """Both documents now have no placeholders, so both are issuable, so
        neither should carry a checklist addressed to the licensor. build.ps1
        blocks a signed build on this phrase; this catches it at test time and in
        an unsigned build too."""
        for name in ("LICENCE-TERMS.md", "PRIVACY-NOTICE.md"):
            text = (PROJECT / name).read_text(encoding="utf-8")
            assert "delete before issuing" not in text, (
                f"{name} has a drafting-notes section. Anything in it that is "
                "still live belongs in BUSINESS-NOTES.md, which is not published "
                "and not handed to customers."
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

    def test_the_publisher_matches(self):
        """The spec stamps CompanyName into both executables' version resource,
        and installer.iss writes AppPublisher into the installer's. Disagree, and
        a customer sees one name in the UAC prompt and another in Properties --
        and only one of them can match a code-signing certificate's subject."""
        iss, spec = self._define("AppPublisher"), self._spec_value("COMPANY")
        assert iss == spec, (
            f"installer.iss AppPublisher is {iss!r} but merge_tool.spec COMPANY "
            f"is {spec!r}. Both are shown to the customer, and both have to "
            "match the certificate."
        )

    def test_both_executables_get_a_version_resource(self):
        """The defect this guards against: VERSION was declared in the spec from
        the first build and never passed to EXE(), so both programs shipped with
        Properties -> Details blank for a week. The installer looked fine, because
        Inno Setup writes its own metadata -- which is exactly why nobody noticed.

        A test comparing the constants would not have caught it. This one checks
        the constants are actually *used*.
        """
        spec = SPEC.read_text(encoding="utf-8")
        assert spec.count("version=version_resource(") == 2, (
            "both EXE() calls must pass version=version_resource(...). Without "
            "it the programs ship with no CompanyName, ProductName or "
            "FileVersion, which is what a firm's IT inventories them by."
        )
        for field in ("CompanyName", "ProductName", "FileVersion", "ProductVersion"):
            assert f'StringStruct("{field}"' in spec, (
                f"the version resource does not set {field}"
            )
        # The resource must be built from the constants, not from literals that
        # can drift away from them.
        for constant in ("COMPANY", "APP_NAME", "VERSION", "COPYRIGHT"):
            assert f", {constant})" in spec, (
                f"the version resource should use {constant} rather than "
                "repeating its value"
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


@needs("PRIVACY-NOTICE.md")
class TestPrivacyNotice:
    """Clause 8.3 of the terms promises a privacy notice on request, so one has
    to exist and has to say the things the UK GDPR requires a notice to say."""

    def _text(self):
        path = PROJECT / "PRIVACY-NOTICE.md"
        assert path.is_file(), "clause 8.3 promises a privacy notice; there is none"
        return path.read_text(encoding="utf-8")

    @needs("LICENCE-TERMS.md")
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

        if unpublished_or_missing("LICENCE-TERMS.md"):
            pytest.skip("LICENCE-TERMS.md is not published -- nothing to compare against")
        pattern = _re.compile(r"\[(LEGAL ENTITY NAME|NUMBER|REGISTERED ADDRESS|CONTACT EMAIL)\]")
        terms = set(pattern.findall((PROJECT / "LICENCE-TERMS.md").read_text(encoding="utf-8")))
        notice = set(pattern.findall(self._text()))
        assert notice <= terms or not notice, (
            f"the notice has placeholders the terms do not: {sorted(notice - terms)}"
        )


class TestTheTesterNote:
    """docs/tester-note.md goes to friends, family and anyone else trying the
    thing informally. Unlike the customer note it is sent ad hoc, with no
    release checklist in front of the sender and no build gate behind it, so it
    has to be correct as it stands.
    """

    NOTE = PROJECT / "docs" / "tester-note.md"

    def _text(self):
        assert self.NOTE.is_file(), "docs/tester-note.md is missing"
        return self.NOTE.read_text(encoding="utf-8")

    def test_it_has_nothing_to_fill_in(self):
        """The customer note's placeholders are caught by build.ps1 before a
        signed build. Nothing stands behind this one, so an unfilled token would
        simply go out."""
        import re as _re

        tokens = sorted(set(_re.findall(r"\[[A-Z][A-Z0-9 _]{2,}\]", self._text())))
        assert not tokens, (
            f"the tester note has placeholders: {tokens}. It is sent by hand "
            "with no gate behind it, so it must not need filling in."
        )

    def test_the_html_matches_the_markdown(self):
        """The page is what actually gets handed over -- on a USB stick, usually
        -- so a stale render reaches a tester while the repository looks right.

        Compared in memory rather than by re-running the script and restoring
        the file, as the EULA test does: there is no reason for a test to write
        to the working tree when the renderer can simply be imported, and a test
        that restores a file it overwrote is one interrupted run away from
        leaving the wrong content on disk.
        """
        import importlib.util

        script = PROJECT / "packaging" / "make_tester_html.py"
        assert script.is_file(), "packaging/make_tester_html.py is missing"
        page = PROJECT / "docs" / "tester-note.html"
        assert page.is_file(), (
            "docs/tester-note.html is missing. Run "
            "packaging/make_tester_html.py and commit it -- the committed page "
            "is the one that gets copied to a stick."
        )

        spec = importlib.util.spec_from_file_location("make_tester_html", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        expected = module.render(self._text())
        actual = page.read_text(encoding="utf-8")
        assert actual == expected, (
            "docs/tester-note.html does not match what tester-note.md renders "
            "to. Re-run packaging/make_tester_html.py and commit the result -- "
            "or someone edited the HTML by hand, in which case the note of "
            "record and the note a tester reads have diverged."
        )

    def test_the_html_needs_nothing_external(self):
        """It is opened from a USB stick, on someone else's machine, possibly
        with no network. A linked stylesheet or a web font would render the page
        wrong in exactly the situation it exists for."""
        page = (PROJECT / "docs" / "tester-note.html")
        if not page.is_file():
            pytest.skip("covered by test_the_html_matches_the_markdown")
        text = page.read_text(encoding="utf-8")
        for pattern in ("<link", "<script", "http://", "https://", "@import"):
            assert pattern not in text, (
                f"the tester page references {pattern!r}. It has to render from "
                "removable media with no network, so everything must be inline."
            )

    def test_it_warns_about_smart_app_control(self):
        """This paragraph stops a tester permanently disabling a Windows
        security feature to help with a favour -- Smart App Control cannot be
        re-enabled without reinstalling Windows. It is the sort of long caveat
        that gets trimmed for brevity later."""
        text = self._text().lower()
        assert "smart app control" in text, (
            "the tester note must warn about Smart App Control, which blocks "
            "unsigned installers outright on recent clean Windows 11 installs"
        )
        assert "reinstalling" in text, (
            "it must say why not to turn it off: Windows will not let you turn "
            "it back on without reinstalling the operating system"
        )

    def test_it_explains_the_unsigned_warning(self):
        """A tester who was not told to expect "Publisher: Unknown" is a tester
        who reasonably refuses, and that is a wasted favour rather than a
        result."""
        text = self._text()
        assert "Unknown" in text and "certificate" in text, (
            "it should say the publisher will read Unknown and why -- no "
            "certificate has been bought yet"
        )

    def test_it_keeps_the_claim_that_nothing_is_uploaded(self):
        """The same claim as clause 8 of the terms and section 2 of the privacy
        notice. If the Software ever gains telemetry or an update check, this
        has to change with them."""
        text = self._text().lower()
        assert "does not upload" in text
        assert "no internet connection" in text


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
        """An absent legal document contributes no tokens.

        That is right rather than convenient: with the document absent there is
        no second meaning for a token to collide with, and the customer note --
        which is the half that is always here -- is still checked against
        whatever legal documents this clone does carry."""
        import re as _re

        if not path.is_file():
            return set()
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
