<#
.SYNOPSIS
    Publish the current state of main to the public repository.

.DESCRIPTION
    The public repository has its own history, starting from a single squashed
    commit, and shares no ancestry with this one. The two cannot be merged and
    main must never be pushed to it. This script does the only correct thing:
    it makes the public branch's *tree* match main, removes the files listed in
    not-published.txt, checks that nothing they contain has leaked in by another
    route, and commits.

    Run it from anywhere in the repository. It leaves you back on the branch you
    started on.

.PARAMETER Message
    The commit message for the public branch. Required: the public history is
    read by strangers and "sync" tells them nothing.

.PARAMETER Push
    Actually push. Without it the script stops after committing locally and
    prints what it would push, which is the point -- the published tree is worth
    looking at before it leaves.

.EXAMPLE
    .\packaging\publish.ps1 -Message "Add the password option"
    .\packaging\publish.ps1 -Message "Add the password option" -Push
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Message,
    [switch]$Push,
    [string]$Branch = 'public-release',
    [string]$Remote = 'public'
)

$ErrorActionPreference = 'Stop'
$Packaging    = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot  = Split-Path -Parent $Packaging

function Write-Step { param($t) Write-Host "`n>>> $t" -ForegroundColor Cyan }
function Write-Note { param($t) Write-Host "    $t" -ForegroundColor DarkGray }

function Get-DerivedPrivateStrings {
    <#
    .SYNOPSIS
        Work out what must not be published from the documents being held back.

    .DESCRIPTION
        The company number and the registered office live in the very documents
        this script removes, and this repository always has them -- it is the
        only place publishing happens from. So rather than depending on a
        hand-written list, derive the strings to sweep for from the documents
        themselves.

        They are read out of the source branch with `git show`, not from disk:
        by the time the sweep runs they have been deleted from the working tree,
        which is the whole point of the exercise.

        This is what makes private-strings.txt supplementary rather than
        load-bearing. That file is gitignored -- a published list of what must
        not be published would defeat the point -- so it does not survive a
        fresh clone, and the sweep it feeds is the half that caught a leak the
        generic postcode pattern missed. Deriving removes that dependency.

        Fragments, not whole addresses: a fragment still matches a reformatted
        version, which is how an address usually escapes.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$SourceBranch,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Documents
    )

    $strings = @()
    foreach ($doc in $Documents) {
        if ($doc -notlike '*.md') { continue }

        # ls-tree first: `git show` on a path that is not in the branch writes
        # to stderr, and in PowerShell 5.1 that is noise at best.
        $present = & git ls-tree --name-only $SourceBranch -- $doc
        if (-not $present) { continue }

        $text = (& git show "${SourceBranch}:${doc}") -join "`n"
        if (-not $text) { continue }

        # The company registration number.
        foreach ($m in [regex]::Matches($text, 'under number\s+(\d{6,8})')) {
            $strings += $m.Groups[1].Value
        }

        # The registered office, as comma-separated fragments. The clause runs
        # to the end of its paragraph and may carry a trailing parenthetical --
        # '("we", "us", "our")' in the terms -- so cut that off before splitting.
        foreach ($m in [regex]::Matches($text, 'registered office is at\s+([\s\S]+?)\r?\n\r?\n')) {
            $office = ($m.Groups[1].Value -replace '\s+', ' ').Trim()
            $paren = $office.IndexOf(' ("')
            if ($paren -gt 0) { $office = $office.Substring(0, $paren) }
            $office = $office.TrimEnd('.', ' ')
            foreach ($part in $office.Split(',')) {
                $fragment = $part.Trim()
                # Five characters filters out noise without losing a short
                # locality or a postcode; a bare number would be matched by the
                # company-number rule above if it mattered.
                if ($fragment.Length -ge 5) { $strings += $fragment }
            }
        }
    }
    # Both documents carry the same licensor details, so dedupe here rather than
    # reporting "10 strings" for five.
    return @($strings | Sort-Object -Unique)
}

