#!/usr/bin/env python3
"""
PDF Page Merger Tool
====================

Reusable merger: you place PDFs, images, Word documents and spreadsheets (whole
files, or specific page ranges) and it stitches them into one document, in the
order you specify.

The tool NEVER extracts, reads, prints or logs the *content* of your PDFs.
It only copies page objects from source files into the output file. The only
things it reports are file names and page counts.

Usage
-----
    python merge.py                          # merge everything in .\\input
    python merge.py a.pdf scan.jpg b.pdf     # merge these files, in this order
    python merge.py "report.pdf:1-3,7" b.pdf # only pages 1-3 and 7 of report.pdf
    python merge.py "report.pdf:!4" -o out.pdf  # report.pdf without page 4
    python merge.py --list                   # dry run: show the plan, merge nothing
    python merge.py -o final.pdf             # choose the output name

Page-range syntax:  1  |  2-5  |  7-  (7 to end)  |  -4  (start to 4)  |  all
Combine with commas:  1-3,7,10-
Remove pages instead with a leading ! (or ~):  !7  |  !2-4  |  !1,3,5
A keep-list also reorders and repeats; an exclusion keeps the original order.

For a finished bundle, --index adds a contents page listing every source against
its starting page, and --stamp numbers the pages ("{n}", "Page {n} of {total}",
or "ABC-{n:05d}" for Bates numbering).

Images become pages sized to match the PDF pages they are merged with, so the
finished document is one consistent page size. See --image-page to change that.

Word documents (.docx, .doc, .docm, .rtf, .odt) and spreadsheets (.xlsx, .xlsm,
.xlsb, .xls, .csv, .ods) are converted to PDF first, by Microsoft Office where
it is installed, otherwise by LibreOffice. The converted copies are temporary
and deleted after the merge; see --keep-converted. Spreadsheets follow their own
print setup unless you pass --excel-fit.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import sys
import tempfile
from io import BytesIO
from pathlib import Path

try:
    from pypdf import PdfReader, PdfWriter, Transformation
except ImportError:
    sys.exit("pypdf is not installed. Run:  python -m pip install pypdf")

# pypdf narrates malformed files to stderr; we report those files ourselves,
# with the file name attached, so keep its chatter out of the way.
logging.getLogger("pypdf").setLevel(logging.CRITICAL)

# Packaged into an .exe, __file__ points inside a temporary unpack folder, so the
# tool's own folder is where the executable lives instead.
BASE = Path(
    sys.executable if getattr(sys, "frozen", False) else __file__
).resolve().parent
INPUT_DIR = BASE / "input"
OUTPUT_DIR = BASE / "output"
ORDER_FILE = BASE / "order.txt"

# Images become pages too. Multi-frame TIFF/GIF count as several pages, so page
# ranges work on them the same way they work on a PDF.
IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff",
    ".webp", ".ppm", ".pgm", ".jfif", ".heic", ".heif",
}

# Word and Excel documents are converted to PDF first, by Office itself where it
# is installed, otherwise by LibreOffice.
WORD_EXTS = {".docx", ".doc", ".docm", ".rtf", ".odt"}
EXCEL_EXTS = {".xlsx", ".xlsm", ".xlsb", ".xls", ".csv", ".ods"}
OFFICE_EXTS = WORD_EXTS | EXCEL_EXTS

SOURCE_EXTS = {".pdf"} | IMAGE_EXTS | OFFICE_EXTS

# Page sizes in points (1/72 inch).
PAGE_SIZES = {
    "letter": (612.0, 792.0),
    "a4": (595.28, 841.89),
    "legal": (612.0, 1008.0),
}

# A page spec: 1 | 2-5 | 7- | -4 | all, comma separated. A leading ! or ~ turns
# the whole thing around: every page except the ones listed.
# A lone ! or ~ matches too, so that a typo gets a helpful error rather than
# being mistaken for part of the file name.
RANGE_RE = re.compile(
    r"^(?:[!~]|[!~]?(?:all|\*|\d+|\d*-\d+|\d+-)(?:,(?:\d+|\d*-\d+|\d+-))*)$",
    re.IGNORECASE,
)
DROP_MARKERS = ("!", "~")


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #

def natural_key(path: Path):
    """Sort so that page2.pdf comes before page10.pdf."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def split_spec(token: str) -> tuple[str, str | None]:
    """Split 'file.pdf:1-3' into ('file.pdf', '1-3').

    Splits on the LAST colon only, and only when what follows is a valid page
    spec, so Windows paths like C:\\docs\\file.pdf are left alone.
    """
    token = token.strip().strip('"')
    if ":" in token:
        head, _, tail = token.rpartition(":")
        if head and tail and RANGE_RE.match(tail):
            return head, tail
    return token, None


def parse_line(line: str) -> tuple[str, str | None] | None:
    """Parse one order.txt line into (path, spec). Returns None for blanks/comments."""
    line = line.split("#", 1)[0].strip()
    if not line:
        return None
    path, spec = split_spec(line)
    if spec is None:
        # Also accept the whitespace form:  my file.pdf   1-3,7
        head, sep, tail = path.rpartition(" ")
        if sep and head.strip() and RANGE_RE.match(tail.strip()):
            path, spec = head.strip(), tail.strip()
    return path.strip().strip('"'), spec


def parse_ranges(spec: str | None, n_pages: int, label: str) -> list[int]:
    """Turn a page spec into a list of 0-based page indices.

    Normally the spec says which pages to keep, in the order given, so it also
    reorders and repeats. A leading ! (or ~) inverts it: keep everything except
    the pages listed, in their original order. The two forms are deliberately
    not mixable -- one says what to keep, the other says what to drop.
    """
    if spec is None or spec.strip().lower() in ("", "all", "*"):
        return list(range(n_pages))

    spec = spec.strip()
    dropping = spec[:1] in DROP_MARKERS
    if dropping:
        spec = spec[1:].strip()
        if not spec:
            raise ValueError(f"{label}: nothing to drop -- write it like !7 or !2-4")

    listed: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            first, _, last = part.partition("-")
            start = int(first) if first.strip() else 1
            end = int(last) if last.strip() else n_pages
        else:
            start = end = int(part)
        if start < 1 or start > end:
            raise ValueError(f"{label}: invalid page range '{part}'")
        if end > n_pages:
            raise ValueError(
                f"{label}: page range '{part}' exceeds the file's {n_pages} page(s)"
            )
        listed.extend(range(start - 1, end))

    if dropping:
        unwanted = set(listed)
        kept = [i for i in range(n_pages) if i not in unwanted]
        if not kept:
            raise ValueError(f"{label}: dropping '{spec}' would leave nothing")
        return kept

    if not listed:
        raise ValueError(f"{label}: page spec '{spec}' selects no pages")
    return listed


def describe_spec(spec: str | None, n_pages: int) -> str:
    """How a page spec reads in the run summary."""
    if not spec:
        return f"1-{n_pages}"
    spec = spec.strip()
    if spec[:1] in DROP_MARKERS:
        return f"all except {spec[1:].strip()}"
    return spec


