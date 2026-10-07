<#
.SYNOPSIS
    Build, sign and package the PDF Page Merger.

.DESCRIPTION
    Runs the four steps in the order that matters:

        1. PyInstaller  -> dist\PDF Page Merger\  (programs + bundled Python)
        2. Sign the executables
        3. Inno Setup   -> dist\installer\PDFPageMerger-<version>-Setup.exe
        4. Sign the installer

    Steps 2 and 4 are both needed. Signing only the installer leaves the
    programs inside it unsigned, so the first thing a user runs after
    installing is an unsigned executable.

    There are two ways to sign. With a certificate in the Windows certificate
    store or a .pfx, signing uses Set-AuthenticodeSignature, which is part of
    Windows -- no Windows SDK, no signtool.exe. With Azure Artifact Signing
    (formerly Trusted Signing) the key lives in Microsoft's HSM and there is no
    local certificate, so signing goes through signtool.exe with their dlib
    provider; that route needs the Windows SDK installed.

    See "Getting a real certificate" in packaging\README.md for the choice
    between them.

.PARAMETER CertificateThumbprint
    Thumbprint of a code signing certificate in your certificate store. Find it
    with:  Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert

.PARAMETER PfxPath
    Alternatively, a .pfx file. You will be prompted for its password.

.PARAMETER AzureSigningAccount
    Azure Artifact Signing: the signing account name. Passing this selects the
    Azure route, and -AzureCertificateProfile and -AzureEndpoint come with it.
    Authentication is whatever DefaultAzureCredential finds -- `az login` is the
    usual answer.

.PARAMETER AzureCertificateProfile
    The certificate profile within that account. Its subject is what customers
    see as the publisher, so it has to match AppPublisher in installer.iss.

.PARAMETER AzureEndpoint
    The regional endpoint, e.g. https://weu.codesigning.azure.net/ for West
    Europe. Region-specific: the wrong one fails to authenticate rather than
    redirecting.

.PARAMETER TrustedSigningDlib
    Path to Azure.CodeSigning.Dlib.dll. Found automatically in .tools\ or in the
    NuGet package cache; pass it if it lives somewhere else.

.PARAMETER SignToolPath
    Path to signtool.exe. Found automatically in the Windows Kits; pass it to
    override.

.PARAMETER TimestampUrl
    Timestamp server. Signatures without a timestamp stop validating the day the
    certificate expires; with one they remain valid indefinitely.

.PARAMETER SkipSign
    Build without signing, for a quick test.

.PARAMETER SkipTests
    Build even though the test suite fails. Prints a warning; use sparingly.

.EXAMPLE
    .\packaging\build.ps1 -SkipSign

.EXAMPLE
    .\packaging\build.ps1 -CertificateThumbprint A1B2C3D4E5F60718293A4B5C6D7E8F9012345678

.EXAMPLE
    .\packaging\build.ps1 -AzureSigningAccount mysigningaccount `
                           -AzureCertificateProfile myprofile `
                           -AzureEndpoint https://weu.codesigning.azure.net/
#>

[CmdletBinding()]
param(
    [string]$CertificateThumbprint,
    [string]$PfxPath,
    [string]$AzureSigningAccount,
    [string]$AzureCertificateProfile,
    [string]$AzureEndpoint,
    [string]$TrustedSigningDlib,
    [string]$SignToolPath,
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [switch]$SkipSign,
    [switch]$SkipInstaller,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Packaging   = $PSScriptRoot
$AppName     = 'PDF Page Merger'
$DistApp     = Join-Path $ProjectRoot "dist\$AppName"

function Write-Step  { param([string]$Text) Write-Host "`n=== $Text ===" -ForegroundColor Cyan }
function Write-Note  { param([string]$Text) Write-Host "    $Text" -ForegroundColor DarkGray }

function Invoke-Native {
    # Windows PowerShell 5.1 turns a native command's stderr into ErrorRecords as
    # soon as the caller redirects streams -- so piping this script to a log file
    # (build.ps1 -SkipSign 2>&1 | Tee-Object build.log) would otherwise abort the
    # build on PyInstaller's ordinary INFO output, because of the 'Stop'
    # preference set at the top. The exit code is what actually matters, and
    # every caller below checks $LASTEXITCODE.
    param(
        [Parameter(Mandatory)][string]$Exe,
        [string[]]$Arguments = @()
    )
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Exe @Arguments } finally { $ErrorActionPreference = $saved }
}