Push-Location $ProjectRoot
try {
    # --- The branch we came from, to return to. ------------------------------
    $startBranch = (& git rev-parse --abbrev-ref HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Not a git repository." }

    $dirty = & git status --porcelain
    if ($dirty) {
        throw ("The working tree has uncommitted changes. Commit or stash them " +
               "first -- this script switches branches and would carry them across.")
    }

    # --- The exclusion list. -------------------------------------------------
    $listFile = Join-Path $Packaging 'not-published.txt'
    if (-not (Test-Path $listFile)) { throw "not-published.txt is missing." }
    $excluded = Get-Content $listFile |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and -not $_.StartsWith('#') }
    if (-not $excluded) { throw "not-published.txt lists nothing. If that is deliberate, delete this check." }
    Write-Step "Not publishing"
    foreach ($path in $excluded) { Write-Note $path }

    # --- Make the public branch's tree match main. ---------------------------
    Write-Step "Updating $Branch from $startBranch"
    & git checkout --quiet $Branch
    if ($LASTEXITCODE -ne 0) { throw "Could not switch to $Branch. It is the public history -- do not delete it." }

    try {
        & git restore --source=$startBranch --worktree --staged .
        if ($LASTEXITCODE -ne 0) { throw "Could not copy the tree from $startBranch." }

        foreach ($path in $excluded) {
            if (Test-Path $path) {
                & git rm --quiet --force $path
                if ($LASTEXITCODE -ne 0) { throw "Could not remove $path from $Branch." }
            }
        }

        # --- The guards that actually matter. --------------------------------
        # Removing the listed paths is necessary but nowhere near sufficient: the
        # point is to keep the registered office out of the public repository,
        # and it can arrive in a file nobody thought about. It did, the first
        # time this ran -- a test asserting the literal company number and street
        # name, in a file that is published.
        #
        # So two sweeps. A generic pattern catches generically-shaped things,
        # which is cheap and needs no list. The literal strings are derived from
        # the held-back documents themselves -- they are the authority for what
        # the address is, and this repository always has them. private-strings.txt
        # adds anything derivation cannot see, and is optional.
        Write-Step "Checking the tree for anything that should not be published"
        $leaks = @()

        $derived = Get-DerivedPrivateStrings -SourceBranch $startBranch -Documents $excluded
        if ($derived) {
            Write-Note "$($derived.Count) string(s) derived from the held-back documents"
        } else {
            Write-Host "    Nothing could be derived from the held-back documents." -ForegroundColor Yellow
            Write-Host "    If they no longer carry a company number and registered office," -ForegroundColor Yellow
            Write-Host "    that is fine; if they do, the patterns in" -ForegroundColor Yellow
            Write-Host "    Get-DerivedPrivateStrings have stopped matching and this sweep is" -ForegroundColor Yellow
            Write-Host "    not doing its job." -ForegroundColor Yellow
        }

        $extra = @()
        $stringsFile = Join-Path $Packaging 'private-strings.txt'
        if (Test-Path $stringsFile) {
            $extra = Get-Content $stringsFile |
                ForEach-Object { $_.Trim() } |
                Where-Object { $_ -and -not $_.StartsWith('#') }
            if ($extra) { Write-Note "$($extra.Count) more from private-strings.txt" }
        }

        $private = @($derived + $extra) | Sort-Object -Unique
        $postcode = '\b[A-Z]{1,2}[0-9][A-Z0-9]? ?[0-9][A-Z]{2}\b'

        foreach ($file in (& git ls-files)) {
            if (-not (Test-Path -LiteralPath $file)) { continue }
            $raw = Get-Content -LiteralPath $file -Raw -ErrorAction SilentlyContinue
            if ($null -eq $raw) { continue }
            foreach ($m in [regex]::Matches($raw, $postcode)) {
                $leaks += "$file : $($m.Value)  (postcode-shaped)"
            }
            foreach ($needle in $private) {
                # Named in the message: a false positive is useless to diagnose
                # otherwise, and the fragments are derived rather than secret to
                # whoever is running this.
                if ($raw -like "*$needle*") { $leaks += "$file : contains `"$needle`"" }
            }
        }

        if ($leaks) {
            throw ("The tree about to be published contains:`n    " +
                   (($leaks | Sort-Object -Unique) -join "`n    ") +
                   "`nTake it out, or add the file to not-published.txt. If it is a false " +
                   "positive, narrow the derivation in Get-DerivedPrivateStrings deliberately " +
                   "rather than deleting the check.")
        }
        Write-Note "nothing found"

        # --- Commit. -------------------------------------------------------------
        $staged = & git diff --cached --name-status
        if (-not $staged) {
            Write-Step "Nothing to publish"
            Write-Note "$Branch already matches $startBranch, less the excluded files."
            return
        }
        Write-Step "Publishing"
        foreach ($line in $staged) { Write-Note $line }
        & git commit --quiet --message $Message
        if ($LASTEXITCODE -ne 0) { throw "The commit failed." }
        Write-Note ("committed " + (& git rev-parse --short HEAD).Trim())

        if ($Push) {
            & git push $Remote "${Branch}:main"
            if ($LASTEXITCODE -ne 0) {
                throw ("The push was rejected. That is the safety net working, not a " +
                       "problem to force past -- re-read `"Publishing`" in packaging\README.md.")
            }
            Write-Host "`n=== Pushed to $Remote ===" -ForegroundColor Green
        } else {
            Write-Host "`n=== Committed, not pushed ===" -ForegroundColor Yellow
            Write-Host "    Review it, then run the same command with -Push." -ForegroundColor Yellow
        }
    }
    finally {
        & git checkout --quiet $startBranch
        Write-Note "back on $startBranch"
    }
}
finally {
    Pop-Location
}
