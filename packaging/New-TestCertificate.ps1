<#
.SYNOPSIS
    Create a self-signed code signing certificate, to test the signing pipeline.

.DESCRIPTION
    This proves the build and signing steps work end to end before you spend
    money on a real certificate.

    It does NOT make the software trusted. A self-signed certificate is not
    chained to a public authority, so Windows still shows the SmartScreen
    warning and the signature reads as invalid on any machine that has not been
    told to trust it. Only a certificate from a public certificate authority
    fixes that -- see README.md in this folder.

    The certificate is created in your own certificate store (Cert:\CurrentUser\My).
    It is removed again by -Remove.

.PARAMETER Subject
    The publisher name that appears in the signature.

.PARAMETER Trust
    Also add it to your Trusted Root store, so signatures validate on THIS
    machine. Needs an elevated prompt and changes a security setting, so it asks
    first. Only do this on a machine you are testing on.

.PARAMETER Remove
    Delete the certificate again, from both stores.

.EXAMPLE
    .\packaging\New-TestCertificate.ps1
    .\packaging\build.ps1 -CertificateThumbprint <the thumbprint it prints>

.EXAMPLE
    .\packaging\New-TestCertificate.ps1 -Remove
#>

[CmdletBinding()]
param(
    [string]$Subject = "CN=PDF Page Merger Test Certificate",
    [switch]$Trust,
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'

if ($Remove) {
    $gone = 0
    foreach ($store in 'Cert:\CurrentUser\My', 'Cert:\CurrentUser\Root', 'Cert:\LocalMachine\Root') {
        Get-ChildItem $store -ErrorAction SilentlyContinue |
            Where-Object { $_.Subject -eq $Subject } |
            ForEach-Object {
                Remove-Item $_.PSPath -Force -ErrorAction SilentlyContinue
                Write-Host "removed from $store : $($_.Thumbprint)"
                $gone++
            }
    }
    if ($gone -eq 0) { Write-Host "Nothing to remove for $Subject" }
    return
}

Write-Host "Creating a TEST certificate. This does not make your software trusted." -ForegroundColor Yellow

$certificate = New-SelfSignedCertificate `
    -Subject $Subject `
    -Type CodeSigningCert `
    -KeyUsage DigitalSignature `
    -KeyAlgorithm RSA `
    -KeyLength 3072 `
    -HashAlgorithm SHA256 `
    -CertStoreLocation Cert:\CurrentUser\My `
    -NotAfter (Get-Date).AddYears(2)

Write-Host ""
Write-Host "  subject    : $($certificate.Subject)"
Write-Host "  thumbprint : $($certificate.Thumbprint)"
Write-Host "  expires    : $($certificate.NotAfter)"
Write-Host ""
Write-Host "Build with it:" -ForegroundColor Green
Write-Host "  .\packaging\build.ps1 -CertificateThumbprint $($certificate.Thumbprint)"

if ($Trust) {
    Write-Host ""
    Write-Host "Adding it to Trusted Root changes a security setting on this machine." -ForegroundColor Yellow
    $answer = Read-Host "Type YES to continue"
    if ($answer -ceq 'YES') {
        $exported = Join-Path $env:TEMP "pdfmerger-test-cert.cer"
        Export-Certificate -Cert $certificate -FilePath $exported | Out-Null
        Import-Certificate -FilePath $exported -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
        Remove-Item $exported -Force
        Write-Host "Added to Cert:\CurrentUser\Root. Undo with -Remove." -ForegroundColor Green
    } else {
        Write-Host "Left untrusted."
    }
}