def resolve(path_str: str) -> Path:
    """Resolve a source path: as given, then relative to .\\input, then to the tool folder."""
    p = Path(path_str)
    if p.is_absolute():
        return p
    for base in (Path.cwd(), INPUT_DIR, BASE):
        candidate = base / p
        if candidate.exists():
            return candidate
    return INPUT_DIR / p  # does not exist; reported later against a sensible path


def can_write_dir(folder: Path) -> bool:
    """True when a file can actually be created in folder, creating it if needed.

    Do not be tempted back to `os.access(folder, os.W_OK)`. On Windows that only
    reflects the read-only attribute and ignores ACLs, so it reports
    C:\\Program Files as writable -- which made the fallbacks below dead code and
    turned an installed copy into an unhandled PermissionError. The only reliable
    test on Windows is to write something.
    """
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".write-test-{os.getpid()}"
        with open(probe, "wb"):
            pass
        probe.unlink()
        return True
    except OSError:
        return False


def writable_output_dir() -> Path:
    """Where merged files go when no output is named.

    The tool's own output folder normally, which keeps a copied-around folder
    self-contained. An installed copy lives somewhere like Program Files and
    cannot write there, so that case falls back to the user's Documents, and then
    to the temp folder if even that is barred.
    """
    choices = (
        OUTPUT_DIR,
        Path.home() / "Documents" / "PDF Page Merger",
        Path(tempfile.gettempdir()) / "PDF Page Merger",
    )
    for folder in choices:
        if can_write_dir(folder):
            return folder
    return choices[-1]  # nothing is writable; let the caller's error speak


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def is_word(path: Path) -> bool:
    return path.suffix.lower() in WORD_EXTS


def is_excel(path: Path) -> bool:
    return path.suffix.lower() in EXCEL_EXTS


def needs_conversion(path: Path) -> bool:
    return is_word(path) or is_excel(path)


def office_app_for(path: Path) -> str:
    return "EXCEL" if is_excel(path) else "WORD"


# --------------------------------------------------------------------------- #
# Word and Excel documents -> PDF
# --------------------------------------------------------------------------- #

