# Building a signed installer

Turns this folder into `PDFPageMerger-1.0.0-Setup.exe`: a single installer that
carries its own copy of Python, pypdf and Pillow, so the machine it lands on
needs nothing installed.

```
packaging\
  build.ps1                 the whole build, in order
  merge_tool.spec           PyInstaller: the two programs
  installer.iss             Inno Setup: the installer
  make_icon.py              draws icon.ico
  New-TestCertificate.ps1   a throwaway certificate for testing the pipeline
```

## What you need first

| Tool | Why | Where |
|------|-----|-------|
| PyInstaller | bundles Python with the app | `python -m pip install pyinstaller` |
| Inno Setup 6 | builds the installer | <https://jrsoftware.org/isdl.php> |
| A code signing certificate | stops Windows warning users off | see below |

Signing itself needs nothing extra — `Set-AuthenticodeSignature` is part of
Windows. The Windows SDK and `signtool.exe` are not required. That holds for a
certificate in the Windows certificate store or a `.pfx`; the Azure route below
is the exception, and would need `signtool.exe` adding.

## Build it

```powershell
# no certificate yet - check the build works
.\packaging\build.ps1 -SkipSign

# with your certificate
.\packaging\build.ps1 -CertificateThumbprint A1B2C3...

# or from a .pfx file (it will ask for the password)
.\packaging\build.ps1 -PfxPath C:\keys\company.pfx
```

