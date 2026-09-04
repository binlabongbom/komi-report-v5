# Security Policy

## Supported version

Security fixes are applied to the latest supported KOMI Report release. Older releases may be superseded rather than patched individually.

## Reporting a vulnerability

Please report suspected security vulnerabilities privately to the repository owner through the connected GitHub account. Do not publish exploit details, credentials, customer data, private keys, or proof-of-concept material in a public issue.

Include, when possible:

- affected KOMI Report version;
- affected component or file;
- steps to reproduce;
- expected and observed behavior;
- impact assessment;
- a minimal proof of concept that does not expose real customer data.

## Release verification

Official Windows releases may include:

- SHA-256 checksums;
- a self-signed Authenticode signature;
- the public signing certificate;
- signature and integrity verification scripts;
- release metadata and security evidence.

The self-signed certificate provides a stable signing identity and tamper detection, but it is not a publicly trusted commercial code-signing certificate. Windows may therefore show an untrusted or unknown publisher until the certificate is explicitly trusted on that machine or user account.

Never trust a signing certificate based only on its filename. Verify the certificate SHA-256 and thumbprint against the values published with the official release.