# --------------------------------------------------------------------------- #
# What we need before starting
# --------------------------------------------------------------------------- #

function Find-InnoSetup {
    # The project's own portable copy wins, for the same reason .python\ exists:
    # a release build should not depend on what happens to be installed
    # machine-wide. See PROJECT-NOTES.md, "The build environment".
    $local = Join-Path $ProjectRoot '.tools\InnoSetup\ISCC.exe'
    if (Test-Path $local) { return $local }

    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    $onPath = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
    if ($onPath) { $candidates = @($onPath) + $candidates }
    foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { return $c } }
    return $null
}

function Find-Python {
    # Likewise: prefer .python\, because `python` on PATH may be an interpreter
    # shared with another project, and PyInstaller bundles from the environment
    # it runs in.
    $local = Join-Path $ProjectRoot '.python\python.exe'
    if (Test-Path $local) { return $local }
    return (Get-Command python -ErrorAction SilentlyContinue).Source
}

function Get-SigningCertificate {
    if ($PfxPath) {
        if (-not (Test-Path $PfxPath)) { throw "No .pfx at $PfxPath" }
        $password = Read-Host -Prompt "Password for $(Split-Path -Leaf $PfxPath)" -AsSecureString
        return Get-PfxCertificate -FilePath $PfxPath -Password $password
    }
    if ($CertificateThumbprint) {
        $clean = $CertificateThumbprint -replace '[^0-9A-Fa-f]', ''
        foreach ($store in 'Cert:\CurrentUser\My', 'Cert:\LocalMachine\My') {
            $found = Get-ChildItem $store -ErrorAction SilentlyContinue |
                     Where-Object { $_.Thumbprint -eq $clean }
            if ($found) { return $found[0] }
        }
        throw "No certificate with thumbprint $clean in your certificate stores."
    }
    $any = @(Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction SilentlyContinue)
    if ($any.Count -eq 1) {
        Write-Note "Using the only code signing certificate found: $($any[0].Subject)"
        return $any[0]
    }
    if ($any.Count -gt 1) {
        throw "Several code signing certificates found. Pass -CertificateThumbprint to choose one."
    }
    throw "No code signing certificate found. Pass -CertificateThumbprint or -PfxPath, or use -SkipSign."
}

function Find-SignTool {
    if ($SignToolPath) {
        if (-not (Test-Path $SignToolPath)) { throw "No signtool.exe at $SignToolPath" }
        return $SignToolPath
    }
    # Newest SDK first: the x64 build, which is what the dlib is built against.
    $roots = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
        "$env:ProgramFiles\Windows Kits\10\bin"
    )
    $found = foreach ($root in $roots) {
        if (Test-Path $root) {
            Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending |
                ForEach-Object { Join-Path $_.FullName 'x64\signtool.exe' } |
                Where-Object { Test-Path $_ }
        }
    }
    if ($found) { return @($found)[0] }
    $onPath = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
    if ($onPath) { return $onPath }
    return $null
}

function Find-TrustedSigningDlib {
    if ($TrustedSigningDlib) {
        if (-not (Test-Path $TrustedSigningDlib)) { throw "No dlib at $TrustedSigningDlib" }
        return $TrustedSigningDlib
    }
    # .tools\ first, matching how Inno Setup is kept with the project rather than
    # depending on a machine-wide install.
    $candidates = @(
        (Join-Path $Packaging '..\.tools\TrustedSigning\bin\x64\Azure.CodeSigning.Dlib.dll'),
        (Join-Path $Packaging '..\.tools\TrustedSigning\Azure.CodeSigning.Dlib.dll')
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return (Resolve-Path $c).Path } }

    $nuget = Join-Path $env:USERPROFILE '.nuget\packages\microsoft.trusted.signing.client'
    if (Test-Path $nuget) {
        $newest = Get-ChildItem $nuget -Directory -ErrorAction SilentlyContinue |
                  Sort-Object Name -Descending |
                  ForEach-Object { Join-Path $_.FullName 'bin\x64\Azure.CodeSigning.Dlib.dll' } |
                  Where-Object { Test-Path $_ }
        if ($newest) { return @($newest)[0] }
    }
    return $null
}