# Driven through PowerShell so no extra Python package is needed: Office is
# already on the machine, and this is the same COM interface pywin32 would use.
# Reads a manifest of "app<TAB>source<TAB>destination" lines and writes a result
# line per document. Each application is started at most once, macros are
# force-disabled, and a session the user already had open is never closed.
OFFICE_PS = r"""
param([string]$Manifest, [string]$Result, [string]$ExcelFit = 'as-is')
$ErrorActionPreference = 'Stop'

# Office rejects COM calls whenever it is busy (RPC_E_CALL_REJECTED) -- during
# startup, while finishing an export, while repainting. A message filter is the
# supported answer: Windows then waits and retries the call for us instead of
# throwing. Without this, converting several files in a row is unreliable.
try {
    Add-Type -ErrorAction Stop -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

[ComImport, Guid("00000016-0000-0000-C000-000000000046"),
 InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IOleMessageFilter
{
    [PreserveSig] int HandleInComingCall(int dwCallType, IntPtr hTaskCaller, int dwTickCount, IntPtr lpInterfaceInfo);
    [PreserveSig] int RetryRejectedCall(IntPtr hTaskCallee, int dwTickCount, int dwRejectType);
    [PreserveSig] int MessagePending(IntPtr hTaskCallee, int dwTickCount, int dwPendingType);
}

public class OfficeMessageFilter : IOleMessageFilter
{
    [DllImport("Ole32.dll")]
    private static extern int CoRegisterMessageFilter(IOleMessageFilter newFilter, out IOleMessageFilter oldFilter);

    public static void Register()
    {
        IOleMessageFilter previous;
        CoRegisterMessageFilter(new OfficeMessageFilter(), out previous);
    }

    public static void Revoke()
    {
        IOleMessageFilter previous;
        CoRegisterMessageFilter(null, out previous);
    }

    int IOleMessageFilter.HandleInComingCall(int dwCallType, IntPtr hTaskCaller, int dwTickCount, IntPtr lpInterfaceInfo)
    {
        return 0;   // SERVERCALL_ISHANDLED
    }

    int IOleMessageFilter.RetryRejectedCall(IntPtr hTaskCallee, int dwTickCount, int dwRejectType)
    {
        // SERVERCALL_RETRYLATER: wait out a busy application, but briefly. One
        // that is wedged (a modal dialog, a misbehaving add-in) must surface as
        // an error quickly so the merge can fall back to LibreOffice instead.
        if (dwRejectType == 2 && dwTickCount < 10000) { return 250; }
        return -1;
    }

    int IOleMessageFilter.MessagePending(IntPtr hTaskCallee, int dwTickCount, int dwPendingType)
    {
        return 2;   // PENDINGMSG_WAITDEFPROCESS
    }
}
'@
    [OfficeMessageFilter]::Register()
} catch {}

# Belt and braces: the filter handles busy servers, this handles the rest.
function Invoke-Office {
    param([scriptblock]$Action, [int]$Tries = 6)
    for ($i = 1; $i -le $Tries; $i++) {
        try { return & $Action }
        catch {
            if ($i -eq $Tries) { throw }
            Start-Sleep -Milliseconds (300 * $i)
        }
    }
}

function Get-AppPids {
    param([string]$Name)
    @(Get-Process -Name $Name -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
}

# Quit() alone sometimes leaves Office running in the background. Give it a few
# seconds to go on its own -- killing it is a last resort, because a killed
# Office registers crash-recovery entries that disrupt the next run -- then stop
# whatever we started. Processes that existed before we began are left alone.
function Stop-OurProcesses {
    param([string]$Name, $Before)
    for ($waited = 0; $waited -lt 5000; $waited += 250) {
        $ours = @(Get-Process -Name $Name -ErrorAction SilentlyContinue |
                  Where-Object { $Before -notcontains $_.Id })
        if ($ours.Count -eq 0) { return }
        Start-Sleep -Milliseconds 250
    }
    foreach ($p in @(Get-Process -Name $Name -ErrorAction SilentlyContinue)) {
        if ($Before -notcontains $p.Id) { try { $p.Kill() } catch {} }
    }
}

function Clean-Message {
    param($ErrorRecord)
    return ($ErrorRecord.Exception.Message -replace '[\t\r\n]', ' ')
}

$out = New-Object System.Collections.ArrayList
$jobs = @()
foreach ($line in (Get-Content -LiteralPath $Manifest -Encoding UTF8)) {
    if (-not $line.Trim()) { continue }
    $f = $line -split "`t"
    $jobs += ,([pscustomobject]@{ App = $f[0]; Src = $f[1]; Dst = $f[2] })
}

# ------------------------------- Word -------------------------------------- #
$wordJobs = @($jobs | Where-Object { $_.App -eq 'WORD' })
if ($wordJobs.Count -gt 0) {
    $before = Get-AppPids 'WINWORD'
    $wasAlreadyRunning = $before.Count -gt 0
    $word = $null
    try {
        $word = Invoke-Office { New-Object -ComObject Word.Application }
        if (-not $word) { throw "Word could not be started" }
        Invoke-Office { $word.Visible = $false }
        Invoke-Office { $word.DisplayAlerts = 0 }
        try { $word.AutomationSecurity = 3 } catch {}
        foreach ($j in $wordJobs) {
            try {
                # The whole document is one retryable unit: a rejection halfway
                # through leaves the document open, so it is reopened and redone.
                Invoke-Office -Tries 2 {
                    $doc = $null
                    try {
                        $doc = $word.Documents.Open($j.Src, $false, $true, $false, "", "", $false)
                        try { $doc.ExportAsFixedFormat($j.Dst, 17) }
                        catch { $doc.SaveAs2($j.Dst, 17) }
                    } finally {
                        if ($doc) {
                            Start-Sleep -Milliseconds 100
                            try { Invoke-Office -Tries 8 { $doc.Close(0) } } catch {}
                            try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($doc) } catch {}
                        }
                    }
                }
                [void]$out.Add("OK`t$($j.Src)")
            } catch {
                [void]$out.Add("ERR`t$($j.Src)`t$(Clean-Message $_)")
            }
            Start-Sleep -Milliseconds 200
        }
    } catch {
        $msg = Clean-Message $_
        [void]$out.Add("FATAL`tWORD`t$msg")
        foreach ($j in $wordJobs) { [void]$out.Add("ERR`t$($j.Src)`t$msg") }
    } finally {
        if ($word) {
            if (-not $wasAlreadyRunning) { try { $word.Quit() } catch {} }
            try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word) } catch {}
            [GC]::Collect()
            [GC]::WaitForPendingFinalizers()
            if (-not $wasAlreadyRunning) { Stop-OurProcesses 'WINWORD' $before }
        }
    }
}

# ------------------------------- Excel ------------------------------------- #
$excelJobs = @($jobs | Where-Object { $_.App -eq 'EXCEL' })
if ($excelJobs.Count -gt 0) {
    $before = Get-AppPids 'EXCEL'
    $wasAlreadyRunning = $before.Count -gt 0
    $excel = $null
    try {
        $excel = Invoke-Office { New-Object -ComObject Excel.Application }
        if (-not $excel) { throw "Excel could not be started" }
        Invoke-Office { $excel.Visible = $false }
        Invoke-Office { $excel.DisplayAlerts = $false }
        try { $excel.ScreenUpdating = $false } catch {}
        try { $excel.AskToUpdateLinks = $false } catch {}
        try { $excel.AutomationSecurity = 3 } catch {}
        foreach ($j in $excelJobs) {
            try {
                Invoke-Office -Tries 2 {
                    $book = $null
                    try {
                        $book = $excel.Workbooks.Open($j.Src, 0, $true)
                        # Keep our workbooks out of Excel's crash-recovery list.
                        # Otherwise an interrupted run leaves recovery entries
                        # behind, and Excel greets the next one with a recovery
                        # pane that blocks automation completely.
                        try { $book.EnableAutoRecover = $false } catch {}
                        if ($ExcelFit -ne 'as-is') {
                            # PageSetup talks to the printer driver and is slow
                            # enough that Excel often rejects the next call.
                            foreach ($sheet in $book.Worksheets) {
                                try {
                                    Invoke-Office -Tries 4 {
                                        $sheet.PageSetup.Zoom = $false
                                        $sheet.PageSetup.FitToPagesWide = 1
                                        if ($ExcelFit -eq 'page') {
                                            $sheet.PageSetup.FitToPagesTall = 1
                                        } else {
                                            $sheet.PageSetup.FitToPagesTall = $false
                                        }
                                    }
                                } catch {}
                            }
                        }
                        $book.ExportAsFixedFormat(0, $j.Dst)
                    } finally {
                        if ($book) {
                            # Excel suspends its object model while it finishes an
                            # export (0x800AC472). Closing has to wait that out, or
                            # the workbook stays open and blocks the next one.
                            Start-Sleep -Milliseconds 200
                            try { Invoke-Office -Tries 8 { $book.Close($false) } } catch {}
                            try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($book) } catch {}
                        }
                    }
                }
                [void]$out.Add("OK`t$($j.Src)")
            } catch {
                [void]$out.Add("ERR`t$($j.Src)`t$(Clean-Message $_)")
            }
            Start-Sleep -Milliseconds 200
        }
    } catch {
        $msg = Clean-Message $_
        [void]$out.Add("FATAL`tEXCEL`t$msg")
        foreach ($j in $excelJobs) { [void]$out.Add("ERR`t$($j.Src)`t$msg") }
    } finally {
        if ($excel) {
            if (-not $wasAlreadyRunning) { try { $excel.Quit() } catch {} }
            try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel) } catch {}
            [GC]::Collect()
            [GC]::WaitForPendingFinalizers()
            if (-not $wasAlreadyRunning) { Stop-OurProcesses 'EXCEL' $before }
        }
    }
}

try { [OfficeMessageFilter]::Revoke() } catch {}
$out | Out-File -LiteralPath $Result -Encoding UTF8
"""


def find_libreoffice(args=None) -> Path | None:
    """LibreOffice can stand in for Office, and is the only option off Windows.

    Looked for on PATH, which is where it is expected to be. --soffice or the
    SOFFICE environment variable override that; a couple of default install
    folders are tried last so the tool still works if copied elsewhere.
    """
    import os
    from shutil import which

    told = getattr(args, "soffice", None) or os.environ.get("SOFFICE")
    if told:
        given = Path(told)
        if given.is_file():
            return given
        for inside in ("soffice.exe", "soffice", "program/soffice.exe"):
            if (given / inside).is_file():
                return given / inside

    found = which("soffice") or which("libreoffice")
    if found:
        return Path(found)

    for candidate in (
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path("/usr/bin/soffice"),
        Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
    ):
        if candidate.exists():
            return candidate
    return None


