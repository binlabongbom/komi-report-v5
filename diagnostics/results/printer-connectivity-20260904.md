# Printer Connectivity Diagnostic — 2026-09-04

## Scope

- Runner: `DESKTOP-P9TSQEJ`
- Installed application used for the probe: KOMI Report `5.2.7`
- Targets: `10.244.116.8` and `10.244.116.6`
- Mode: read-only. The diagnostics did not write Counter/History data and did not attempt default passwords.

## Connectivity result

A final protocol comparison was completed in GitHub Actions run `33864369745`.

| Target | TCP 80 | TCP 443 | TCP 515 | TCP 631 | TCP 9100 | HTTP result |
|---|---:|---:|---:|---:|---:|---|
| `10.244.116.8` | Open | Open | Open | Open | Open | HTTP 301 redirect to HTTPS |
| `10.244.116.6` | Open | Open | Open | Open | Open | HTTP 301 redirect to HTTPS |

The same connections succeeded when explicitly bound to the physical Ethernet address `10.244.116.72` and when bound to the Tailscale address `100.80.139.46`.

## Web Connection result

The V5.2.7 modern Web Connection probe reached both printers, but both returned an authentication condition equivalent to:

> PublicUser is disabled; Administrator authentication is required.

The unauthenticated legacy HTTP Meter endpoint was also not supported by the selected firmware path. Therefore, the printers are reachable, but Counter/User data cannot be read without the configured Administrator credential and the correct model/profile.

## Routing observation

Route diagnostic run `33864099702` found that the runner has:

- Physical Ethernet IPv4: `10.244.116.72`
- Tailscale IPv4: `100.80.139.46`
- A connected Ethernet route for `10.244.116.0/24`
- An overlapping accepted Tailscale route for `10.244.116.0/24` with a lower effective metric

Windows therefore selected Tailscale as the automatic outgoing interface for these local-subnet printer IPs. Earlier run `33863672139` timed out against both printers, while the later protocol run succeeded within milliseconds. This makes the overlapping route a plausible source of intermittent connectivity, although the final successful test proves that both targets were online at the time of the final probe.

## Local configuration limitation

The GitHub Actions runner service executes as `NetworkService` (`DESKTOP-P9TSQEJ$`). Its per-user KOMI data location did not contain an application database, target device configuration, or credential reference. Read-only locator run `33864508273` also found no accessible existing KOMI database/configuration under the runner service context.

Windows Credential Manager data is user-scoped. Consequently, a credential saved by the interactive Windows user is not available to the `NetworkService` runner process. No credential value was read or exposed by these diagnostics.

## Conclusion

- Network and printer service connectivity: **PASS at final probe** for both targets.
- HTTPS redirect and Web Connection reachability: **PASS**.
- Public/anonymous Meter read: **BLOCKED BY DEVICE CONFIGURATION** because PublicUser is disabled.
- Administrator-authenticated Counter read: **NOT YET VERIFIED** under the runner service account.
- Real-device User Name enrichment (`1`, `2`, `3` to actual names): **NOT YET VERIFIED**, because the Administrator credential and device model/profile are not available to the account running the workflow.

The next end-to-end test must run under the same Windows account that owns the existing KOMI database and Credential Manager entries, or the two devices must be configured with Administrator credentials under the actual service account used for background polling. The overlapping Tailscale route should also be corrected or intentionally controlled before reliability UAT.
