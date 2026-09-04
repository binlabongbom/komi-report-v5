# KOMI Report — Free Release Security Controls

This project intentionally uses security controls that do not require a paid code-signing subscription.

## Release pipeline

The Windows release pipeline uses the following controls:

1. Build and validate the installer on the self-hosted Windows runner.
2. Verify the original build artifact SHA-256 before signing.
3. Reuse one persistent self-signed Code Signing certificate from the self-hosted runner certificate store.
4. Authenticode-sign the Windows installer using SHA-256.
5. Attempt to add a public timestamp; if the timestamp service is unavailable, sign without a timestamp rather than publishing an unsigned installer.
6. Verify that the signed installer contains the expected signer certificate.
7. Recalculate SHA-256 after signing.
8. Publish checksum, signing-certificate metadata, verification scripts, release metadata, and the public certificate with the installer.

The private signing key stays in the Windows certificate store on the self-hosted runner and is not uploaded to GitHub Releases.

## Release assets

A hardened Windows release can include:

- `KOMI_Report_..._Installer.exe` — signed installer;
- `INSTALLER.sha256` — installer checksum;
- `SHA256SUMS.txt` — portable checksum file;
- `KOMI-Report-Code-Signing.cer` — public self-signed certificate only;
- `CERTIFICATE.sha256` — checksum of the public certificate;
- `SIGNATURE_INFO.json` — signer, thumbprint, certificate validity, timestamp, and installer hash;
- `VERIFY-INTEGRITY.ps1` — verifies installer SHA-256;
- `VERIFY-SIGNATURE.ps1` — verifies installer SHA-256 and signer thumbprint;
- `TRUST-KOMI-CERT.ps1` — optional explicit helper for users who decide to trust the self-signed certificate;
- `RELEASE_INFO.json` — build and signing metadata;
- `LICENSE` — KOMI Report proprietary freeware license.

## Important limitation of self-signed Authenticode

Self-signed Authenticode does **not** create public Windows trust. A clean Windows machine may still show `Unknown Publisher`, `NotTrusted`, or SmartScreen warnings.

The signature is still useful for:

- detecting modification after signing;
- proving that multiple releases were signed by the same private key while that certificate remains in use;
- allowing managed machines to explicitly trust the public certificate;
- giving support staff a reproducible signer thumbprint and file hash to verify.

Do not tell customers that the self-signed certificate is equivalent to a commercial/publicly trusted code-signing certificate.

## Customer verification

For hash-only verification:

```powershell
.\VERIFY-INTEGRITY.ps1
```

For hash + signer verification:

```powershell
.\VERIFY-SIGNATURE.ps1
```

To explicitly trust the certificate for the current Windows user, only after verifying the official certificate hash/thumbprint:

```powershell
.\TRUST-KOMI-CERT.ps1 -Install -Scope CurrentUser
```

Machine-wide trust requires an elevated PowerShell window:

```powershell
.\TRUST-KOMI-CERT.ps1 -Install -Scope LocalMachine
```

## Free repository security automation

The repository also contains:

- Dependabot weekly version-update configuration for Python, npm, and GitHub Actions;
- a self-hosted weekly security audit workflow;
- `pip-audit` for Python dependency vulnerabilities;
- `npm audit` for web dependencies;
- Bandit for Python static security analysis;
- Ruff for additional Python checks;
- detect-secrets for accidental secret discovery;
- CycloneDX SBOM generation for Python and npm where supported;
- existing web security tests;
- SHA-256 hashes for the generated audit evidence.

Dependency/static-analysis findings are initially report-only to avoid silently blocking releases because of pre-existing findings or scanner false positives. Existing explicit security tests remain a blocking check in the audit workflow.

## Controls that still require repository settings

Some GitHub account/repository settings cannot be changed by the release workflow itself. When available on the current GitHub plan, enable them in repository Settings, especially release immutability and Dependabot alerts/security updates.

Paid/private-repository security products are intentionally not required by this free baseline.
