# Project notes

Written 30 September 2026, as a record of how this tool was built and why, so the
chat it came from can be deleted without losing anything.

[README.md](README.md) is the user guide — how to run it, every option, the page
range syntax. **This file is the other half:** the decisions behind the design,
the bugs that were found the hard way, what is true about *this machine*, and
what is still open. Read this before changing anything non-trivial.

---

## What it is

A reusable document merger. You give it PDFs, images, Word documents and
spreadsheets, in an order you control, optionally picking or removing pages from
each, and it produces one PDF — with an optional contents page and page
numbering.

Three ways in, one engine underneath:

| | |
|---|---|
| **Window** | `Merge GUI.bat` — drag files on, reorder, press Merge |
| **Folder** | drop files in `input\`, double-click `Merge.bat` |
| **Command line** | `python merge.py ...` — scriptable, explicit |

## The files

```
merge.py                  the engine and the command line (~1,500 lines)
merge_gui.pyw             the window
Merge GUI.bat             launcher for the window
Merge.bat                 launcher for the input\ folder
docs\order.txt.example    the canonical example, kept out of the working root
                          because it kept being renamed away; installer.iss
                          ships it to {app}, where a user copies it
input\, output\           the folder workflow
docs\gui.png              screenshot used by README.md
packaging\                the installer build (see packaging\README.md)
settings.json             created on first use by the window; not in version control
.gitignore                keeps settings.json, the input\ drop box, build output
                          and any signing certificates out of the repository
requirements-build.txt    the pinned build environment
tests\                    pytest suite; build.ps1 runs it before building
pytest.ini                test configuration
THIRD-PARTY-NOTICES.txt   generated; shipped to {app}. See packaging\make_notices.py
LICENCE-TERMS.md          the terms the program is sold under; the source of
                          truth for packaging\EULA.rtf, which the installer
                          shows on an accept/decline page. Edit this, not the
                          .rtf. See packaging\make_eula.py
docs\customer-install-note.md  template to send with the installer
.python\                  this project's own Python; not in version control
.tools\InnoSetup\         portable Inno Setup; not in version control either
```

### The build environment

**`.python\` is this project's own Python 3.13.13, and the separation is
deliberate — do not "simplify" it back to the shared interpreter.**

Rebuild it from `requirements-build.txt`; it holds pypdf, Pillow and PyInstaller
and nothing else. The interpreter that `python` on `PATH` resolves to is **not a
venv** despite sitting in a folder named `.venv` — it is a standalone install
whose `site-packages` is shared with an unrelated project, which is how reportlab
and pypdfium2 arrived here uninvited.

Three reasons this project does not build against it:

- **Licensing.** That interpreter has **PyMuPDF installed, which is AGPL-3.0.**
  PyInstaller only bundles what is imported, so it would not ship today — but one
  hook or `collect_all` would, into a product intended for sale. An environment
  that *cannot* contain AGPL code is worth more than one that probably will not
  ship it. Confirmed absent from `dist\`.
- **Reproducibility.** An installer should not be built against an environment
  another project mutates without telling you.
- **Size.** cv2 (112 MB), playwright (106 MB) and numpy (31 MB) are all
  candidates for inclusion there. The build comes out at 42 MB.

It was made by copying the standalone install and leaving its packages behind
(`robocopy ... /XD Lib\site-packages`), because this machine has no other Python
— the `py` launcher reports "No installed Pythons found!" and `python` on `PATH`
is the shared one. Verified genuinely independent: `sys.prefix` is inside the
project, no `sys.path` entry points outside it, and tkinter, ssl, sqlite3, lzma
and ctypes all import. **That shared interpreter could be deleted without
breaking the build.**

It pinned **pypdf 6.19.0 and Pillow 12.3.0**, newer than the 6.13.2 and 12.2.0 the
original testing used. The full merge path was re-verified on them.

**Inno Setup lives in `.tools\InnoSetup\` on the same principle.** Version 6.7.3,
installed from the official `innosetup-6.7.3.exe` with **`/PORTABLE=1`**, which
needs no administrator rights and writes nothing to the registry or
`Program Files` — worth knowing, because this account is not an administrator and
a normal install would stop for a UAC prompt. The download was checked against
the SHA256 in winget's manifest and its Authenticode signature (Pyrsys B.V.)
before being run. `ISPPBuiltins.iss` is present, which matters: `installer.iss`
uses `#define`, so it needs the preprocessor, not just the compiler.

`build.ps1` finds both tools itself — `Find-Python` and `Find-InnoSetup` each
prefer the project's copy and fall back to `PATH` and `Program Files`, so the
script still works on a machine that has them installed normally. Before this it
called bare `python`, which here resolves to the shared interpreter that has
no PyInstaller, so the script could not have worked at all.

