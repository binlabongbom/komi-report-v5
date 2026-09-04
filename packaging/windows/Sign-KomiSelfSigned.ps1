param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [string]$ReleaseInfoPath = "",
    [string]$PublisherSubject = "CN=Wongsakorn Uphonram, O=KOMI Report",
    [string]$FriendlyName = "KOMI Report Self-Signed Code Signing",
    [int]$CertificateYears = 10
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Utf8NoBom {
    param([string]$Path, [string]$Text)
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $utf8)
}

function Get-OrCreateSigningCertificate {
    $now = Get-Date
    $certificate = Get-ChildItem Cert:\CurrentUser\My |
        Where-Object {
            $_.FriendlyName -eq $FriendlyName -and
            $_.HasPrivateKey -and
            $_.NotAfter -gt $now.AddDays(30) -and
            ($_.EnhancedKeyUsageList | Where-Object { $_.ObjectId.Value -eq '1.3.6.1.5.5.7.3.3' })
        } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1

    if ($certificate) {
        Write-Host "Reusing self-signed code-signing certificate: $($certificate.Thumbprint)"
        return $certificate
    }

    Write-Host 'Creating persistent self-signed code-signing certificate in CurrentUser\\My.'
    $certificate = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $PublisherSubject `
        -FriendlyName $FriendlyName `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -HashAlgorithm SHA256 `
        -KeyAlgorithm RSA `
        -KeyLength 3072 `
        -NotAfter (Get-Date).AddYears($CertificateYears)

    if (-not $certificate -or -not $certificate.HasPrivateKey) {
        throw 'Unable to create a usable self-signed code-signing certificate.'
    }

    return $certificate
}

$sourceInstaller = (Resolve-Path -LiteralPath $InstallerPath).Path
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$outputRoot = (Resolve-Path -LiteralPath $OutputDirectory).Path
$installerName = [System.IO.Path]::GetFileName($sourceInstaller)
$signedInstaller = Join-Path $outputRoot $installerName
Copy-Item -LiteralPath $sourceInstaller -Destination $signedInstaller -Force

$certificate = Get-OrCreateSigningCertificate
$certificatePath = Join-Path $outputRoot 'KOMI-Report-Code-Signing.cer'
Export-Certificate -Cert $certificate -FilePath $certificatePath -Type CERT -Force | Out-Null

# Trust the certificate only for the account running the self-hosted runner.
# This makes local CI verification meaningful without changing customer machines.
Import-Certificate -FilePath $certificatePath -CertStoreLocation 'Cert:\CurrentUser\Root' | Out-Null
Import-Certificate -FilePath $certificatePath -CertStoreLocation 'Cert:\CurrentUser\TrustedPublisher' | Out-Null

$timestampServer = 'http://timestamp.digicert.com'
$timestampUsed = $false
$signature = $null

try {
    Write-Host "Signing installer with SHA-256 and timestamp server $timestampServer"
    $signature = Set-AuthenticodeSignature `
        -FilePath $signedInstaller `
        -Certificate $certificate `
        -HashAlgorithm SHA256 `
        -TimestampServer $timestampServer

    if ($signature.Status -notin @('Valid', 'NotTrusted')) {
        throw "Timestamped signing returned status $($signature.Status): $($signature.StatusMessage)"
    }
    $timestampUsed = $true
}
catch {
    Write-Warning "Timestamped signing was unavailable: $($_.Exception.Message)"
    Write-Warning 'Retrying self-signing without an external timestamp.'
    $signature = Set-AuthenticodeSignature `
        -FilePath $signedInstaller `
        -Certificate $certificate `
        -HashAlgorithm SHA256
}

$signature = Get-AuthenticodeSignature -FilePath $signedInstaller
if (-not $signature.SignerCertificate) {
    throw 'Signed installer does not contain an Authenticode signer certificate.'
}
if ($signature.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) {
    throw "Signer thumbprint mismatch. Expected $($certificate.Thumbprint), got $($signature.SignerCertificate.Thumbprint)."
}
if ($signature.Status -in @('HashMismatch', 'NotSigned')) {
    throw "Authenticode verification failed with status $($signature.Status): $($signature.StatusMessage)"
}