The result lands in `dist\installer\`.

Four steps run in a deliberate order: build the programs, **sign the programs**,
build the installer, **sign the installer**. Both signing steps matter. Signing
only the installer leaves the executables inside it unsigned, so the first thing
a user runs after installing is unsigned — which is exactly what SmartScreen and
corporate application-control policies object to.

## The licence page

Setup shows the licence terms and will not continue without acceptance.
`EULA.rtf` is **generated** from `..\LICENCE-TERMS.md` by `make_eula.py`, which
`build.ps1` runs before Inno Setup — so edit the Markdown and never the `.rtf`,
exactly as with `THIRD-PARTY-NOTICES.txt`. The build says so in yellow when the
regenerated file differs from what was committed.

The terms still have placeholders in them — entity name, registered address,
contact, privacy notice. `make_eula.py` lists them on every run. **A `-SkipSign`
build prints them and carries on; a signed build refuses**, because a signed
build is one going to a customer, and an accept page reading
"[LEGAL ENTITY NAME]" is not a contract.

To see the page as the customer will, without running setup, load the result
into the same control Inno displays it in:

```powershell
Add-Type -AssemblyName System.Windows.Forms
$rtb = New-Object System.Windows.Forms.RichTextBox
$rtb.Rtf = [System.IO.File]::ReadAllText("packaging\EULA.rtf")
$rtb.Text
```

## Testing the pipeline before you buy anything

```powershell
.\packaging\New-TestCertificate.ps1
.\packaging\build.ps1 -CertificateThumbprint <the thumbprint it prints>
```

This creates a self-signed certificate in your own certificate store and signs
with it. It proves every step works. **It does not make the software trusted** —
Windows still warns, because the certificate is not chained to a public
authority. Remove it afterwards with `.\packaging\New-TestCertificate.ps1 -Remove`.

## Getting a real certificate

This is the part that costs money and takes time, and there is no way around it.
There are two routes, and they trade money against work.

Whichever you choose, **`AppPublisher` in `installer.iss` must be the same
organisation name as the certificate subject**, or the installer claims one
publisher while its signature names another. The spec's `COMPANY` has to match
too, since it goes into both executables' version resource;
`TestTheTwoFilesAgree` asserts those two agree with each other, but nothing can
check them against a certificate you have not bought yet.

### Route 1 — a certificate from a CA

Works with `build.ps1` exactly as it stands.

- **Buy from a public certificate authority** — Sectigo, DigiCert, GlobalSign and
  their resellers. Expect roughly £200–£400 a year for a standard (OV)
  certificate, more for EV.
- **It arrives on hardware.** Since June 2023 the CA/Browser Forum has required
  the private keys for all publicly-trusted code signing certificates to live on
  a FIPS 140-2 Level 2 token or in a cloud HSM. You will be sent a USB token, or
  given a cloud signing service. You cannot simply download a `.pfx` any more.
  Where a token is involved, `Set-AuthenticodeSignature` can still use it once
  its driver exposes the certificate to the Windows certificate store; cloud
  services usually supply their own signing tool instead.
- **A token ties signing to one machine.** Whichever computer it is plugged into
  is the only one that can cut a release. Worth knowing before choosing.
- **Validation takes days.** The CA verifies your business exists — company
  registration, a verifiable phone number, sometimes a legal opinion letter. Sole
  traders can get certificates, but it is more work.

### Route 2 — Azure Artifact Signing

Formerly called Trusted Signing. Microsoft holds the key in their own HSM and you
sign over an API, so **there is no hardware token at all**. About **$9.99 a
month** on the Basic tier for up to 5,000 signatures, then $0.005 each — roughly
a quarter of what a CA certificate costs, and you can sign from anywhere.

Two things to check before committing to it:

- **Eligibility.** Individual developers are limited to the USA and Canada.
  *Organisations* cover a longer list including the UK and the EU, so a company
  is the route to use rather than a sole trader. There is a long-standing
  requirement of three or more years of verifiable tax history, and whether it
  still applies is genuinely unclear — the same Microsoft Q&A thread contains a
  Microsoft employee saying there is no minimum organisation age and a
  Microsoft-affiliated answer saying three years, and a vendor blog claims the
  rule was dropped in 2026. **Check the current prerequisites on Microsoft Learn,
  and confirm eligibility in the Azure portal before subscribing.** Onboarding
  either accepts the organisation or it does not, and asking costs nothing. Note
  the rename: search for "Azure Artifact Signing (formerly Trusted Signing)".
- **It needs the Windows SDK.** `build.ps1` supports this route, but it goes
  through `signtool.exe` with Microsoft's dlib provider rather than
  `Set-AuthenticodeSignature`, so the SDK has to be installed for it. The
  certificate route still needs neither. Install the provider with
  `nuget install Microsoft.Trusted.Signing.Client`, or drop it in
  `.tools\TrustedSigning\`, which is checked first — the same arrangement as
  Inno Setup, so the dependency travels with the project rather than with the
  machine.

### Signing with route 2

```powershell
az login   # DefaultAzureCredential is what the dlib authenticates with

.\packaging\build.ps1 -AzureSigningAccount mysigningaccount `
                       -AzureCertificateProfile myprofile `
                       -AzureEndpoint https://weu.codesigning.azure.net/