Both `.bat` launchers prefer `.python\` and fall back to `PATH` only when it is
absent, so a copy of this folder sent to someone else still works. Before this
they took whatever `PATH` offered, which on this machine is the shared
interpreter — the project had its own Python but was not using it. Proven by
running `Merge.bat` with that interpreter stripped from `PATH`, where no `python`
resolves at all: it merged anyway.

Under git since 30 September 2026 — one initial commit holding everything above,
on `master`, **no remote**, so this is protection against bad edits and not
against losing the drive. Author identity is set per-repository, not globally.

---

## Design decisions worth keeping

**One engine, not two.** The window builds the same command line the terminal
takes and calls `merge.main()` directly — you can see the exact command echoed in
its log. `build_parser()` exists so the GUI and CLI share one set of defaults and
cannot drift apart. If you add a feature to `merge.py`, the window can expose it
by adding one argument to `build_argv()`.

**Nothing reads your documents.** The merger copies page objects between files.
It never extracts text or logs content — only file names and page counts. That is
a deliberate property worth preserving, and it is the honest basis for the
"nothing is uploaded" selling point.

**Keep-lists versus exclusions don't mix.** `file.pdf:1-3,7` says what to keep
(and so also reorders and repeats); `file.pdf:!7` says what to drop (and always
preserves original order). Allowing both in one spec reads fine but makes the
semantics ambiguous — does the exclusion apply to the whole file or the preceding
range? — and buys nothing you cannot already express. Keep them separate.

**Images match the document's page size.** Image pages take the size of the PDF
pages they are merged with, so a bundle is one consistent size throughout. The
most common size wins when sources disagree. In `match` mode a landscape image is
fitted inside the document's page rather than turning the sheet sideways, because
turning it would defeat the matching; the fixed sizes (`letter`, `a4`, `legal`)
do auto-rotate.

**The index settles its own length first.** A contents page shifts every page
after it, including the numbers printed on itself. `index_page_count()` resolves
that before laying out. Verified against a 2-page index.

**Text is drawn by hand.** pypdf cannot draw text and reportlab is deliberately
not a dependency, so `text_overlay()` writes PDF source directly — real cross-reference
table and all — using Helvetica, one of the 14 fonts every reader has. Nothing is
embedded; index pages cost about a kilobyte. Right-aligned page numbers are exact
because every digit in Helvetica is 556 units wide.

**There is a test suite, and the build will not run without it passing.**
153 tests, about a second and a half: `.python\python.exe -m pytest`. They cover
page specs including the keep/drop distinction and the Windows-path colon case,
the index settling its own page count, stamping at all six positions with Bates
formats and offsets, image page-size matching and the auto-rotate difference
between `match` and the fixed sizes, bookmarks surviving index insertion,
`settings.json` corruption, and whole merges through `main()`.

`build.ps1` runs them before PyInstaller and refuses to build on failure, with
`-SkipTests` as a loud override. Verified by planting a failing test: the build
aborted before PyInstaller started.

Two things worth knowing. The writability tests were checked against the *old*
code — reverting `writable_output_dir` to its `os.access` version makes three of
them fail, so they genuinely pin that bug rather than merely passing. And the
suite found a new one on its first run: `load_settings` read `settings.json` as
plain utf-8, so a byte-order mark — which Notepad can add and Windows
PowerShell's `Out-File -Encoding utf8` always adds — made `json.loads` raise and
silently discarded every saved preference. `order.txt` and the Office result file
were already read as utf-8-sig; this was the one place that was missed.

**Third-party notices are generated by the build, not written or remembered.**
`packaging\make_notices.py` reads the licence texts out of `.python\` and
assembles `THIRD-PARTY-NOTICES.txt`, so what ships is exactly what is installed
rather than something transcribed and left to rot. **`build.ps1` runs it every
time**, because a generated file that depends on someone remembering to refresh it
will eventually describe versions that are no longer in the box — and accuracy is
the entire point of a licence notice. If the regenerated file differs from the
committed one the build says so in yellow and carries on, so the change is noticed
and can be committed rather than silently shipped or silently lost. Verified both
ways: a correct file reports "notices unchanged", and a deliberately corrupted one
was detected and rewritten.
It covers the five components actually distributed — CPython (PSF), pypdf
(BSD-3), Pillow (MIT-CMU, whose text also covers the image codecs Pillow bundles),
Tcl/Tk, and PyInstaller's bootloader (GPL-2.0 **with** the exception that permits
bundling proprietary applications, which is why this program is not itself GPL).
It deliberately omits setuptools, pip, altgraph, pefile, packaging and
pywin32-ctypes: those are build-time only, verified absent from `dist\`. Note
pypdf looks absent from `dist\` too, because being pure Python it is compiled
into the `PYZ` archive inside each `.exe` — it is distributed, and its notice is
required.

**A password is never put on the command line by the window.** `merge.main()`
takes a `passwords` keyword for callers in the same process, which is how the
window passes them, because the window echoes the exact command line it builds
into its log -- and argv is readable by anything that can list processes. The
command line keeps `--password` for people who want it, but `--password` with no
value prompts instead, which is the form worth recommending. `--password-file`
covers scripts.

Passwords are also deliberately absent from `PRESET_FIELDS`, so they cannot reach
`settings.json`, and `unlock()` swallows pypdf's exception rather than printing
it, because that text can contain the password. Four tests assert the password
does not appear in stdout, stderr, the merged PDF, or `build_argv`.

Not done as a per-file suffix: `file.pdf:letmein` would collide with the
page-spec syntax, and silently -- `RANGE_RE` would reject it and the whole token
would be taken as a filename.

**The customer-facing documents are filled in at two different times, so their
placeholders must not share tokens.** `docs\customer-install-note.md` is filled
per customer; `LICENCE-TERMS.md` and `PRIVACY-NOTICE.md` are filled once, when the
trading entity is settled. The note used `[NUMBER]` for the seat count while both
legal documents use it for the company registration number -- so the
find-and-replace the release checklist invites would have told a customer their
licence covered several million users. The note now uses `[SEATS]`, and a test
asserts no token appears on both sides, plus that every token in the note is named
in the release checklist so a renamed field cannot be silently left unfilled.

The installer ships both legal documents, so clause 8.3's reference to
`PRIVACY-NOTICE.md` resolves for a customer rather than dangling, and the note
tells a compliance team the notice is there and what the load-bearing part of it
says.

**OpenSSL ships and needed its own notice.** `libcrypto-3.dll` and
`libssl-3.dll`, 5.8 MB of Apache-2.0 code, come with the bundled Python for its
`ssl` and `hashlib` modules -- and CPython's own `LICENSE.txt` does not mention
OpenSSL at all. The notices guard only looked at package *directories*, so DLLs
walked straight past it. Fixed: an OpenSSL entry whose version (3.0.19) and
copyright line are read from the shipped DLLs' own version resource, with the
Apache-2.0 text committed under `packaging\licenses\` rather than depending on
cryptography's metadata still being present.

Two others turned out covered by accident: `zlib1.dll` because Pillow's licence
text happens to include zlib's, and `libffi-8.dll` because CPython's includes
libffi's. Drop either dependency and the DLL would still ship, from Python, and
silently lose its notice -- so there is now a test mapping every shipped DLL to a
word that must appear in the notices, which fails on an unrecognised DLL too.
`VCRUNTIME140.dll` is deliberately excluded: it is redistributable under the
Visual Studio terms rather than an open-source licence with a notice obligation,
and that is worth a lawyer's glance before a commercial release rather than a
guessed licence text.

**There is no Explorer right-click menu, on purpose.** One was written and
dropped unused on 2 October 2026, before ever being installed. Three reasons, in
increasing order of importance. It registered only 4 of the 25 supported
extensions, so right-clicking a `.png` did nothing while the tickbox promised
images were covered. A multi-file selection would have opened one window per file,
because Windows invokes a `"%1"` verb once per item — and `MultiSelectModel` is
not a real fix, since Windows caps how many files reach a single invocation, so a
large selection still fragments; doing it properly needs a single-instance app
with inter-process forwarding, which is new failure modes in an otherwise simple
program. Most of all, it hands files over in **Explorer's sort order**, which is
precisely the control a bundle assembler must keep — the opposite of what this
tool is for. If a quick path is ever wanted, a shortcut in `shell:sendto` gives
the same convenience with correct multi-file behaviour, no registry writes, no
per-extension list and nothing to uninstall. The installer now has no `[Registry]`
section at all; verified by the compiler parsing none.

**A preset covers finishing only** — never which files go in or where output
lands, since those change every job. Editing any option clears the preset name so
the box never claims a preset that no longer describes what is set.

**Settings live beside the tool** so they travel when the folder is copied,
falling back to `%APPDATA%` when the folder is read-only (the installed case).

**Drag-and-drop uses the Windows shell directly** (`WM_DROPFILES` via ctypes)
rather than `tkinterdnd2`. No package to install, which matters if this is ever
distributed — a customer should not have to `pip install` anything.

---

## Bugs found and fixed — the expensive knowledge

These were all found by testing, not by reading the code. If you refactor, these
are the traps.

### Office automation

- **`capture_output=True` deadlocks the merge.** Office inherits the pipe handle
  PowerShell is given and keeps it open, so `subprocess.run` blocks draining a
  pipe that never closes — even after its timeout kills PowerShell. Results come
  back through a *file* instead; output goes to `DEVNULL`. Do not "helpfully"
  restore output capture here.
- **Excel suspends its object model after an export** (`0x800AC472`). If `Close`
  fails and the failure is swallowed, the workbook stays open and poisons every
  later call. The close retries.
- **Killing Office creates crash-recovery entries.** Each killed Excel registers a
  document under `HKCU\...\Office\16.0\Excel\Resiliency\DocumentRecovery`; enough
  of them and Excel greets every new instance with a recovery pane that blocks
  COM automation entirely. Workbooks now get `EnableAutoRecover = $false`, and
  killing is a last resort after a 5-second grace period.
- **A running Office session is never closed.** Asking for Excel attaches to the
  copy the user already has open, so the script records whether it was already
  running and only quits an instance it started.
- **LibreOffice must run in its own profile.** `soffice --convert-to` otherwise
  hands the job to a copy the user already has open: it can silently convert
  nothing, disturb their session, and leave locks on input files (it did exactly
  that during the session). Every conversion now passes
  `-env:UserInstallation=<temp profile>`.
- **A COM message filter is registered** to handle `RPC_E_CALL_REJECTED`, bounded
  to 10 seconds so a genuinely wedged app fails fast into the LibreOffice
  fallback instead of hanging.

### Windows API

- **Declare ctypes signatures.** `GetParent` with no `restype` truncates a 64-bit
  window handle to 32 bits. It happened to work because the handle was small.
  Every Win32 function used now declares `restype`/`argtypes`.
- **The drop must register against the real top-level window.** During
  `__init__`, Tk has not created it yet, so `GetParent` returns 0 and you silently
  subclass the child frame — drops then do nothing. Setup is deferred until the
  window is realised.
- **Keep references to the callback and previous window proc.** If either is
  garbage collected, Windows calls into freed memory.
- **`os.access(folder, os.W_OK)` lies about directories on Windows.** It reflects
  the read-only *attribute* and ignores ACLs, so it reports
  `C:\Program Files\PDF Page Merger` as writable. Both fallbacks written for the
  installed case therefore never ran. `writable_output_dir()` handed back the
  Program Files `output\` and `mkdir` raised an unhandled `PermissionError`, so
  **the installed command line crashed** on any merge without `-o`; and
  `settings_path()` kept returning the read-only location, so the window silently
  never saved settings and its `%APPDATA%` fallback was dead code. Found on
  2 October 2026 by installing to `Program Files` and running a merge — the one
  case this note had claimed was handled, which is a reminder that an untested
  fallback is a guess. Both now call `merge.can_write_dir()`, which creates the
  folder and writes a probe file, because on Windows the only way to know whether
  you can write somewhere is to write there.

### Tkinter

- **Cancel pending `after` callbacks on teardown**, bound to `<Destroy>` so any
  path is covered. Otherwise Tk fires the log poller at a dead widget — invisible
  under `pythonw`, where there is no console to show it.
- `_refresh()` resets the status line, so anything reporting an outcome must run
  *after* it.

### Frozen / installed builds

- `__file__` points inside a temp unpack folder once packaged, so `BASE` uses
  `sys.executable` when `sys.frozen` is set. Without this, an installed copy looks
  for `input\` in a temp directory.
- Installed under `Program Files` the tool's folders are read-only:
  `writable_output_dir()` falls back to `Documents\PDF Page Merger\`.

### Data handling

- `settings.json` is untrusted input — it is hand-editable and travels between
  machines. A malformed `presets` value (a string or list where an object was
  expected) **crashed the window on startup** before it could draw anything.
  Every shape is now handled: bad types fall back to built-ins, individual bad
  presets are dropped, junk fields stripped.

### Packaging

- **The shipped documentation does not land beside the executables.** PyInstaller 6
  places everything in `datas` under `_internal\`, so the three files
  `merge_tool.spec` ships — `README.md`, `order.txt.example` and
  `input\READ ME - put PDFs here.txt` — install to `_internal\`, where no user
  will look. The spec's own comment says they are "shipped alongside the
  executables, so the installed copy explains itself", and that intent is not met.
  Worse for the third one: when frozen, `BASE` is the folder holding the `.exe`,
  so the folder the tool actually watches is `<app>\input`, which
  `merge.py` creates empty on first use — while the file explaining what to put
  there sits in `_internal\input\`. Found by inspecting a real install on
  2 October 2026. **Fixed the same day:** the spec's `DATA` is now empty, with a
  comment saying why, and `installer.iss` copies the three files from the source
  tree straight to `{app}` and `{app}\input`. Placing the third one there also
  creates the `input\` folder, so a fresh install explains itself before the first
  run instead of creating that folder empty. Confirmed by the compiler's own log
  listing all three as packaged; the destinations are declarative and get their
  real proof on the next install. Note the trade: `dist\PDF Page Merger\` on its
  own no longer carries any documentation, which is fine because the installer is
  the deliverable, but worth knowing if you ever hand someone that folder.

### The build script

- **Redirecting the build's streams used to abort the build.** Windows PowerShell
  5.1 wraps a native command's stderr in `ErrorRecord`s as soon as the caller
  redirects, and PyInstaller writes all of its ordinary INFO output to stderr —
  so `build.ps1 -SkipSign 2>&1 | Tee-Object build.log`, which is just asking for
  a build log, died at the first INFO line because of the script's
  `$ErrorActionPreference = 'Stop'`. Native calls now go through
  `Invoke-Native`, which drops to `Continue` for the duration; the exit-code
  checks that were already there do the real work. Verified by running that
  exact pipeline: 1,223 lines captured, build intact.
- **`Invoke-Signing` treated an untrusted certificate as a signing failure.**
  `Set-AuthenticodeSignature`'s `Status` says whether the certificate's *chain is
  trusted on this machine*, not whether the signature was written — a self-signed
  certificate always comes back `UnknownError` even though the file is correctly
  signed and timestamped. The function demanded `Valid`, so it threw after
  signing the first executable, leaving `pdfmerge.exe` unsigned. That made the
  workflow `New-TestCertificate.ps1` *prints for you* impossible to run, while the
  signature check at the end of the same script already said `UnknownError` "is
  expected" for self-signed certificates. It now treats the signature as applied
  when the file carries one whose thumbprint matches the certificate just used,
  and says so plainly when the chain is untrusted. Real failures — `NotSigned`,
  a hash mismatch — still throw.
- **A build input that lives where people work will be moved, 5 October 2026.**
  `order.txt.example` was renamed to `order.txt` three times -- which is precisely
  what `README.md` tells a user to do with the installed copy -- and each time it
  removed a file `installer.iss` ships, so the build died at the Inno Setup step
  having already spent a minute on PyInstaller. Saying "copy, not rename" in four
  places did not stop it happening again. The canonical copy now lives in `docs\`,
  away from the working root, and the installer sources it from there; it still
  installs to `{app}` so nothing changes for a user. A test now checks that every
  `Source:` in `installer.iss` exists, so a missing build input fails the suite in
  two seconds instead of the build in a minute.
- **Following the README broke the build, 2 October 2026.** `merge_tool.spec`
  ships `order.txt.example` as a data file, while `README.md` said to *rename* it
  to `order.txt` to use it. Doing exactly that removed a build input, and
  PyInstaller stopped with `Unable to find ... order.txt.example`. All three
  places now say **copy**, and the example file says it too. The general lesson:
  a file listed in the spec's `DATA` is a build dependency, so no documentation
  anywhere should tell anyone to move or rename one.

---

## This machine

| | |
|---|---|
| Python (this project) | 3.13.13 at `.python\python.exe` — **use this one.** Self-contained; see "The build environment" |
| Python (the shared one) | 3.13.13, and the only Python that `PATH` or the `py` launcher will find — locate it with `where python`. Despite sitting in a folder named `.venv` it is a **standalone install, not a venv**, so its `site-packages` is shared with an unrelated project and installing anything there affects that project too |
| In that shared install | pypdf 6.13.2, Pillow 12.2.0, openpyxl 3.1.5, python-docx 1.2.0, and 34 more. Present but **unused by this tool**: reportlab 5.0.1, pypdfium2 5.13.0 — they arrived through the shared `site-packages`, which is exactly the drift that justifies `.python\`. Do not start importing them; see "Text is drawn by hand". **PyMuPDF 1.28.0 is in there and it is AGPL-3.0** — never build a shipped artifact against that interpreter. |
| In `.python\` | pypdf 6.19.0, Pillow 12.3.0, PyInstaller 6.22.3 — pinned in `requirements-build.txt` |
| In `.tools\` | Inno Setup 6.7.3, portable, no admin rights needed. Both `ISCC.exe` and the preprocessor `ISPPBuiltins.iss` are present |
| Not installed | pywin32, WiX, Windows SDK / signtool. **No code signing certificate**, which is the only thing now standing between this and a shippable release |
| Microsoft Office | 16.0. **Word automation works well.** |
| LibreOffice | 26.2.5.2 at `D:\LibreOffice\program`, on the machine `PATH`. `soffice` resolves to `soffice.com` — the console launcher, which is the right one: it runs synchronously, where `soffice.exe` returns immediately and can race the output check. |

### Office automation does not work on this machine — it is Office 2016 RTM

Investigated properly on 2 October 2026, which disproved the earlier hypothesis.

**What it is.** `Microsoft Office Professional Plus 2016`, version
**16.0.4266.1001**, an MSI (volume) install with no ClickToRun configuration, 32
bit, whose `EXCEL.EXE` and `WINWORD.EXE` are dated **31 July 2015** — the original
RTM build, never patched, on Windows 11 26200. Office 2016 reached end of extended
support in October 2025, so it will not be getting fixes. Find it with
`Excel.Application\CLSID` → `LocalServer32`; the usual
`Microsoft Office\root\Office16` path does not exist here.

**Symptoms.** A trivial COM sequence works — creating `Excel.Application`, adding
a blank workbook, exporting it to PDF and quitting takes about 3 seconds. Anything
real fails. `Workbooks.Open` returns a workbook whose `.Name` is empty and Excel
then reports itself permanently busy (`RPC_E_SERVERCALL_RETRYLATER`); the tool's
own conversion fails with `RPC_E_CALL_REJECTED` even though its PowerShell script
installs the COM message filter that exists to retry exactly that. Word, which
this file previously recorded as working well, now fails the same way.

**Two hypotheses were tested and are wrong:**

- **Not the Acrobat PDFMaker add-in.** Disabling it (`LoadBehavior=0` in HKCU,
  with the HKLM entries left alone) produced one success out of four attempts —
  the other three were a 60-second timeout and two outright rejections. One
  success in four is a coincidence, not a fix. The setting was restored to 3.
- **Not orphaned Office processes.** Three were found accumulating, all with
  `MainWindowHandle = 0` and no Word lock files, so automation leftovers rather
  than anyone's editing session. Killing them changed nothing.

**What is confirmed to work.** `EnableAutoRecover = $false` genuinely prevents the
phantom crash-recovery entries that caused the original trouble: several forced
kills during this investigation produced none. The `Resiliency\DocumentRecovery`
key has stayed absent since it was deleted.

**What to do about it.** Treat Office conversion as unavailable here and use
`--converter libreoffice`, which converts the same spreadsheet correctly in about
14 seconds. If Office conversion ever matters — and the only thing it buys is
`--excel-fit`, which has no LibreOffice equivalent — the realistic options are to
patch this install to a current 2016 build, or move to a supported Office. A
Quick Repair from Apps & Features is worth one attempt before either. Do not spend
more time on add-ins or stray processes; both have been eliminated.

## Verification status

Tested and working: mixed merges of all five source types; page ranges, reordering
and repetition; exclusions (`!7`, `~2-4`) across PDFs, Word and Excel; image page
size matching (exact to the decimal against A4); multi-frame TIFF; EXIF rotation;
transparency flattening; Word conversion via Office; Word/Excel/CSV conversion via
LibreOffice with an isolated profile; the index with 1- and 2-page layouts;
stamping at all six positions with Bates formats and start offsets; bookmarks
surviving index insertion; the GUI end to end including drag-and-drop (tested by
constructing a real `HDROP` and sending a genuine `WM_DROPFILES`); presets; saved
settings including corrupt-file handling; and both launchers.

**The PyInstaller build works — verified 1 October 2026, and it worked first
try**, contrary to the warning that used to sit in this paragraph.
`.python\python.exe -m PyInstaller --clean --noconfirm packaging\merge_tool.spec`
produced `dist\PDF Page Merger\` at 42 MB with both executables. Checked:
`pdfmerge.exe` merges PDFs, an image and an exclusion with a contents page and
stamping, giving the same 7 pages and 3 bookmarks as the source checkout; the GUI
launches and titles its window; `README.md`, `order.txt.example` and the `input\`
instructions all ship in `_internal\`; and none of pymupdf, cv2, numpy,
playwright, reportlab, openpyxl or docx is bundled.

**The whole install/uninstall cycle was verified on 7-8 October 2026.**
Installed from `PDFPageMerger-1.0.0-Setup.exe` to the default
`C:\Program Files\PDF Page Merger\`, exercised, and removed. What it showed:

- The uninstall entry registers the publisher from `AppPublisher`, version
  1.0.0, install location, ~55 MB.
- All six customer-facing files land at the top level, with nothing misfiled
  into `_internal\`, and `input\READ ME - put PDFs here.txt` is in the folder
  the tool actually watches.
- **The output fallback works against a genuinely unwritable directory.** A
  write probe into the install folder fails as it should, and the installed
  command line with no `-o` resolved its output to
  `Documents\PDF Page Merger\merged.pdf` rather than raising. This is the
  2 October `os.access` crash, checked where it actually happened rather than
  only in the test suite.
- Settings went to `AppData\Roaming\PDF Page Merger\settings.json`, not the
  install folder.
- An AES-256 source merged with `--password`, so the bundled OpenSSL works in
  the frozen build -- the 5 October defect, likewise checked against a real
  installation.
- The window opens, reports a real window handle and title, and closes cleanly.
- The uninstall removes the registry entry, the install folder, the Start Menu
  group and the desktop shortcut, and leaves no orphaned keys anywhere under
  `HKLM\SOFTWARE` or `HKCU\SOFTWARE` -- nothing under the `AppId`, no App
  Paths entry. It deliberately keeps `settings.json` and anything in
  `Documents\PDF Page Merger\`, which is the user's data rather than the
  program's.

Installing needs elevation, and a silent install launched from a background
shell has its UAC request cancelled with exit code 2 and no log written. Run it
interactively, or from a foreground terminal.

**The programs carried no version metadata until 7 October 2026.** `VERSION`
was declared in `merge_tool.spec` from the first build and never passed to either
`EXE()` call, so `Properties -> Details` was blank on both executables: no
`ProductName`, no `CompanyName`, no `FileVersion`.

Found by testing a real installation rather than by reading anything. The note
below about embedded metadata is correct and always was -- it describes
`Setup.exe`, which Inno Setup stamps from `AppPublisher` and `AppVersion`. That
is precisely why the gap lasted: the installer looked finished, so what it
installed went unchecked.

It matters more than tidiness. A firm's IT inventories software by
`FileVersion`, and signing does not supply it -- a signed build with no version
resource still shows nothing. The fix builds a `VSVersionInfo` in the spec from
the constants already there (PyInstaller 6 accepts the object directly, see
`building/api.py:618`) rather than committing a separate resource file, which
would have been a third copy of the version string to keep in step. `COMPANY`
is declared in the spec and asserted equal to `AppPublisher`, the same
declare-independently-and-test-agreement pattern the version and names already
use.

Two tests guard it. One checks the constants agree; the other checks they are
actually *used*, because a test of the first kind would have passed throughout
the week the defect existed. Verified by deleting the command line's resource:
`assert 1 == 2`.

**The installer compiles and `build.ps1` runs end to end — verified 2 October
2026.** `ISCC.exe` compiled `installer.iss` without complaint, and
`.\packaging\build.ps1 -SkipSign` carried out both stages in one run, producing
`dist\installer\PDFPageMerger-1.0.0-Setup.exe` at 13.9 MB. Its embedded metadata
reads ProductName "PDF Page Merger", Company as set in `AppPublisher`,
version 1.0.0, signature
`NotSigned` as `-SkipSign` implies. The whole run was done with the shared interpreter
stripped from `PATH`, and PyInstaller reported `Python environment:
F:\PDF Page Merger Tool\.python`, so the pipeline really is self-contained.

**The installer installs — tested 2 October 2026**, per-user ("Just me", so no
administrator rights were needed) into `D:\PDF Page Merger`, the destination page
accepting a path outside `Program Files` because `DisableDirPage` is not set.
Confirmed afterwards by inspecting the machine rather than taking it on trust:

- Both programs and `unins000.exe` present in the install folder.
- Uninstall entry registered — Apps & Features shows "PDF Page Merger", version
  1.0.0, the publisher from `AppPublisher`, `InstallLocation`
  `D:\PDF Page Merger\`.
- Start Menu shortcut under `%APPDATA%\...\Start Menu\Programs\` and a desktop
  shortcut, both per-user, which is correct for this install mode. Nothing in
  `ProgramData` or the Public desktop, as expected.
- The **installed** `pdfmerge.exe` merges correctly: page ranges, an exclusion, an
  image matched to A4, a contents page and stamping gave the same 7 pages as the
  source checkout.
- The window ran too, writing `settings.json` beside the tool — correct, since a
  `D:\` install is writable, so the `%APPDATA%` fallback was not needed — and
  producing `output\merged.pdf`.

**The uninstaller is clean too — tested 2 October 2026.** Run from the Start Menu
entry; it removed both programs, `_internal\`, `unins000.exe`, `settings.json`
(the one thing `[UninstallDelete]` targets), the Start Menu group, the desktop
shortcut and the Apps & Features registration. It left `output\merged.pdf` and its
folder, which is correct: Inno does not delete files it did not install, nor a
folder that still has something in it, so a user's merged output survives
uninstalling the tool. No orphaned registry keys in `HKCU` or `HKLM`.

The all-users variant was uninstalled the same day and was clean too, including
the `HKLM` registration, the `ProgramData` Start Menu group and both the Public
and per-user desktop shortcuts. It removed the install folder **entirely**, the
difference from the per-user case being simply that nothing user-created was left
in it — which is itself a consequence of the `os.access` bug, since the tool had
never managed to write an `output\` folder there. Nothing was left in
`Documents\`, `%APPDATA%` or the registry.

**The read-only install case is tested too — and it was broken.** An all-users
install into `C:\Program Files\PDF Page Merger` on 2 October 2026 confirmed the
documentation fix: `README.md`, `order.txt.example` and `input\READ ME - put PDFs
here.txt` all arrived beside the programs, `input\` was created, and nothing was
left duplicated in `_internal\`. But a merge without `-o` **crashed** with
`PermissionError` from `mkdir` on the Program Files `output\` folder. See
"`os.access` lies about directories on Windows" above. Fixed and re-verified by
copying the frozen build to a folder with write access denied through `icacls`
and running it: it merged and wrote to `Documents\PDF Page Merger\merged.pdf`,
while a writable folder still prefers its own `output\`.

**Nothing about the installer is unverified now** — build, signing, install both
per-user and all-users, the documentation placement, the read-only output
fallback, and the uninstaller have all been exercised. The right-click menu is not
a gap because the feature was removed; see "There is no Explorer right-click menu,
on purpose". What has *not* been done is a real signed release, for want of a
certificate, and the installed copy at `C:\Program Files` predates the
`os.access` fix, so it still has the crash until it is reinstalled.

Two later changes have not been through an install: the documentation now being
placed beside the programs, and the removal of the registry entries. Both are
declarative in `installer.iss` and the compiler confirms them, but the next
install is what proves them.

**The signing path is exercised — verified 2 October 2026 with a throwaway
certificate.** `New-TestCertificate.ps1` (without `-Trust`, so nothing was added
to any trust store) then `build.ps1 -CertificateThumbprint ...` signed both
executables, compiled the installer, signed that, and ran its own signature
check. All three came out Authenticode-signed and **timestamped** against
`timestamp.digicert.com`, and the file times confirm the order that matters: the
programs were signed at 19:19:22 and the installer packaged and signed at
19:19:39, so it wrapped already-signed binaries. All three read `UnknownError`,
which is the correct result for a self-signed certificate outside Trusted Root; a
CA-issued certificate would read `Valid`. The certificate was deleted afterwards
and all three stores verified clean.

This found the `Invoke-Signing` bug above, which had made the documented
test-certificate workflow unusable. What is still untested is signing with a
**real** certificate, since there is none — but the only difference should be the
reported status.

---

## Known limitations

- **`--excel-fit` only works when Excel does the converting.** It changes the
  workbook's print setup before exporting, which LibreOffice has no equivalent
  for. Under LibreOffice the switch is silently ignored. Set "Fit to 1 page wide"
  in the workbook itself if you need it under either converter.
- **HEIC images** need `python -m pip install pillow-heif`; they are skipped with
  that message until then.
- **Drag-and-drop is Windows-only.** The buttons work everywhere.
- **Page numbers follow the converted document**, so `report.docx:2-4` means pages
  2–4 as Word lays them out. Use `--list` first if unsure.
- Password-protected files are skipped with a note, not prompted for.

---

## If you pick this up again

**To finish the installer:** the build is done — `.\packaging\build.ps1 -SkipSign`
produces a working setup .exe from a cold start. What remains is to *run* that
setup on a machine you do not mind changing (it needs to be approved at a UAC
prompt) and check the shortcuts, the read-only
`Program Files` output fallback and the uninstaller. Then sign it. Change
`AppPublisher` in `installer.iss` if you sign the build — it must match your
certificate's subject. `AppUrl` is gone; the file says how to put a real support
URL back.

**To ship a build to someone:** hand over
`dist\installer\PDFPageMerger-1.0.0-Setup.exe` and nothing else — it carries its
own Python. Send its SHA-256 separately so the recipient's IT can verify it,
because **e-mail will not carry it**: `.exe` attachments are blocked by Gmail,
Outlook and essentially every corporate filter, and zipping does not help. Use a
download link or a USB stick. `docs\customer-install-note.md` is a template
covering the prerequisites, the SmartScreen warning, where output goes and how to
uninstall; fill in the version, checksum and contact details.

Make **LibreOffice** the documented prerequisite rather than Office. Not for
licensing reasons but for support ones: you cannot inspect a customer's Office
installation, and an unpatched one fails in ways that look like your bug — this
machine is the proof. PDFs and images need nothing at all.

**The terms are not in the public repository.** They have to identify the
contracting party by registered office, so they are issued with each order
instead. `packaging\not-published.txt` lists what is held back and
`packaging\publish.ps1` enforces it; `packaging\README.md` under "Publishing"
explains how a clone without them still builds and tests. The short version: the
two files are flagged `skipifsourcedoesntexist` in `installer.iss`, `build.ps1`
writes a placeholder licence page and refuses to sign such a build, and the tests
that read them skip for exactly the paths on that list.

**The terms exist now.** `LICENCE-TERMS.md` is the licence the program is sold
under, and `installer.iss` shows it on an accept/decline page that setup will not
pass without acceptance. It is drafted to the law of England and Wales, as a
perpetual per-seat licence (one named user, two devices), business-to-business
only — that last choice is what allows the liability cap and the exclusion of
implied terms to stand, and it is why clause 2.2 says the Software is not offered
to consumers. Selling to individuals would require redrafting, not a disclaimer.

Three clauses were written for this product rather than taken from a template,
and are the ones to preserve through any edit:

- **3.4 against 4.1.** Using the tool to produce bundles *for* clients is
  expressly allowed — it is the entire product. Handing clients the software, or
  running it for them as a separately charged service, is not. Those two
  sentences have to stay next to each other; losing the first turns the second
  into a prohibition on the intended use.
- **9.6 and 10.5.** The output must be checked before it is filed or served, and
  the customer acknowledges the risk allocation is reflected in the price. That
  acknowledgement is what gives the liability cap a chance under UCTA 1977 — a
  bare cap in a supplier's standard terms is the kind courts strike down.
- **8.** No telemetry, no uploads, not a data processor. This is only true
  because the merger never reads document contents, so **if that ever changes,
  clause 8 becomes a false statement in a contract**, not merely a stale README
  line. See "Nothing reads your documents" above.

**`EULA.rtf` is generated, never edited.** `packaging\make_eula.py` renders it
from `LICENCE-TERMS.md`, and `build.ps1` regenerates it before every Inno Setup
run, for the same reason the notices are regenerated: two copies of a legal
document drift, and here the drifting copy is the one the customer accepted.
Edit the Markdown. The converter handles only the Markdown that document uses —
headings, wrapped paragraphs, bullets, bold, italic, code spans and `---` — so
add support before reaching for a table. Verify a change by loading the result
into a RichEdit, which is what Inno displays it in:

```powershell
Add-Type -AssemblyName System.Windows.Forms
$rtb = New-Object System.Windows.Forms.RichTextBox
$rtb.Rtf = [System.IO.File]::ReadAllText("packaging\EULA.rtf")
$rtb.Text
```

That is how the one real conversion bug was caught: a code span inside an italic
paragraph came out with its backticks showing, because `inline()` escaped
emphasised runs instead of recursing into them.

**The terms still carry placeholders** — entity name, registered address,
contact, privacy notice — and `make_eula.py` lists them on every run. A build
with `-SkipSign` prints them in yellow and carries on; **a signed build throws**,
because a signed build is one going to somebody, and an accept page reading
"[LEGAL ENTITY NAME]" is not a contract. Both the script and `build.ps1` find
them with the same regex; keep the two in step if you change either.

**Still outstanding:** the terms carry placeholders, and they have not been read
by a solicitor — see `BUSINESS-NOTES.md`. Bump the version for every build anyone receives, and keep a record of
who has which, or supporting "it does not work" is guesswork. It has to be set in
**two** places — `AppVersion` in `installer.iss` and `VERSION` in
`merge_tool.spec` — and this file used to claim the two were cross-checked. They
were not: `installer.iss` has no `[Code]` section and never had one. A claimed
safety net that does not exist is worse than none, because it invites trusting
it. `tests/test_packaging.py` now really does check it, along with the
application name and both executable names, so a mismatch fails the suite in
under a second rather than producing an installer whose filename and whose
embedded metadata disagree. `packaging\README.md` has the release checklist.

**Commercial reasoning is deliberately not in this file.** Market analysis,
pricing and route-to-market live in `BUSINESS-NOTES.md`, which `.gitignore`
excludes. This file is written to be readable by a stranger; that one is not for
publication. One decision from it does belong here, because it constrains the
architecture: **the tool is sold on-premises, not as a service.** That is what
keeps the "nothing is uploaded" property true, and it is also forced — Microsoft
does not license Office for server-side automation, so a hosted version could not
use the Office conversion path at all.

**Dependency licensing:** pypdf is BSD-3 and Pillow is MIT-CMU, both fine for
commercial distribution. cryptography is Apache-2.0 or BSD-3 at your option, and
OpenSSL 3.x is Apache-2.0. Office can never be shipped — the user must have their
own. LibreOffice is MPL 2.0 and easier to require than to bundle. Every component
actually distributed has its licence text in `THIRD-PARTY-NOTICES.txt`, which
`packaging\make_notices.py` generates and the build regenerates every time; see
"Packaging" above for why that is automatic rather than remembered.

**Natural next features:** an index with sub-entries per page range; bookmarks
nested by source; a job file that saves a whole merge (files, order, ranges) for
repeat runs; batch mode over many folders.