function Invoke-SignToolSigning {
    <#
        Azure Artifact Signing. The key is in Microsoft's HSM, so there is no
        local certificate and Set-AuthenticodeSignature cannot reach it --
        signtool loads their dlib, which authenticates with
        DefaultAzureCredential and asks the service to sign the digest.

        The account and profile go in a JSON file rather than on the command
        line, which is signtool's interface, not a choice. It is written per
        call and deleted afterwards: it names the signing account, and a stray
        copy in the project folder is the kind of thing that ends up committed.
    #>
    param([string[]]$Paths)

    $metadata = Join-Path ([System.IO.Path]::GetTempPath()) "acs-$PID-$(Get-Random).json"
    $body = [ordered]@{
        Endpoint                = $AzureEndpoint
        CodeSigningAccountName  = $AzureSigningAccount
        CertificateProfileName  = $AzureCertificateProfile
    }
    # ASCII, not UTF8: PowerShell 5.1 writes a BOM with Out-File/Set-Content
    # -Encoding utf8, and signtool's parser chokes on it.
    $body | ConvertTo-Json | Set-Content -LiteralPath $metadata -Encoding ascii
    try {
        foreach ($path in $Paths) {
            Invoke-Native $script:signtool @(
                'sign', '/v',
                '/fd', 'SHA256',
                '/tr', $TimestampUrl,
                '/td', 'SHA256',
                '/dlib', $script:dlib,
                '/dmdf', $metadata,
                $path
            )
            if ($LASTEXITCODE -ne 0) {
                throw ("signtool could not sign $(Split-Path -Leaf $path) (exit " +
                       "$LASTEXITCODE). If it is an authentication failure, run " +
                       "`az login`; if it is the endpoint, check the region.")
            }
            Write-Note "signed  $(Split-Path -Leaf $path)"
        }
    }
    finally {
        Remove-Item -LiteralPath $metadata -Force -ErrorAction SilentlyContinue
    }
}