```

The endpoint is regional and the wrong one fails to authenticate rather than
redirecting. `signtool.exe` and the dlib are found automatically; override with
`-SignToolPath` and `-TrustedSigningDlib`. The timestamp authority defaults to
Microsoft's for this route, since theirs is the one the service requires, unless
`-TimestampUrl` says otherwise.

The two routes are mutually exclusive and the script refuses both at once.

### Which to choose

Route 2 is cheaper every year and removes the token, at the cost of installing
the Windows SDK. Route 1 needs nothing beyond Windows itself. Both sign the
programs and the installer, and both are refused if a customer-facing document
still carries a placeholder.

Confirm route 2 eligibility before deciding — it is free to find out, and the
answer may settle it for you.

### Standard (OV) versus Extended Validation (EV)

An OV certificate stops the "unknown publisher" warning, but **SmartScreen may
still warn until the file builds reputation** — that is a function of how many
people have downloaded and run it, and it clears over days or weeks. An EV
certificate gets SmartScreen reputation immediately, costs more, and always
requires hardware. If you are selling to firms whose IT will not tolerate any
warning on day one, EV is the one that avoids the awkward conversation.

### Always timestamp

`build.ps1` timestamps by default. Without a timestamp, every copy you have ever
shipped stops validating the moment the certificate expires. With one, the
signature stays valid long after. Change the server with `-TimestampUrl` if your
CA prefers its own.

## Deploying to a managed network

The installer accepts the usual Inno Setup switches, so IT can push it silently:

```
PDFPageMerger-1.0.0-Setup.exe /VERYSILENT /NORESTART /SUPPRESSMSGBOXES
```

It installs per-machine when run as administrator and per-user otherwise, so it
works without admin rights where that is required.

If a customer's IT department insists on **MSI** rather than an .exe — some
deployment tooling only accepts MSI — that needs the WiX Toolset and a different
script. Worth asking before assuming; plenty of environments take the .exe.

## Version numbers

Set the version in two places, and keep them the same:

- `merge_tool.spec` — `VERSION`
- `installer.iss` — `AppVersion`

`tests/test_packaging.py` enforces this, so a mismatch fails the test suite --
and therefore the build, which runs the suite first. It also checks the
application name and both executable names agree between the two files.

## Cutting a release someone else will receive

Everything below the line is what distinguishes a build you keep from a build you
hand over. Work through it in order.

**1. Decide the version and set it in both places.** `VERSION` in
`merge_tool.spec`, `AppVersion` in `installer.iss`. Patch for a fix, minor for a
feature. Never reuse a number someone has already had: when they report a
problem, the version is the only thing that tells you what they are running.

**2. Make sure the terms are complete.** `LICENCE-TERMS.md` must have no
remaining `[PLACEHOLDER]`. A signed build refuses while any remain, because an
agreement that does not name its licensor names nobody.

**3. Commit everything, then build signed.**

```powershell
git status                      # must be clean
.\packaging\build.ps1 -CertificateThumbprint <yours>
```

The build runs the tests, re-renders `EULA.rtf` from `LICENCE-TERMS.md`,
regenerates `THIRD-PARTY-NOTICES.txt`, and refuses on a test failure. If it tells
you either generated file changed, stop and commit the change -- what you are
about to send must match what is in version control.

**4. Check the signature really took.**

```powershell
Get-AuthenticodeSignature .\dist\installer\PDFPageMerger-<version>-Setup.exe |
  Select-Object Status, SignerCertificate, TimeStamperCertificate