def _office_batch(
    jobs: list[tuple[Path, Path]], work: Path, args
) -> tuple[dict[Path, object], set[str]]:
    """One PowerShell round trip converting `jobs` via Word/Excel over COM.

    Returns ({source: pdf path or error string}, {apps that could not start}).
    Call `_convert_with_office`, not this, so a wedged Office is noticed early.
    """
    import subprocess

    script = work / "office_to_pdf.ps1"
    manifest = work / "manifest.txt"
    result = work / "result.txt"
    script.write_text(OFFICE_PS, encoding="utf-8")
    manifest.write_text(
        "".join(
            f"{office_app_for(src)}\t{src.resolve()}\t{dst.resolve()}\n"
            for src, dst in jobs
        ),
        encoding="utf-8",
    )

    every_app = {office_app_for(src) for src, _ in jobs}
    # The parser below trusts whatever is in the result file, and this function
    # runs more than once per merge, so last time's answers must not be read as
    # this time's.
    result.unlink(missing_ok=True)
    try:
        subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass",
                "-File", str(script),
                "-Manifest", str(manifest),
                "-Result", str(result),
                "-ExcelFit", args.excel_fit,
            ],
            # Office inherits any pipe we hand PowerShell and keeps it open, so
            # capturing output here would deadlock even after a timeout. The
            # results come back through the result file instead.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # Kept short on purpose: if Office is not answering, waiting longer
            # rarely helps, and LibreOffice is usually standing by.
            timeout=30 + 30 * len(jobs),
        )
    except FileNotFoundError:
        return {src: "PowerShell is not available" for src, _ in jobs}, every_app
    except subprocess.TimeoutExpired:
        return {src: "Office did not respond in time" for src, _ in jobs}, every_app

    if not result.exists():
        return {src: "Office could not be started" for src, _ in jobs}, every_app

    outcome: dict[Path, object] = {}
    stalled: set[str] = set()
    by_resolved = {str(src.resolve()): src for src, _ in jobs}
    dest_of = {str(src.resolve()): dst for src, dst in jobs}

    for line in result.read_text(encoding="utf-8-sig").splitlines():
        fields = line.split("\t")
        if fields[0] == "FATAL" and len(fields) > 1:
            stalled.add(fields[1])
        elif fields[0] in ("OK", "ERR") and len(fields) > 1:
            src = by_resolved.get(fields[1])
            if src is None:
                continue
            if fields[0] == "OK" and dest_of[fields[1]].exists():
                outcome[src] = dest_of[fields[1]]
            else:
                outcome[src] = fields[2] if len(fields) > 2 else "conversion failed"

    for src, _ in jobs:
        outcome.setdefault(src, "the document was not converted")
    return outcome, stalled


def _convert_with_office(
    jobs: list[tuple[Path, Path]], work: Path, args
) -> tuple[dict[Path, object], set[str]]:
    """Convert via Word/Excel over COM, giving up early if Office is unwell.

    The batch timeout has to be generous, because a real conversion can take the
    best part of a minute -- but that made a wedged Office cost 30 + 30N seconds
    before falling back, growing with exactly the large bundles this tool is for.
    So the first file goes on its own: if Office cannot manage one document it
    will not manage twenty, and LibreOffice is standing by. A sick machine now
    costs one file's wait instead of the whole batch's.
    """
    if len(jobs) < 2:
        return _office_batch(jobs, work, args)

    first, rest = jobs[:1], jobs[1:]
    outcome, stalled = _office_batch(first, work, args)
    if not isinstance(outcome.get(first[0][0]), Path):
        reason = outcome.get(first[0][0], "Office did not respond in time")
        every_app = {office_app_for(src) for src, _ in jobs}
        return {src: reason for src, _ in jobs}, every_app

    more, more_stalled = _office_batch(rest, work, args)
    outcome.update(more)
    return outcome, stalled | more_stalled