$installerHash = (Get-FileHash -LiteralPath $signedInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
$certificateHash = (Get-FileHash -LiteralPath $certificatePath -Algorithm SHA256).Hash.ToLowerInvariant()
$certificateThumbprint = $certificate.Thumbprint.ToUpperInvariant()

$checksumLine = "$installerHash  $installerName`n"
Write-Utf8NoBom -Path (Join-Path $outputRoot 'INSTALLER.sha256') -Text $checksumLine
Write-Utf8NoBom -Path (Join-Path $outputRoot 'SHA256SUMS.txt') -Text $checksumLine
Write-Utf8NoBom -Path (Join-Path $outputRoot 'CERTIFICATE.sha256') -Text "$certificateHash  KOMI-Report-Code-Signing.cer`n"

$signatureInfo = [ordered]@{
    signing_mode = 'self-signed Authenticode'
    public_trust = $false
    publisher_subject = $certificate.Subject
    certificate_friendly_name = $certificate.FriendlyName
    certificate_thumbprint_sha1 = $certificateThumbprint
    certificate_file_sha256 = $certificateHash
    certificate_not_before = $certificate.NotBefore.ToUniversalTime().ToString('o')
    certificate_not_after = $certificate.NotAfter.ToUniversalTime().ToString('o')
    timestamp_server = if ($timestampUsed) { $timestampServer } else { $null }
    timestamp_used = $timestampUsed
    authenticode_status_on_build_runner = [string]$signature.Status
    authenticode_status_message = [string]$signature.StatusMessage
    installer = $installerName
    installer_bytes = (Get-Item -LiteralPath $signedInstaller).Length
    installer_sha256 = $installerHash
}
Write-Utf8NoBom -Path (Join-Path $outputRoot 'SIGNATURE_INFO.json') -Text (($signatureInfo | ConvertTo-Json -Depth 5) + "`n")

if ($ReleaseInfoPath -and (Test-Path -LiteralPath $ReleaseInfoPath)) {
    $releaseInfo = Get-Content -LiteralPath $ReleaseInfoPath -Raw | ConvertFrom-Json
    $releaseInfo | Add-Member -NotePropertyName installer_sha256 -NotePropertyValue $installerHash -Force
    $releaseInfo | Add-Member -NotePropertyName installer_bytes -NotePropertyValue ((Get-Item -LiteralPath $signedInstaller).Length) -Force
    $releaseInfo | Add-Member -NotePropertyName signing_mode -NotePropertyValue 'self-signed Authenticode' -Force
    $releaseInfo | Add-Member -NotePropertyName signing_public_trust -NotePropertyValue $false -Force
    $releaseInfo | Add-Member -NotePropertyName signing_certificate_thumbprint -NotePropertyValue $certificateThumbprint -Force
    $releaseInfo | Add-Member -NotePropertyName signing_certificate_sha256 -NotePropertyValue $certificateHash -Force
    $releaseInfo | Add-Member -NotePropertyName signing_timestamp_used -NotePropertyValue $timestampUsed -Force
    Write-Utf8NoBom -Path (Join-Path $outputRoot 'RELEASE_INFO.json') -Text (($releaseInfo | ConvertTo-Json -Depth 10) + "`n")
}

$verifyIntegrity = @"
param(
    [string]`$Installer = ".\$installerName"
)

`$ErrorActionPreference = 'Stop'
`$ExpectedSha256 = '$installerHash'

if (-not (Test-Path -LiteralPath `$Installer)) {
    throw "Installer not found: `$Installer"
}

`$ActualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath `$Installer).Hash.ToLowerInvariant()
Write-Host "KOMI Report installer integrity verification"
Write-Host "File:     `$Installer"
Write-Host "Expected: `$ExpectedSha256"
Write-Host "Actual:   `$ActualSha256"

if (`$ActualSha256 -ne `$ExpectedSha256) {
    throw 'Integrity check FAILED. Do not install this file.'
}

Write-Host 'Integrity check PASSED. The installer matches the official release hash.'
"@
Write-Utf8NoBom -Path (Join-Path $outputRoot 'VERIFY-INTEGRITY.ps1') -Text $verifyIntegrity

