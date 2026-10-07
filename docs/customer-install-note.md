# PDF Page Merger — installation note

**A template to send with the installer.** Fill in the bracketed fields —
version, checksum, seat count and contact — delete this line and the next, and
send it as the body of an email or a one-page PDF alongside the download link.

Substitute `[VERSION]`, `[SIZE]`, `[CHECKSUM]`, `[SEATS]` and
`[YOUR CONTACT DETAILS]`. `[SEATS]` is the number of users this customer is
buying for. It is deliberately not named after a number, because the legal
documents use a similarly-named token for the company registration number, and
one careless find-and-replace across the project would otherwise promise a
licence for several million users.

Get the checksum for a specific build with:

```powershell
(Get-FileHash .\dist\installer\PDFPageMerger-1.0.0-Setup.exe -Algorithm SHA256).Hash
```

---

## What you are receiving

**PDF Page Merger [VERSION]** — `PDFPageMerger-[VERSION]-Setup.exe`, about [SIZE].

It combines PDFs, images, Word documents and spreadsheets into a single PDF, in an
order you control, optionally adding a contents page and page numbering.

To let your IT team confirm the file arrived intact, its SHA-256 checksum is:

```
[CHECKSUM]
```

They can verify it in PowerShell with:

```powershell
Get-FileHash .\PDFPageMerger-[VERSION]-Setup.exe -Algorithm SHA256
```

## Before you install

**Windows only.** Windows 10 or Windows 11.

**Nothing else is needed for PDFs and images.** The program carries everything it
requires, including its own copy of Python. You do not need to install anything
alongside it.

**For Word documents and spreadsheets**, one of the following must already be on
the machine, because the program does not include either:

- **LibreOffice** — free, from libreoffice.org. This is what we recommend and
  test against.
- **Microsoft Office** — works, but only if your installation is current. Older
  unpatched versions of Office can refuse automation, in which case the program
  waits briefly and then uses LibreOffice instead.

If neither is present, PDFs and images still merge normally; Word and Excel files
are skipped with a note telling you why.

## Installing

Double-click the installer.

**Windows will warn you**, with a blue box saying *"Windows protected your PC"*.
Choose **More info**, then **Run anyway**. This appears because the installer is
not yet code-signed; it is not an indication that anything is wrong with the file,
and the checksum above lets you confirm you received exactly what we sent.

You will then be asked **who to install for**:

| Choice | Installs to | Needs an administrator |
|---|---|---|
| Just me | your own user folder | no |
| All users | `C:\Program Files\PDF Page Merger` | yes |

Either is fine, and you may change the destination folder on the following page.

## Using it

A **PDF Page Merger** entry appears in the Start Menu, and on the desktop if you
asked for a shortcut. Drag files onto the window, put them in the order you want,
and press Merge.

There is also a `pdfmerge.exe` in the installation folder for use from a command
prompt or a script.

`README.md` in the installation folder is the full guide, covering page ranges,
contents pages and page numbering.

## Where it puts things

- **Merged output** goes to an `output` folder beside the program, or to
  `Documents\PDF Page Merger\` if the program was installed somewhere your account
  cannot write to, such as `Program Files`.
- **Your preferences** are saved beside the program, or in your own profile if
  that folder is read-only.
- **Nothing else on the machine is modified.** The installer adds a Start Menu
  entry, an optional desktop shortcut and an uninstall registration. It makes no
  other changes to Windows or to file associations.

## Your documents stay on your machine

The program never uploads anything and never transmits the contents of your
documents. It copies pages between files on the computer it is running on. Word
and Excel conversion is performed by the copy of Office or LibreOffice already
installed on that same machine.

It does not need an internet connection, and will work on a machine that has none.

## Removing it

**Settings → Apps → Installed apps → PDF Page Merger → Uninstall**, or the
*Uninstall PDF Page Merger* entry in the Start Menu.

Uninstalling removes the program and its shortcuts. Any PDFs you have produced are
left where they are.

## Licensing

**The installer shows the licence terms and asks you to accept them** before it
installs anything. They are also left in the installation folder as
`LICENCE-TERMS.md`, so you can read them again afterwards or pass them to your
legal team.

In short: the licence is perpetual, so it does not expire and there is nothing to
renew. It covers **[SEATS] named user(s)**, each on up to two of their own
machines, and includes every version 1.x update. Use it for as much client work
as you like; you may not pass the program itself on to anyone else or run it as a
service for others. Please read the terms themselves rather than relying on this
paragraph.

`PRIVACY-NOTICE.md` is in the installation folder too. It is short, and the part
worth reading is that the program sends nothing anywhere: because your documents
never reach us, we hold no personal data of yours and we are not your data
processor, so no data processing agreement is needed for this licence. Your own
obligations to your clients are of course unchanged.

`THIRD-PARTY-NOTICES.txt` in the installation folder lists the open-source
components the program is built from, with their licences. That file is separate
from the licence terms and does not replace them.

Microsoft Office is never supplied with this program; where Office is used for
conversion, it is your own licensed copy on your own machine. Note that
Microsoft's licensing of Office does not generally permit unattended or
server-side automated use, so if you intend to run merges on a schedule or on a
server, LibreOffice is the converter to use.

## Support

[YOUR CONTACT DETAILS]

When reporting a problem, it helps enormously to include the version above, what
you were merging, and the text of any message the program showed.
