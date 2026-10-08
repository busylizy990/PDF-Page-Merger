# PDF Page Merger — note for testers

Thanks for trying this. It merges PDFs, images, Word documents and spreadsheets
into one PDF, in an order you control, optionally with a contents page and page
numbering.

It should take about ten minutes to try properly. There is a checklist at the end
and anything you notice is useful, including "this bit was confusing".

---

## Windows will warn you, and that is expected

When you run the installer you will get a prompt saying **"Publisher: Unknown"**.

That is not a problem with the file. Software is normally signed with a
certificate bought from a certificate authority, which is what makes Windows show
a company name instead of "Unknown". One has not been bought yet, so Windows has
nothing to show you.

Say yes to the prompt. If you would rather not, that is a completely reasonable
instinct and you should say so instead — it is better feedback than installing
reluctantly.

**One exception. Stop if you cannot get past it.** If your PC is a fairly new
Windows 11 machine, it may have **Smart App Control** turned on, which refuses
unsigned programs outright with no "run anyway" option.

Do not turn Smart App Control off to get this working. Windows will not let you
turn it back on afterwards without reinstalling the whole operating system, and
that is far too high a price. Just say it blocked you — that is genuinely useful
to know.

## Installing

Run the installer from wherever you were given it. If you were sent a USB stick,
running it straight from the stick is fine.

It will offer to install **for everyone on this PC** or **just for me**. Either is
fine. "Just for me" needs no administrator password, so choose that if you do not
have one.

You need 64-bit Windows 10 or 11. Nothing else — Python and everything it needs
is included.

To merge **Word documents or spreadsheets** you need Microsoft Office or
LibreOffice already installed. PDFs and images work without either.

## Using it

A **PDF Page Merger** entry appears in your Start Menu, and on the desktop if you
asked for the shortcut.

**Drag files onto the window**, drag them into the order you want, and press
Merge. That is the whole idea. You do not need to put files in any particular
folder first.

The merged PDF goes into a `Documents\PDF Page Merger` folder, and the window
tells you the exact path when it finishes.

`README.md` in the installation folder is the full guide, if you want page
ranges, contents pages or page numbering.

## Nothing leaves your computer

The program does not upload your documents, does not read their text, has no
usage tracking, and works with no internet connection at all. Word and Excel
conversion uses the copy of Office or LibreOffice already on your own machine.

This matters because the point of the thing is handling documents you would not
want going anywhere.

## What would help most

- [ ] **Drag a folder of several PDFs onto the window.** Did they end up in the
      order you expected? If not, what order did you expect?
- [ ] **Merge without choosing an output folder.** Did it tell you clearly where
      the file went, and was that somewhere sensible?
- [ ] **A Word document**, if you have Office or LibreOffice. This is the part
      most likely to behave differently on different PCs.
- [ ] **Uninstall it** — Settings → Apps → Installed apps → PDF Page Merger, or
      the Uninstall entry in the Start Menu. Did it disappear from the Start
      Menu and the desktop?

## Sending feedback

Anything at all is useful, but these especially:

- Anything that **crashed**, or any error message — the exact wording if you can
- Anything you expected to work and it did not
- Anything **confusing**, even slightly. If you had to guess what a button did,
  that is a fault in the program, not in you
- How long the whole thing took, and whether you would have given up anywhere

If something went wrong, it helps to know **which version** you had. Right-click
the installer or `PDF Page Merger.exe`, choose **Properties → Details**, and the
version is listed there.

Uninstalling leaves any PDFs you produced exactly where they are, so you will not
lose anything by removing it.

**contact@damreb.co.uk**