```

`Status` should be `Valid`, and `TimeStamperCertificate` must not be empty --
without a timestamp the signature dies with the certificate.

**5. Record the checksum.**

```powershell
(Get-FileHash .\dist\installer\PDFPageMerger-<version>-Setup.exe -Algorithm SHA256).Hash
```

**6. Tag the commit**, so the artifact maps to source for ever:

```powershell
git tag -a v<version> -m "Release <version>"
git push origin v<version>
```

**7. Fill in the install note.** Copy `docs\customer-install-note.md` and
substitute `[VERSION]`, `[SIZE]`, the `[CHECKSUM]` from step 5, `[SEATS]` for this
customer, and `[YOUR CONTACT DETAILS]`. Do not blanket find-and-replace
`[NUMBER]` across the project: it means the company registration number in the
legal documents, and the install note deliberately uses `[SEATS]` instead so the
two cannot be confused. Remember e-mail will not carry an `.exe` -- use a link or a USB
stick, and send the checksum separately so their IT can verify it.

**8. Write down who got which version and when.** A one-line-per-customer text
file is enough. Without it, supporting two customers on different builds is
guesswork.

**Before the first paid release**, two things are still outstanding and neither is
a build step: a solicitor should read `LICENCE-TERMS.md`, and somebody should
confirm the Microsoft Visual C++ runtime redistribution terms cover shipping
`VCRUNTIME140.dll` the way this installer does.

## Publishing

Use the script. It is not a convenience -- publishing by hand now has a step that
must not be forgotten, and a procedure that depends on remembering a step will
one day publish a home address.

```powershell
.\packaging\publish.ps1 -Message "what changed"          # commits, shows the diff
.\packaging\publish.ps1 -Message "what changed" -Push    # and pushes
```

Without `-Push` it stops after committing locally and prints what it would send,
which is the point: look at the tree before it leaves.

### What is held back, and why

`packaging\not-published.txt` lists the files kept out of the public repository.
Today that is the licence terms, the privacy notice, and the `EULA.rtf` generated
from the terms.

They have to identify the contracting party, which means giving the company's
registered office. That address is on the Companies House register already, but
"findable on the register" and "indexed in a public git repository, in a history
that is awkward to scrub" are different kinds of exposure. The documents go to
customers with their order, which is where they are actually needed.

So a clone of the public repository has to work without them, and does:

- `installer.iss` flags those two files `skipifsourcedoesntexist`.
- `build.ps1` writes a placeholder licence page saying the terms are not included
  and the build must not be distributed -- Inno Setup has no way to omit the
  licence page, and a setup with no page at all would look finished.
- The same script **refuses to sign** such a build. Signing is what makes an
  installer distributable, so that is where the refusal belongs.
- The tests that read those documents skip, and only for paths on that list.
  `TestWhatIsNotPublished` asserts the list and the installer flags agree, so
  the flag cannot be used to silence a genuinely broken `Source:` path.

Both halves were verified by deleting the three files and running the suite and a
build: 213 passed, 18 skipped, and an installer was produced whose licence page
says what it is.

### The two things the script protects you from

**It never pushes `main`.** The public repository has its own history, starting
from a single squashed commit, and shares no ancestry with this one. The two
cannot be merged. The local branch `public-release` is that history -- keep it,
do not delete it. What the script does is make `public-release`'s *tree* match
`main` (`git restore --source=main`), without bringing any of `main`'s commits
with it, so the push is an ordinary fast-forward.

Never run `git push public main:main`. Git will refuse it as a non-fast-forward,
and refusing is correct -- forcing past it publishes this repository's entire
history rather than the squashed one. A rejected push to `public` is the safety
net working; stop and re-read this section rather than overriding it.

**It sweeps the tree for the address** before committing, and throws if it
finds it. Removing the listed files is necessary but not sufficient: the address
can arrive in a file nobody thought about. It did, the first time this ran -- a
test asserting the literal company number and street name, in a file that is
published.

Two sweeps, because one pattern cannot do both jobs:

- **Postcode-shaped text**, by regular expression. Needs no list, and finds a
  pasted address anywhere. Across the other 41 files there are no false
  positives.
- **The literal strings**, which `Get-DerivedPrivateStrings` works out from the
  held-back documents themselves -- the company number, and the registered
  office split into comma-separated fragments. They are read out of the source
  branch with `git show`, because by the time the sweep runs they have been
  deleted from the working tree.

Deriving rather than listing is what makes this survive a fresh clone. The
documents are the authority for what the address is, and this repository always
has them -- it is the only place publishing happens from. Fragments rather than
whole addresses, because a fragment still matches a reformatted version, which is
how an address usually escapes.

`packaging\private-strings.txt` is still read if it exists, for anything
derivation cannot see. It is gitignored, nothing depends on it, and there is
currently no need for one.

A leak is reported with the string that matched, so a false positive can be
diagnosed. If one ever appears, narrow the derivation deliberately rather than
deleting the check.

The remote named `public` points at the published repository; `origin` points at
this one. They are deliberately different names so neither is the default.

## What the installed copy does differently

Installed under `Program Files`, the program's own folder is read-only. The tool
notices and adapts on its own:

- merged files default to `Documents\PDF Page Merger\` instead of the tool's
  `output\` folder
- settings and presets go to `%APPDATA%\PDF Page Merger\settings.json`

Copy the folder somewhere writable instead and it stays self-contained, keeping
everything beside the program. Both arrangements work; neither needs configuring.
