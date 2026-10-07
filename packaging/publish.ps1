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
        # So two sweeps. A generic pattern catches generically-shaped things; the
        # literal strings have to be named somewhere, and the only safe somewhere
        # is a file that stays in this repository. private-strings.txt is
        # gitignored for that reason -- a published list of what must not be
        # published would rather defeat the point.
        Write-Step "Checking the tree for anything that should not be published"
        $leaks = @()

        $postcode = '\b[A-Z]{1,2}[0-9][A-Z0-9]? ?[0-9][A-Z]{2}\b'
        foreach ($file in (& git ls-files)) {
            if (-not (Test-Path -LiteralPath $file)) { continue }
            $raw = Get-Content -LiteralPath $file -Raw -ErrorAction SilentlyContinue
            if ($null -eq $raw) { continue }
            foreach ($m in [regex]::Matches($raw, $postcode)) {
                $leaks += "$file : $($m.Value)  (postcode-shaped)"
            }
        }

        $stringsFile = Join-Path $Packaging 'private-strings.txt'
        if (Test-Path $stringsFile) {
            $private = Get-Content $stringsFile |
                ForEach-Object { $_.Trim() } |
                Where-Object { $_ -and -not $_.StartsWith('#') }
            Write-Note "$($private.Count) literal string(s) from private-strings.txt"
            foreach ($file in (& git ls-files)) {
                if (-not (Test-Path -LiteralPath $file)) { continue }
                $raw = Get-Content -LiteralPath $file -Raw -ErrorAction SilentlyContinue
                if ($null -eq $raw) { continue }
                foreach ($needle in $private) {
                    if ($raw -like "*$needle*") { $leaks += "$file : contains a private string" }
                }
            }
        } else {
            Write-Host "    private-strings.txt is missing, so only the generic sweep ran." -ForegroundColor Yellow
            Write-Host "    It is gitignored and does not survive a fresh clone -- see" -ForegroundColor Yellow
            Write-Host "    BUSINESS-NOTES.md. Recreate it before relying on this check." -ForegroundColor Yellow
        }

        if ($leaks) {
            throw ("The tree about to be published contains:`n    " +
                   (($leaks | Sort-Object -Unique) -join "`n    ") +
                   "`nTake it out, or add the file to not-published.txt. If it is a false " +
                   "positive, widen the check deliberately rather than deleting it.")
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