def _convert_with_libreoffice(
    jobs: list[tuple[Path, Path]], soffice: Path, work: Path
) -> dict[Path, object]:
    """Convert via LibreOffice, one output folder per document to avoid clashes.

    Runs against a throwaway user profile. Without that, LibreOffice hands the
    job to a copy the user already has open: it can silently convert nothing,
    it disturbs their session, and it leaves locks on the input files.
    """
    import subprocess

    profile = work / "loprofile"
    profile.mkdir(parents=True, exist_ok=True)
    isolated = f"-env:UserInstallation={profile.as_uri()}"

    outcome: dict[Path, object] = {}
    for src, dst in jobs:
        # Output goes to a file rather than a pipe: soffice leaves background
        # processes holding inherited handles, which can wedge a pipe read.
        log = dst.parent / "soffice.log"
        try:
            with open(log, "wb") as sink:
                subprocess.run(
                    [
                        str(soffice), isolated,
                        "--headless", "--norestore", "--invisible",
                        "--convert-to", "pdf", "--outdir", str(dst.parent),
                        str(src.resolve()),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=sink,
                    stderr=sink,
                    timeout=180,
                )
        except subprocess.TimeoutExpired:
            outcome[src] = "LibreOffice did not respond in time"
            continue

        produced = dst.parent / (src.stem + ".pdf")
        if produced.exists():
            if produced != dst:
                produced.replace(dst)
            outcome[src] = dst
        else:
            detail = ""
            try:
                detail = log.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                pass
            outcome[src] = detail.splitlines()[-1] if detail else (
                "LibreOffice produced no PDF"
            )
    return outcome


def describe_batch(sources: list[Path]) -> str:
    """'1 Word and 2 Excel document(s)' -- for the progress line."""
    words = sum(1 for s in sources if is_word(s))
    sheets = len(sources) - words
    parts = []
    if words:
        parts.append(f"{words} Word")
    if sheets:
        parts.append(f"{sheets} Excel")
    return f"{' and '.join(parts)} document(s)"


def convert_office_docs(sources: list[Path], work: Path, args) -> dict[Path, object]:
    """Turn Word/Excel documents into PDFs. Returns {source: pdf path or error}."""
    jobs: list[tuple[Path, Path]] = []
    for n, src in enumerate(sources, 1):
        folder = work / f"doc{n}"
        folder.mkdir(parents=True, exist_ok=True)
        jobs.append((src, folder / (src.stem + ".pdf")))

    soffice = find_libreoffice(args)
    use_office = args.converter == "office" or (
        args.converter == "auto" and sys.platform == "win32"
    )

    if use_office:
        print(f"Converting {describe_batch(sources)} with Microsoft Office...")
        if soffice:
            # The first document is converted on its own, so an Office that is
            # not answering costs that one wait and not the whole batch's --
            # quote what actually happens rather than the full batch timeout.
            print(
                f"  (if Office does not answer this waits up to 60s, "
                f"then uses LibreOffice)"
            )
        outcome, stalled = _convert_with_office(jobs, work, args)

        # Only documents whose application refused to start are worth retrying.
        retry = [(src, dst) for src, dst in jobs if office_app_for(src) in stalled]
        if not retry or args.converter != "auto":
            return outcome
        if not soffice:
            for src, _ in retry:
                outcome[src] = (
                    "no converter available -- install Microsoft Office or "
                    "LibreOffice, or save the document as PDF yourself"
                )
            return outcome
        print(f"  Office was unavailable; trying LibreOffice for {len(retry)} file(s).")
        outcome.update(_convert_with_libreoffice(retry, soffice, work))
        return outcome

    if not soffice:
        return {
            src: (
                "LibreOffice was not found -- install it, or let the tool use "
                "Microsoft Office"
            )
            for src, _ in jobs
        }

    print(f"Converting {describe_batch(sources)} with LibreOffice...")
    return _convert_with_libreoffice(jobs, soffice, work)


def pdf_path_for(src: Path, converted: dict[Path, object]) -> Path:
    """The PDF to actually read for a source: itself, or its converted copy."""
    if not needs_conversion(src):
        return src
    got = converted.get(src)
    if isinstance(got, Path):
        return got
    raise RuntimeError(str(got or "not converted"))

class Workspace:
    """Scratch space for converted documents, cleaned up however the run ends."""

    def __init__(self) -> None:
        self.dir: Path | None = None
        self.readers: list = []

    def make(self) -> Path:
        if self.dir is None:
            self.dir = Path(tempfile.mkdtemp(prefix="pdfmerge_"))
        return self.dir

    def cleanup(self, keep: bool = False) -> None:
        for reader in self.readers:  # release handles before deleting the files
            close_reader(reader)
        self.readers.clear()
        if self.dir is None:
            return
        if keep:
            print(f"Converted PDFs kept in: {self.dir}")
        else:
            shutil.rmtree(self.dir, ignore_errors=True)
        self.dir = None


def close_reader(reader) -> None:
    for target in (reader, getattr(reader, "stream", None)):
        closer = getattr(target, "close", None)
        if closer is None:
            continue
        try:
            closer()
            return
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Images -> PDF pages
# --------------------------------------------------------------------------- #

def _pillow():
    """Import Pillow on demand, so PDF-only merges never need it installed."""
    try:
        from PIL import Image, ImageOps, ImageSequence
    except ImportError:
        raise RuntimeError("Pillow is not installed. Run: python -m pip install pillow")
    return Image, ImageOps, ImageSequence


def _open_image(src: Path):
    Image, _, _ = _pillow()
    try:
        return Image.open(src)
    except Exception as exc:
        if src.suffix.lower() in (".heic", ".heif"):
            raise RuntimeError(
                "iPhone HEIC images need an extra add-on. "
                "Run: python -m pip install pillow-heif"
            ) from exc
        raise


def image_page_count(src: Path) -> int:
    """Frames in the image: 1 for a photo, more for a multi-page TIFF or a GIF."""
    with _open_image(src) as img:
        return int(getattr(img, "n_frames", 1) or 1)


def _flatten(frame, ImageOps):
    """Apply EXIF rotation and drop transparency onto white."""
    Image, _, _ = _pillow()
    frame = ImageOps.exif_transpose(frame) or frame
    if frame.mode in ("RGBA", "LA") or (frame.mode == "P" and "transparency" in frame.info):
        frame = frame.convert("RGBA")
        canvas = Image.new("RGB", frame.size, "white")
        canvas.paste(frame, mask=frame.split()[-1])
        return canvas
    return frame if frame.mode == "RGB" else frame.convert("RGB")


def _fit_to_page(src_page, page_size: tuple[float, float], margin_in: float, turn: bool):
    """Centre an image page on a given page size, scaled to fit inside the margins."""
    page_w, page_h = page_size
    img_w = float(src_page.mediabox.width)
    img_h = float(src_page.mediabox.height)

    # On a standard sheet, turn it sideways for landscape images so they fill it.
    # When matching the document's own pages we leave the orientation alone.
    if turn and img_w > img_h:
        page_w, page_h = max(page_w, page_h), min(page_w, page_h)

    margin = max(0.0, margin_in) * 72.0
    avail_w = max(page_w - 2 * margin, 1.0)
    avail_h = max(page_h - 2 * margin, 1.0)
    scale = min(avail_w / img_w, avail_h / img_h)

    sheet = PdfWriter().add_blank_page(width=page_w, height=page_h)
    sheet.merge_transformed_page(
        src_page,
        Transformation()
        .scale(scale)
        .translate((page_w - img_w * scale) / 2, (page_h - img_h * scale) / 2),
    )
    return sheet


def image_pages(src: Path, indices: list[int], args, page_size, turn: bool) -> list:
    """Render the selected frames of an image file as PDF pages.

    page_size is (width, height) in points, or None to size each page to its image.
    """
    _, ImageOps, ImageSequence = _pillow()
    wanted = set(indices)
    rendered: dict[int, object] = {}

    with _open_image(src) as img:
        for i, frame in enumerate(ImageSequence.Iterator(img)):
            if i not in wanted:
                continue
            flat = _flatten(frame, ImageOps)

            dpi = float(args.image_dpi)
            if dpi <= 0:
                info = flat.info.get("dpi") or img.info.get("dpi")
                dpi = float(info[0]) if info and info[0] else 150.0
            if dpi < 1:
                dpi = 150.0

            buf = BytesIO()
            flat.save(buf, format="PDF", resolution=dpi, quality=95)
            buf.seek(0)
            page = PdfReader(buf).pages[0]
            rendered[i] = (
                page
                if page_size is None
                else _fit_to_page(page, page_size, args.image_margin, turn)
            )

    # Follow the order the user asked for; a frame may be used more than once.
    return [rendered[i] for i in indices]


def unlock(reader, passwords=()) -> bool:
    """Try to open an encrypted reader. True when its pages can be read.

    The empty password goes first and is tried for every file: a document
    secured against editing rather than reading needs no password, and that is
    the common case for anything stamped "secured" by a court, a bank or a
    scanner. Supplied passwords are then tried in turn, so one --password can
    cover a bundle where only some files are locked.

    pypdf raises rather than returning False for some files -- a missing AES
    backend, a corrupt encryption dictionary -- so every attempt is guarded. A
    wrong password must cost you one file, not the whole merge, and the exception
    is swallowed rather than printed because its text can contain the password.
    """
    if not reader.is_encrypted:
        return True
    for candidate in ("", *passwords):
        try:
            if reader.decrypt(candidate):
                return True
        except Exception:
            continue
    return False


def dominant_page_size(items, converted: dict[Path, object], passwords=()) -> tuple[float, float] | None:
    """The page size the PDF pages in this merge agree on, in points.

    Counts every PDF page that will actually be merged and returns the most
    common (width, height), so images can be given the same sheet. Ties go to
    whichever size appeared first. Returns None when there are no PDF pages.
    """
    # Sizes are grouped on a rounded key so near-identical pages count together,
    # but the exact size of the first page in the group is what we hand back.
    tally: dict[tuple[float, float], list] = {}
    seen = 0

    for path_str, spec in items:
        src = resolve(path_str)
        if is_image(src) or not src.exists():
            continue
        reader = None
        try:
            reader = PdfReader(str(pdf_path_for(src, converted)))
            if not unlock(reader, passwords):
                continue
            for i in parse_ranges(spec, len(reader.pages), src.name):
                page = reader.pages[i]
                width = float(page.mediabox.width)
                height = float(page.mediabox.height)
                if (page.rotation or 0) % 180 == 90:
                    width, height = height, width  # a rotated page reads sideways
                key = (round(width, 1), round(height, 1))
                entry = tally.setdefault(key, [0, seen, (width, height)])
                entry[0] += 1
                seen += 1
        except Exception:
            continue  # unreadable files are reported by the merge loop itself
        finally:
            if reader is not None:
                close_reader(reader)

    if not tally:
        return None
    return max(tally.values(), key=lambda v: (v[0], -v[1]))[2]


def describe_size(page_size: tuple[float, float]) -> str:
    """'8.50 x 11.00 in (US Letter)' -- for the run summary."""
    width, height = page_size
    short, tall = min(width, height), max(width, height)
    label = None
    for (ref_w, ref_h), name in (
        ((612.0, 792.0), "US Letter"),
        ((595.28, 841.89), "A4"),
        ((612.0, 1008.0), "US Legal"),
    ):
        # Scanners and printers are a fraction of a point off; still call it A4.
        if abs(short - ref_w) <= 1.5 and abs(tall - ref_h) <= 1.5:
            label = name
            break
    if label and width > height:
        label += ", landscape"
    text = f"{width / 72:.2f} x {height / 72:.2f} in"
    return f"{text} ({label})" if label else text


# --------------------------------------------------------------------------- #
# Drawing text into a PDF (index pages and page stamps)
# --------------------------------------------------------------------------- #

# Helvetica character widths, per 1000 units of font size, for ASCII 32..126.
# One of the base-14 fonts, so it needs no embedding and no extra library.
# Digits are all 556, which is what makes right-aligned page numbers exact.
_HELVETICA = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278,
    278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584,
    584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556,
    833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278,
    278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222,
    500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500,
    500, 334, 260, 334, 584,
)