function Assert-PublisherMatches {
    <#
        The mismatch this catches reaches the customer as one name in the
        licence terms and another in the UAC prompt. installer.iss's
        AppPublisher and the spec's COMPANY are kept together by
        TestTheTwoFilesAgree, but neither can be checked against a certificate
        until there is one -- which is now, just after signing.

        It only throws when the signature is Valid. A self-signed certificate
        from New-TestCertificate.ps1 reads as UnknownError and will not carry
        the company name, and demanding it there would break the test workflow
        the packaging README documents -- the same trap that once made
        Invoke-Signing reject self-signed certificates outright.
    #>
    param([string]$Path)

    $check = Get-AuthenticodeSignature -FilePath $Path
    $subject = $check.SignerCertificate.Subject
    $iss = Get-Content (Join-Path $Packaging 'installer.iss') -Raw
    $match = [regex]::Match($iss, '(?m)^#define\s+AppPublisher\s+"([^"]*)"')
    if (-not $match.Success) { throw "installer.iss has no #define AppPublisher." }
    $publisher = $match.Groups[1].Value

    if ($subject -and $subject -like "*$publisher*") {
        Write-Note "publisher  : matches AppPublisher"
        return
    }
    $complaint = ("The signature names $subject, but installer.iss declares " +
                  "AppPublisher `"$publisher`". A customer would read one name in " +
                  "the terms and see another in the UAC prompt.")
    if ($check.Status -eq 'Valid') { throw $complaint }
    Write-Host "    $complaint" -ForegroundColor Yellow
    Write-Host "    Not fatal because the signature is $($check.Status), which is what a" -ForegroundColor Yellow
    Write-Host "    self-signed test certificate reads as. It would be fatal for a real one." -ForegroundColor Yellow
}

function Invoke-Signing {
    param([string[]]$Paths, $Certificate)
    foreach ($path in $Paths) {
        $result = Set-AuthenticodeSignature -FilePath $path -Certificate $Certificate `
                    -HashAlgorithm SHA256 -TimestampServer $TimestampUrl `
                    -IncludeChain All

        # Status answers "is this certificate's chain trusted on THIS machine",
        # not "was the signature written". A self-signed certificate always comes
        # back UnknownError even though the file is properly signed -- so
        # demanding 'Valid' here made the workflow that New-TestCertificate.ps1
        # prints impossible, while the signature check near the end of this same
        # script expects exactly that status. What matters is whether the file now
        # carries a signature from the certificate we just used.
        $applied = $result.SignerCertificate -and
                   $result.SignerCertificate.Thumbprint -eq $Certificate.Thumbprint
        if (-not $applied) {
            throw "Signing failed for $(Split-Path -Leaf $path): $($result.Status) -- $($result.StatusMessage)"
        }

        if ($result.Status -eq 'Valid') {
            Write-Note "signed  $(Split-Path -Leaf $path)"
        } else {
            Write-Note "signed  $(Split-Path -Leaf $path)  [$($result.Status): the certificate is not trusted on this machine]"
        }
    }
}

# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #

Write-Step "Checking the tools"

$python = Find-Python
if (-not $python) {
    throw "No Python found: neither .python\python.exe nor python on PATH."
}
Invoke-Native $python @('-c', 'import PyInstaller') 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed in $python. Run:  & '$python' -m pip install -r requirements-build.txt"
}
Write-Note "python: $python"
Write-Note "PyInstaller present"

$iscc = Find-InnoSetup
if (-not $iscc -and -not $SkipInstaller) {
    throw "Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php, or pass -SkipInstaller."
}
if ($iscc) { Write-Note "Inno Setup: $iscc" }

# $signing is what the gates below key off -- the placeholder scan, the
# missing-document refusal, both signing steps. $certificate is the X509 object
# and exists only on the certificate route, because Azure Artifact Signing has no
# local certificate at all. Conflating the two, as this script did while there
# was only one route, would let an Azure-signed build past every gate that exists
# to stop an unfinished build reaching a customer.
$signing     = -not $SkipSign
$azureRoute  = [bool]$AzureSigningAccount
$certificate = $null
$script:signtool = $null
$script:dlib     = $null

if ($signing -and $azureRoute) {
    foreach ($pair in @(@('-AzureCertificateProfile', $AzureCertificateProfile),
                        @('-AzureEndpoint', $AzureEndpoint))) {
        if (-not $pair[1]) { throw "$($pair[0]) is required with -AzureSigningAccount." }
    }
    if ($CertificateThumbprint -or $PfxPath) {
        throw ("Pass either -AzureSigningAccount or a local certificate, not both. " +
               "They are different signing routes and only one can apply.")
    }
    $script:signtool = Find-SignTool
    if (-not $script:signtool) {
        throw ("signtool.exe not found. Azure Artifact Signing goes through it, so " +
               "the Windows SDK is required for this route -- or pass -SignToolPath. " +
               "The certificate route needs neither.")
    }
    $script:dlib = Find-TrustedSigningDlib
    if (-not $script:dlib) {
        throw ("Azure.CodeSigning.Dlib.dll not found. Install it with:  nuget install " +
               "Microsoft.Trusted.Signing.Client  -- or pass -TrustedSigningDlib.")
    }
    # Microsoft's service requires its own timestamp authority; the DigiCert
    # default is for the certificate route. Only overridden when the caller did
    # not ask for a specific one.
    if (-not $PSBoundParameters.ContainsKey('TimestampUrl')) {
        $TimestampUrl = 'http://timestamp.acs.microsoft.com'
    }
    Write-Note "signing    : Azure Artifact Signing"
    Write-Note "account    : $AzureSigningAccount / $AzureCertificateProfile"
    Write-Note "signtool   : $script:signtool"
    Write-Note "dlib       : $script:dlib"
    Write-Note "timestamp  : $TimestampUrl"
} elseif ($signing) {
    $certificate = Get-SigningCertificate
    Write-Note "certificate: $($certificate.Subject)"
    Write-Note "expires    : $($certificate.NotAfter)"
    if ($certificate.NotAfter -lt (Get-Date)) { throw "That certificate has expired." }
    if (-not $certificate.HasPrivateKey) { throw "That certificate has no private key, so it cannot sign." }
} else {
    Write-Host "    NOT SIGNING -- the result will warn users on download and install." -ForegroundColor Yellow
}

if (-not (Test-Path (Join-Path $Packaging 'icon.ico'))) {
    Write-Step "Drawing the icon"
    Invoke-Native $python @((Join-Path $Packaging 'make_icon.py'))
}

# Always regenerated, never trusted from last time. THIRD-PARTY-NOTICES.txt is
# assembled from the licence texts in .python\, so rebuilding the build
# environment with a newer pypdf or Pillow would otherwise leave the shipped
# notices quietly describing versions that are no longer in the box -- and the
# whole point of them is to be accurate. Cheap enough to do every time.
# Before anything is built, not after. The suite takes a second or two and has
# already caught one real bug; shipping a build whose tests fail is the one
# outcome worth making awkward. -SkipTests exists for when you need a binary in
# spite of that, and says so loudly.
if ($SkipTests) {
    Write-Host "    TESTS SKIPPED -- the result is unverified." -ForegroundColor Yellow
} else {
    Write-Step "Running the tests"
    Invoke-Native $python @('-m', 'pytest')
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed. Fix them, or pass -SkipTests if you need this build anyway."
    }
    Write-Note "tests passed"
}

Write-Step "Regenerating the third-party licence notices"
$noticesFile = Join-Path $ProjectRoot 'THIRD-PARTY-NOTICES.txt'
$noticesBefore = if (Test-Path $noticesFile) { (Get-FileHash $noticesFile -Algorithm SHA256).Hash } else { '' }
Invoke-Native $python @((Join-Path $Packaging 'make_notices.py'))
if ($LASTEXITCODE -ne 0) { throw "Could not regenerate THIRD-PARTY-NOTICES.txt." }
if (-not (Test-Path $noticesFile)) { throw "make_notices.py produced no THIRD-PARTY-NOTICES.txt." }
$noticesAfter = (Get-FileHash $noticesFile -Algorithm SHA256).Hash
if ($noticesAfter -ne $noticesBefore) {
    Write-Host "    THIRD-PARTY-NOTICES.txt CHANGED -- a bundled component's licence or" -ForegroundColor Yellow
    Write-Host "    version differs from what was committed. Review and commit it." -ForegroundColor Yellow
} else {
    Write-Note "notices unchanged"
}

# Same reasoning as the notices above, one step further: EULA.rtf is what the
# customer is shown and asked to accept, and it is generated from
# LICENCE-TERMS.md. Regenerating it here means the terms they accept are always
# the terms in the repository, and never a stale .rtf someone forgot to refresh
# after editing the Markdown.
Write-Step "Regenerating the licence agreement"
$termsFile = Join-Path $ProjectRoot 'LICENCE-TERMS.md'
$eulaFile  = Join-Path $Packaging 'EULA.rtf'
# LICENCE-TERMS.md is not in the public repository -- see
# packaging\not-published.txt. A clone of it must still build, so rather than
# dying here we write an EULA that says what it is. Inno Setup has no
# "skip the licence page if the file is missing" option, and an installer
# with no licence page at all would look finished when it is not.
#
# The refusal belongs at signing, not here: signing is what makes a build
# distributable, and the document gate below already throws on a missing
# document when a certificate is in play.
if (-not (Test-Path $termsFile)) {
    if ($signing) {
        throw ("LICENCE-TERMS.md is missing, so there are no terms to put on the " +
               "installer's accept page. A signed build is a build going to " +
               "somebody; it cannot ship a placeholder licence.")
    }
    Write-Host "    LICENCE-TERMS.md IS NOT IN THIS CLONE." -ForegroundColor Yellow
    Write-Host "    Writing a placeholder licence page. The installer this produces is" -ForegroundColor Yellow
    Write-Host "    for testing only and must not be distributed." -ForegroundColor Yellow
    $stub = @(
        '{\rtf1\ansi\deff0{\fonttbl{\f0 Segoe UI;}}\fs20'
        '\b PDF Page Merger -- licence terms not included \b0\par\par'
        'This copy was built from a clone that does not carry the licence terms.\par\par'
        'The terms are issued directly with each order. This build is for testing'
        ' only and must not be distributed. Nothing on this page is an agreement.\par'
        '}'
    ) -join "`r`n"
    Set-Content -Path $eulaFile -Value $stub -Encoding ASCII
    Write-Note "placeholder EULA.rtf written"
} else {
    $eulaBefore = if (Test-Path $eulaFile) { (Get-FileHash $eulaFile -Algorithm SHA256).Hash } else { '' }
    Invoke-Native $python @((Join-Path $Packaging 'make_eula.py'))
    if ($LASTEXITCODE -ne 0) { throw "Could not regenerate EULA.rtf." }
    if (-not (Test-Path $eulaFile)) { throw "make_eula.py produced no EULA.rtf." }
    $eulaAfter = (Get-FileHash $eulaFile -Algorithm SHA256).Hash
    if ($eulaAfter -ne $eulaBefore) {
        Write-Host "    EULA.rtf CHANGED -- LICENCE-TERMS.md has been edited since the last" -ForegroundColor Yellow
        Write-Host "    build. Review and commit it." -ForegroundColor Yellow
    } else {
        Write-Note "licence unchanged"
    }
}

# The terms ship with [PLACEHOLDERS] in them until the trading entity is settled.
# A test build may carry them; a signed one is a build going to somebody, and an
# accept/decline page reading "[LEGAL ENTITY NAME]" is not a contract.
# Same pattern as make_eula.py's PLACEHOLDER: one level of nesting allowed, a
# run of capitals required. Keep the two in step.
#
# PRIVACY-NOTICE.md is checked alongside it. It is not shipped -- clause 8.3
# promises it on request -- but issuing the installer means being ready to hand it
# to a firm's compliance team, and it carries the same four placeholders.
$incomplete = @()
foreach ($doc in @($termsFile,
                   (Join-Path $ProjectRoot 'PRIVACY-NOTICE.md'),
                   (Join-Path $Packaging 'installer.iss'))) {
    if (-not (Test-Path $doc)) {
        if ($signing) { throw "$(Split-Path -Leaf $doc) is missing." }
        Write-Host "    $(Split-Path -Leaf $doc) is missing." -ForegroundColor Yellow
        continue
    }
    $raw = Get-Content $doc -Raw
    $found = [regex]::Matches($raw, '\[(?:[^\[\]]|\[[^\]]*\])*\]') |
        ForEach-Object { $_.Value -replace '\s+', ' ' } |
        Where-Object { $_ -cmatch '[A-Z]{2,}' } | Sort-Object -Unique
    # A section the document itself says to remove before issuing.
    if ($raw -match 'delete before issuing') { $found = @($found) + '<a "delete before issuing" section>' }
    foreach ($item in $found) { $incomplete += "$(Split-Path -Leaf $doc): $item" }
}
if ($incomplete) {
    if ($signing) {
        throw ("The customer-facing documents are incomplete: $($incomplete -join '; '). " +
               "Fill them in before producing a signed build -- those are the copies a customer accepts and relies on.")
    }
    Write-Host "    DOCUMENTS INCOMPLETE:" -ForegroundColor Yellow
    foreach ($item in $incomplete) { Write-Host "        $item" -ForegroundColor Yellow }
    Write-Host "    Fine for a test build; a signed build will refuse." -ForegroundColor Yellow
}

Write-Step "Building the programs with PyInstaller"
Push-Location $ProjectRoot
try {
    Invoke-Native $python @(
        '-m', 'PyInstaller', '--clean', '--noconfirm',
        (Join-Path $Packaging 'merge_tool.spec')
    )
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
} finally {
    Pop-Location
}

$gui = Join-Path $DistApp "$AppName.exe"
$cli = Join-Path $DistApp "pdfmerge.exe"
foreach ($exe in @($gui, $cli)) {
    if (-not (Test-Path $exe)) { throw "PyInstaller did not produce $exe" }
}
Write-Note "built $DistApp"

if ($signing) {
    Write-Step "Signing the programs"
    if ($azureRoute) {
        Invoke-SignToolSigning -Paths @($gui, $cli)
    } else {
        Invoke-Signing -Paths @($gui, $cli) -Certificate $certificate
    }
}

if ($SkipInstaller) {
    Write-Step "Done (installer skipped)"
    Write-Host "    $DistApp" -ForegroundColor Green
    return
}

Write-Step "Building the installer with Inno Setup"
Invoke-Native $iscc @((Join-Path $Packaging 'installer.iss'))
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }

$setup = Get-ChildItem (Join-Path $ProjectRoot 'dist\installer') -Filter '*Setup.exe' |
         Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $setup) { throw "Inno Setup produced no installer." }

if ($signing) {
    Write-Step "Signing the installer"
    if ($azureRoute) {
        Invoke-SignToolSigning -Paths @($setup.FullName)
    } else {
        Invoke-Signing -Paths @($setup.FullName) -Certificate $certificate
    }

    Write-Step "Checking the signature"
    $check = Get-AuthenticodeSignature -FilePath $setup.FullName
    Write-Note "status     : $($check.Status)"
    Write-Note "signer     : $($check.SignerCertificate.Subject)"
    Write-Note "timestamped: $(if ($check.TimeStamperCertificate) { 'yes' } else { 'NO -- expires with the certificate' })"
    if ($check.Status -eq 'UnknownError') {
        Write-Host "    A self-signed certificate reads as UnknownError until it is trusted. That is expected." -ForegroundColor Yellow
    }
    Assert-PublisherMatches -Path $setup.FullName
}

Write-Step "Done"
Write-Host "    $($setup.FullName)" -ForegroundColor Green
Write-Host "    $([math]::Round($setup.Length / 1MB, 1)) MB" -ForegroundColor Green