$verifySignature = @"
param(
    [string]`$Installer = ".\$installerName"
)

`$ErrorActionPreference = 'Stop'
`$ExpectedSha256 = '$installerHash'
`$ExpectedThumbprint = '$certificateThumbprint'

if (-not (Test-Path -LiteralPath `$Installer)) {
    throw "Installer not found: `$Installer"
}

`$ActualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath `$Installer).Hash.ToLowerInvariant()
if (`$ActualSha256 -ne `$ExpectedSha256) {
    throw "SHA-256 mismatch. Expected `$ExpectedSha256, got `$ActualSha256."
}

`$Signature = Get-AuthenticodeSignature -FilePath `$Installer
if (-not `$Signature.SignerCertificate) {
    throw 'No Authenticode signer certificate was found.'
}

`$ActualThumbprint = `$Signature.SignerCertificate.Thumbprint.ToUpperInvariant()
if (`$ActualThumbprint -ne `$ExpectedThumbprint) {
    throw "Signer mismatch. Expected `$ExpectedThumbprint, got `$ActualThumbprint."
}

if (`$Signature.Status -in @('HashMismatch', 'NotSigned')) {
    throw "Signature verification FAILED: `$(`$Signature.Status) - `$(`$Signature.StatusMessage)"
}

Write-Host 'KOMI Report signature verification PASSED.'
Write-Host "SHA-256:   `$ActualSha256"
Write-Host "Signer:    `$(`$Signature.SignerCertificate.Subject)"
Write-Host "Thumbprint:`$ActualThumbprint"
Write-Host "Trust:     `$(`$Signature.Status)"
if (`$Signature.Status -ne 'Valid') {
    Write-Warning 'The signature matches the official self-signed certificate, but this Windows account does not trust that certificate yet.'
}
"@
Write-Utf8NoBom -Path (Join-Path $outputRoot 'VERIFY-SIGNATURE.ps1') -Text $verifySignature

$trustScript = @"
param(
    [switch]`$Install,
    [ValidateSet('CurrentUser', 'LocalMachine')]
    [string]`$Scope = 'CurrentUser',
    [string]`$Certificate = '.\KOMI-Report-Code-Signing.cer',
    [string]`$Installer = '.\$installerName'
)

`$ErrorActionPreference = 'Stop'
`$ExpectedCertificateSha256 = '$certificateHash'
`$ExpectedThumbprint = '$certificateThumbprint'

if (-not `$Install) {
    Write-Host 'This helper trusts the KOMI Report SELF-SIGNED certificate on this Windows machine/account.'
    Write-Host 'Only do this if you obtained the certificate and installer from the official KOMI Report release.'
    Write-Host "Run again with: .\TRUST-KOMI-CERT.ps1 -Install -Scope CurrentUser"
    exit 2
}

if (-not (Test-Path -LiteralPath `$Certificate)) {
    throw "Certificate not found: `$Certificate"
}

`$ActualCertificateSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath `$Certificate).Hash.ToLowerInvariant()
if (`$ActualCertificateSha256 -ne `$ExpectedCertificateSha256) {
    throw "Certificate SHA-256 mismatch. Expected `$ExpectedCertificateSha256, got `$ActualCertificateSha256."
}

`$CertificateObject = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(`$Certificate)
if (`$CertificateObject.Thumbprint.ToUpperInvariant() -ne `$ExpectedThumbprint) {
    throw 'Certificate thumbprint mismatch.'
}

if (`$Scope -eq 'LocalMachine') {
    `$Principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not `$Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'LocalMachine trust requires an elevated PowerShell window. Use -Scope CurrentUser if machine-wide trust is not required.'
    }
}

`$RootStore = "Cert:\`$Scope\Root"
`$PublisherStore = "Cert:\`$Scope\TrustedPublisher"
Import-Certificate -FilePath `$Certificate -CertStoreLocation `$RootStore | Out-Null
Import-Certificate -FilePath `$Certificate -CertStoreLocation `$PublisherStore | Out-Null

Write-Host "Trusted KOMI Report certificate for scope: `$Scope"
Write-Host "Thumbprint: `$ExpectedThumbprint"

if (Test-Path -LiteralPath `$Installer) {
    `$Signature = Get-AuthenticodeSignature -FilePath `$Installer
    Write-Host "Installer signature status: `$(`$Signature.Status)"
    if (`$Signature.SignerCertificate) {
        Write-Host "Installer signer: `$(`$Signature.SignerCertificate.Subject)"
    }
}
"@
Write-Utf8NoBom -Path (Join-Path $outputRoot 'TRUST-KOMI-CERT.ps1') -Text $trustScript

Write-Host 'Self-signing complete.'
Write-Host "Installer: $signedInstaller"
Write-Host "SHA-256: $installerHash"
Write-Host "Certificate thumbprint: $certificateThumbprint"
Write-Host "Certificate SHA-256: $certificateHash"
Write-Host "Authenticode status on runner: $($signature.Status)"
Write-Host "Timestamp used: $timestampUsed"