def text_width(text: str, size: float) -> float:
    """Width of a string set in Helvetica at the given point size."""
    total = 0
    for ch in text:
        code = ord(ch)
        total += _HELVETICA[code - 32] if 32 <= code <= 126 else 556
    return total * size / 1000.0


def _num(value: float) -> bytes:
    """A number as PDF source, without a pointless trailing .0."""
    return f"{value:.2f}".rstrip("0").rstrip(".").encode("ascii") or b"0"


def _pdf_string(text: str) -> bytes:
    """A PDF literal string, escaped, in WinAnsi."""
    raw = text.encode("cp1252", "replace")
    for old, new in ((b"\\", b"\\\\"), (b"(", b"\\("), (b")", b"\\)")):
        raw = raw.replace(old, new)
    return b"(" + raw + b")"


def text_overlay(width: float, height: float, items) -> bytes:
    """A one-page PDF of nothing but text, built by hand.

    items are (x, y, size, bold, text) with the origin at the bottom left.
    Assembled directly as PDF source -- a valid cross-reference table and all --
    because pypdf cannot draw text and reportlab is not a dependency here.
    """
    drawing = []
    for x, y, size, bold, text in items:
        drawing.append(
            b"BT "
            + (b"/F2 " if bold else b"/F1 ")
            + _num(size) + b" Tf 1 0 0 1 "
            + _num(x) + b" " + _num(y) + b" Tm "
            + _pdf_string(text) + b" Tj ET"
        )
    content = b"\n".join(drawing)

    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
        + _num(width) + b" " + _num(height)
        + b"] /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica"
        b" /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold"
        b" /Encoding /WinAnsiEncoding >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(bodies, 1):
        offsets.append(len(out))
        out += str(number).encode() + b" 0 obj\n" + body + b"\nendobj\n"

    xref_at = len(out)
    out += b"xref\n0 " + str(len(bodies) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        b"trailer\n<< /Size " + str(len(bodies) + 1).encode()
        + b" /Root 1 0 R >>\nstartxref\n" + str(xref_at).encode() + b"\n%%EOF\n"
    )
    return bytes(out)


def text_page(width: float, height: float, items):
    """The text overlay as a pypdf page, ready to merge or insert."""
    return PdfReader(BytesIO(text_overlay(width, height, items))).pages[0]


# --------------------------------------------------------------------------- #
# Stamping page numbers
# --------------------------------------------------------------------------- #

STAMP_SPOTS = (
    "bottom-right", "bottom-center", "bottom-left",
    "top-right", "top-center", "top-left",
)


def stamp_pages(writer: PdfWriter, args) -> int:
    """Stamp a running number onto every page. Returns how many were stamped."""
    margin = max(0.0, args.stamp_margin) * 72.0
    size = args.stamp_size
    stamped = 0

    for offset, page in enumerate(writer.pages):
        number = args.stamp_start + offset
        try:
            label = args.stamp.format(n=number, total=len(writer.pages))
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(
                f"--stamp format {args.stamp!r} is not usable ({exc}); "
                "the placeholders are {n} and {total}"
            ) from None

        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        spot = args.stamp_at

        if spot.endswith("left"):
            x = margin
        elif spot.endswith("center"):
            x = (width - text_width(label, size)) / 2
        else:
            x = width - margin - text_width(label, size)
        # Sit the baseline a little inside the margin, not exactly on it.
        y = height - margin - size if spot.startswith("top") else margin - size * 0.3

        page.merge_page(text_page(width, height, [(x, max(y, 2.0), size, False, label)]))
        stamped += 1
    return stamped


# --------------------------------------------------------------------------- #
# The index page
# --------------------------------------------------------------------------- #

def _index_rows_per_page(height: float, args, first: bool) -> int:
    """How many entries fit, leaving room for the heading on the first page."""
    margin = max(0.0, args.index_margin) * 72.0
    usable = height - 2 * margin
    if first:
        usable -= args.index_title_size + args.index_leading * 1.5
    return max(1, int(usable // args.index_leading))


def index_page_count(rows: int, page_size: tuple[float, float], args) -> int:
    """Pages the index itself needs -- which shifts every number on it."""
    height = page_size[1]
    first = _index_rows_per_page(height, args, first=True)
    if rows <= first:
        return 1
    rest = _index_rows_per_page(height, args, first=False)
    return 1 + -(-(rows - first) // rest)


def build_index_pages(sections, page_size, args, reserved: int) -> list:
    """Lay out the contents listing. sections are (title, first body page index)."""
    width, height = page_size
    margin = max(0.0, args.index_margin) * 72.0
    leading = args.index_leading
    size = args.index_size
    number_column = 45.0  # room for a 4-5 digit page number, right aligned
    right_edge = width - margin

    pages: list = []
    row = 0
    while row < len(sections) or not pages:
        first = not pages
        items: list = []
        y = height - margin

        if first:
            y -= args.index_title_size
            items.append((margin, y, args.index_title_size, True, args.index_title))
            y -= leading * 1.5

        room = _index_rows_per_page(height, args, first=first)
        for title, body_start in sections[row:row + room]:
            page_number = reserved + body_start + 1
            digits = str(page_number)
            number_x = right_edge - text_width(digits, size)

            # Trim the name if it would run into the page-number column.
            room_for_name = right_edge - number_column - margin
            name = title
            while name and text_width(name, size) > room_for_name:
                name = name[:-1]
            if name != title:
                name = name[: max(0, len(name) - 1)] + "…"

            items.append((margin, y, size, False, name))
            items.append((number_x, y, size, False, digits))

            # Dot leaders, so the eye can follow the line across.
            gap_from = margin + text_width(name, size) + 4
            gap_to = number_x - 4
            if gap_to - gap_from > 8:
                dot = text_width(".", size)
                dots = "." * int((gap_to - gap_from) // dot)
                if dots:
                    items.append((gap_from, y, size, False, dots))

            y -= leading

        row += room
        pages.append(text_page(width, height, items))
        if row >= len(sections):
            break
    return pages


# --------------------------------------------------------------------------- #
# Building the merge plan
# --------------------------------------------------------------------------- #

def collect_sources(args) -> tuple[list[tuple[str, str | None]], str]:
    """Return the (path, spec) items to merge, plus a description of where they came from."""
    if args.files:
        return [split_spec(tok) for tok in args.files], "command line"

    if ORDER_FILE.exists():
        items = []
        for raw in ORDER_FILE.read_text(encoding="utf-8-sig").splitlines():
            parsed = parse_line(raw)
            if parsed:
                items.append(parsed)
        if items:
            return items, ORDER_FILE.name

    input_dir = Path(args.input_dir) if args.input_dir else INPUT_DIR
    if input_dir == INPUT_DIR:
        input_dir.mkdir(exist_ok=True)  # self-heal a fresh copy of the tool
    wanted = {".pdf"} if args.pdf_only else SOURCE_EXTS
    pattern = "**/*" if args.recursive else "*"
    found = sorted(
        (
            p
            for p in input_dir.glob(pattern)
            if p.is_file() and p.suffix.lower() in wanted
        ),
        key=natural_key,
    )
    return [(str(p), None) for p in found], str(input_dir)


def unique_output(path: Path) -> Path:
    """Never clobber an existing merge: merged.pdf -> merged-2.pdf -> merged-3.pdf ..."""
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

# What --password stores when given no value: ask, rather than take it from the
# command line. A unique object so it cannot be confused with a real password.
PROMPT_FOR_PASSWORD = object()


def resolve_passwords(args, supplied=None) -> tuple[str, ...]:
    """Every password to try, from the keyword argument, a file, and the flags.

    `supplied` is how the window passes them: in memory, never through argv,
    because the window echoes the command line it builds into its own log.
    Order is preserved and duplicates dropped, so repeating a password costs
    nothing. Returns a tuple so it cannot be added to by accident later.
    """
    found: list[str] = list(supplied or ())

    if getattr(args, "password_file", None):
        try:
            text = Path(args.password_file).read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise SystemExit(f"Could not read {args.password_file}: {exc}") from exc
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                found.append(line)

    for value in getattr(args, "password", None) or ():
        if value is PROMPT_FOR_PASSWORD:
            import getpass

            try:
                entered = getpass.getpass("Password for the encrypted PDF(s): ")
            except (EOFError, KeyboardInterrupt):
                raise SystemExit("No password given.") from None
            if entered:
                found.append(entered)
        elif value:
            found.append(value)

    return tuple(dict.fromkeys(found))


def build_parser() -> argparse.ArgumentParser:
    """The command line, kept in one place so the GUI shares its defaults."""
    parser = argparse.ArgumentParser(
        description="Merge PDF pages into a single document.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Page ranges:  file.pdf:1-3,7   file.pdf:5-   file.pdf:-4   file.pdf:all\n"
            "Remove pages:  file.pdf:!7   file.pdf:!2-4   (~ works too)\n"
            "Bundles:  --index adds a contents page, --stamp numbers the pages\n"
            "Images (jpg, png, tiff, ...), Word documents (docx, doc, rtf, odt) and\n"
            "spreadsheets (xlsx, xls, csv, ods) become pages too, mixed in freely.\n"
            "With no arguments, merges everything in .\\input (or follows order.txt)."
        ),
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="PDFs, images, Word and Excel files, optionally with :pageranges",
    )
    parser.add_argument("-o", "--out", help="output file (default: output\\merged.pdf)")
    parser.add_argument("-i", "--input-dir", help="folder to scan instead of .\\input")
    parser.add_argument("-r", "--recursive", action="store_true", help="scan subfolders too")
    parser.add_argument("-l", "--list", action="store_true", help="show the plan, merge nothing")
    parser.add_argument("-f", "--force", action="store_true", help="overwrite the output file")
    parser.add_argument("--no-bookmarks", action="store_true", help="don't bookmark each source")
    parser.add_argument(
        "--index",
        action="store_true",
        help="put a contents page in front, listing each file and its page number",
    )
    parser.add_argument(
        "--index-title", default="Contents", metavar="TEXT",
        help="heading on the contents page (default: Contents)",
    )
    parser.add_argument(
        "--index-size", type=float, default=10.0, metavar="PT",
        help="type size for contents entries (default: 10)",
    )
    parser.add_argument(
        "--index-title-size", type=float, default=17.0, metavar="PT",
        help="type size for the contents heading (default: 17)",
    )
    parser.add_argument(
        "--index-leading", type=float, default=18.0, metavar="PT",
        help="line spacing on the contents page (default: 18)",
    )
    parser.add_argument(
        "--index-margin", type=float, default=1.0, metavar="INCHES",
        help="margin on the contents page (default: 1.0)",
    )
    parser.add_argument(
        "--stamp",
        nargs="?",
        const="{n}",
        metavar="FORMAT",
        help=(
            "stamp a page number on every page. {n} is the number and {total} the "
            "count, so --stamp \"Page {n} of {total}\" or --stamp \"ABC-{n:05d}\" "
            "for Bates numbering (default format: {n})"
        ),
    )
    parser.add_argument(
        "--stamp-at", choices=STAMP_SPOTS, default="bottom-right",
        help="where the stamp goes (default: bottom-right)",
    )
    parser.add_argument(
        "--stamp-size", type=float, default=9.0, metavar="PT",
        help="type size for the stamp (default: 9)",
    )
    parser.add_argument(
        "--stamp-start", type=int, default=1, metavar="N",
        help="number the first page N (default: 1)",
    )
    parser.add_argument(
        "--stamp-margin", type=float, default=0.5, metavar="INCHES",
        help="how far the stamp sits from the page edge (default: 0.5)",
    )
    parser.add_argument(
        "--password",
        action="append",
        nargs="?",
        const=PROMPT_FOR_PASSWORD,
        metavar="PASSWORD",
        help=(
            "password for encrypted PDFs. Give it more than once for a bundle "
            "with different passwords; each is tried in turn. Pass --password "
            "with no value to be asked for it without it appearing on screen, "
            "in your shell history or in the process list -- which is the safer "
            "way to do it"
        ),
    )
    parser.add_argument(
        "--password-file",
        metavar="PATH",
        help=(
            "read passwords from a file, one per line, keeping them out of the "
            "command line. Blank lines and lines starting with # are ignored"
        ),
    )
    parser.add_argument(
        "--pdf-only",
        action="store_true",
        help="ignore images, Word and Excel files when scanning a folder",
    )
    parser.add_argument(
        "--converter",
        choices=("auto", "office", "libreoffice"),
        default="auto",
        help="what turns Word/Excel files into PDF (default: auto)",
    )
    parser.add_argument(
        "--soffice",
        metavar="PATH",
        help="where LibreOffice lives, if it is somewhere unusual",
    )
    parser.add_argument(
        "--keep-converted",
        action="store_true",
        help="keep the PDFs made from Word/Excel files instead of deleting them",
    )
    parser.add_argument(
        "--excel-fit",
        choices=("as-is", "width", "page"),
        default="as-is",
        help=(
            "how spreadsheets are laid out: 'as-is' uses the workbook's own print "
            "setup, 'width' squeezes every sheet to one page wide, 'page' puts "
            "each sheet on a single page (default: as-is)"
        ),
    )
    parser.add_argument(
        "--image-page",
        choices=("match", "letter", "a4", "legal", "exact"),
        default="match",
        help=(
            "page size for images: 'match' uses the same size as the PDF pages in "
            "the merge, 'exact' sizes the page to the image (default: match)"
        ),
    )
    parser.add_argument(
        "--image-margin",
        type=float,
        default=0.25,
        metavar="INCHES",
        help="white border around images on a fixed page size (default: 0.25)",
    )
    parser.add_argument(
        "--image-dpi",
        type=float,
        default=0,
        metavar="DPI",
        help="resolution for 'exact' pages; 0 = use the image's own (default: 0)",
    )
    return parser


def main(argv=None, passwords=None) -> int:
    """`passwords` is for callers in the same process -- the window uses it so a
    password never reaches argv, which it echoes and which anything that can list
    processes can read."""
    args = build_parser().parse_args(argv)
    args.passwords = resolve_passwords(args, passwords)

    state = Workspace()
    try:
        return run(args, state)
    finally:
        state.cleanup(keep=args.keep_converted)


def run(args, state: Workspace) -> int:
    """Do the merge. Split out so temporary files are cleaned up however it ends."""
    items, origin = collect_sources(args)

    if not items:
        kinds = "PDFs" if args.pdf_only else "PDFs, images, Word or Excel files"
        print(f"No {kinds} found in {origin}.")
        print(f"Drop your files into: {INPUT_DIR}")
        return 1

    # Word and Excel files become PDFs first, in one batch so Office starts once.
    converted: dict[Path, object] = {}
    office_sources: list[Path] = []
    for path_str, _ in items:
        src = resolve(path_str)
        if needs_conversion(src) and src.exists() and src not in office_sources:
            office_sources.append(src)
    if office_sources:
        converted = convert_office_docs(office_sources, state.make(), args)

    # Work out the sheet images go on, before merging anything.
    image_size: tuple[float, float] | None = None
    turn_sheet = False
    notes: list[str] = []
    if any(is_image(resolve(p)) for p, _ in items):
        if args.image_page == "exact":
            notes.append("Image pages: sized to each image")
        elif args.image_page == "match":
            image_size = dominant_page_size(items, converted, args.passwords)
            if image_size is None:
                image_size = PAGE_SIZES["letter"]
                turn_sheet = True
                notes.append(f"Image pages: {describe_size(image_size)} - no PDF pages to match")
            else:
                notes.append(f"Image pages: {describe_size(image_size)} - matching the PDF pages")
        else:
            image_size = PAGE_SIZES[args.image_page]
            turn_sheet = True
            notes.append(f"Image pages: {describe_size(image_size)}")

    print(f"Source: {origin}")
    for note in notes:
        print(note)
    print("-" * 62)

    writer = PdfWriter()
    total = 0
    problems: list[str] = []
    sections: list[tuple[str, int]] = []  # (name, first page) for the index

    for path_str, spec in items:
        src = resolve(path_str)
        label = src.name

        if not src.exists():
            problems.append(f"missing file: {src}")
            print(f"  [skip] {src}  -- not found")
            continue

        picture = is_image(src)

        try:
            if picture:
                n_pages = image_page_count(src)
                indices = parse_ranges(spec, n_pages, label)
                pages = (
                    []
                    if args.list
                    else image_pages(src, indices, args, image_size, turn_sheet)
                )
            else:
                reader = PdfReader(str(pdf_path_for(src, converted)))
                if needs_conversion(src):
                    state.readers.append(reader)  # closed before the temp files go
                if not unlock(reader, args.passwords):
                    hint = "" if args.passwords else " (try --password)"
                    problems.append(f"password protected: {label}")
                    print(f"  [skip] {label}  -- password protected{hint}")
                    continue
                n_pages = len(reader.pages)
                indices = parse_ranges(spec, n_pages, label)
                pages = [] if args.list else [reader.pages[i] for i in indices]
        except ValueError as exc:
            problems.append(str(exc))
            print(f"  [skip] {exc}")
            continue
        except RuntimeError as exc:  # a document that would not convert
            problems.append(f"{label}: {exc}")
            print(f"  [skip] {label}  -- {exc}")
            continue
        except Exception as exc:
            problems.append(f"{label}: {exc}")
            print(f"  [skip] {label}  -- could not read ({exc})")
            continue

        if picture and n_pages == 1 and not spec:
            print(f"  {label}   image   ->  1 page")
        else:
            shown = describe_spec(spec, n_pages)
            print(f"  {label}   pages {shown}   ->  {len(indices)} page(s)")

        if not args.list:
            start_at = len(writer.pages)
            for page in pages:
                writer.add_page(page)
            if not args.no_bookmarks:
                writer.add_outline_item(src.stem, start_at)
            sections.append((src.stem, start_at))
        total += len(indices)

    print("-" * 62)

    if total == 0:
        print("Nothing to merge.")
        return 1

    if args.list:
        print(f"Plan: {total} page(s) from {len(items)} source(s). Nothing written (--list).")
        return 0

    if args.index and sections:
        sheet = (
            image_size
            or dominant_page_size(items, converted, args.passwords)
            or PAGE_SIZES["letter"]
        )
        # The index shifts every page after it, including the numbers printed on
        # the index, so settle on its length before laying it out.
        reserved = index_page_count(len(sections), sheet, args)
        for _ in range(2):  # converges immediately; a second pass is belt and braces
            pages = build_index_pages(sections, sheet, args, reserved)
            if len(pages) == reserved:
                break
            reserved = len(pages)
        for position, page in enumerate(pages):
            writer.insert_page(page, position)
        entries = "entry" if len(sections) == 1 else "entries"
        sheets = "page" if len(pages) == 1 else "pages"
        print(f"Index: {len(sections)} {entries} on {len(pages)} {sheets}")

    if args.stamp:
        try:
            stamp_pages(writer, args)
        except ValueError as exc:
            print(f"Not stamped -- {exc}")
            return 1
        print(f"Stamped {len(writer.pages)} page(s) with '{args.stamp}'")

    out_path = Path(args.out) if args.out else writable_output_dir() / "merged.pdf"
    if args.out and not out_path.is_absolute():
        out_path = Path.cwd() / out_path
    if out_path.suffix.lower() != ".pdf":
        out_path = out_path.with_suffix(".pdf")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.force:
        out_path = unique_output(out_path)

    with open(out_path, "wb") as fh:
        writer.write(fh)

    size_kb = out_path.stat().st_size / 1024
    written = len(writer.pages)
    tally = (
        f"{total} page(s)"
        if written == total
        else f"{total} page(s) + {written - total} index = {written}"
    )
    print(f"Merged {tally}  ->  {out_path}   ({size_kb:,.0f} KB)")

    if problems:
        print()
        print(f"Finished with {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
