# Printer Connectivity UAT — 2026-09-04

## Scope

- Product under test: KOMI Report V5.2.7 installed on self-hosted Windows x64 runner `DESKTOP-P9TSQEJ`
- Correct targets: `10.244.116.8`, `10.244.116.6`
- The earlier reference to `10.244.116.10` was an incorrect target and is superseded by this result.
- Network, HTTP/HTTPS, and SNMP diagnostics were read-only and made no Administrator password attempts.
- Application-level verification used temporary read-only Administrator sessions and temporary Meter exports where supported. Credentials remained in process memory only; no printer settings, database records, persistent credential entries, or user-name values were written.

## Result summary

| Target | Device | Network | SNMP | Administrator Meter read | User RAM Meter Export | End-to-end per-user status |
|---|---|---|---|---|---|---|
| `10.244.116.8` | bizhub C750i | PASS; automatic route uses Tailscale | PASS; Total `446152` | PASS; 96 general counters | PASS; 2 mapped nonnumeric names | NOT YET PASS: normal meter path returns zero User subjects |
| `10.244.116.6` | bizhub C450i | PASS; automatic route uses Tailscale | PASS; Total `269199` | PASS; 96 general counters | FAIL: selected firmware endpoint unsupported | NOT YET PASS: zero User subjects and no supported export fallback |

## Target 10.244.116.8 — bizhub C750i

- Ping completed with 0% packet loss; the corrected run averaged about 126 ms.
- TCP ports 80, 443, 515, 631, and 9100 were reachable.
- HTTP redirected to HTTPS; HTTPS returned 200 OK over TLS 1.2.
- Both explicitly bound Ethernet (`10.244.116.72`) and Tailscale (`100.80.139.46`) tests succeeded.
- SNMP returned model `KONICA MINOLTA bizhub C750i`, serial `ACKN041000032`, and Total Meter `446152`.
- Public Web Connection access is disabled and Administrator access is required.
- KOMI Report completed an Administrator read-only meter read and returned 96 general counters.
- The current firmware parser returned zero User subject counters and reported that User Authentication is enabled but its User counter schema is not currently readable.
- A direct read-only User RAM Meter Export succeeded:
  - UTF-16, tab-delimited
  - 70 columns and 7 data rows
  - 2 mapped User IDs (`1`, `2`)
  - 2 unique visible names
  - all mapped names are nonnumeric
  - no empty mapped names
- Actual user-name values were intentionally omitted from logs and this document.

### Interpretation for C750i

The printer contains valid visible User names and V5.2.7 can download and parse the User RAM Meter Export. However, the normal Administrator meter-read path produces no User subject records on this firmware. Name enrichment can only replace IDs on records that already exist; it cannot currently create those records from the export.

Recommended engineering change: when User Authentication is enabled and the Administrator read returns no User subjects, derive the per-user subject counters from the User RAM Meter Export, or add explicit parsing support for this C750i firmware's User counter schema.

## Target 10.244.116.6 — bizhub C450i

- Ping completed with 0% packet loss; average RTT was about 141 ms in the corrected run.
- TCP ports 80, 443, 515, 631, and 9100 were reachable.
- HTTP returned a 301 redirect to HTTPS; HTTPS returned 200 OK over TLS 1.2.
- Explicitly bound tests passed through both:
  - Ethernet source `10.244.116.72`
  - Tailscale source `100.80.139.46`
- SNMP returned:
  - model `KONICA MINOLTA bizhub C450i`
  - serial `AA7R041002004`
  - Total Meter `269199`
  - toner C `18%`, Y `56%`, M `32%`, K `41%`
- Public Web Connection access is disabled and Administrator access is required.
- The installed V5.2.7 application completed an Administrator read-only meter read and returned 96 general counters.
- The meter path returned zero User subject counters and reported that User Authentication is enabled but this firmware's User counter schema is not currently readable.
- A direct User RAM Meter Export attempt did not complete because the selected Web Connection firmware endpoint is unsupported (`WebConnectionUnsupportedError`).
- No user-name values were read into the diagnostic result.

### Interpretation for C450i

Basic connectivity, SNMP, Web Connection, Administrator login, and general meter collection are working. Per-user reporting is not yet supported end-to-end for this device because:

1. the normal Administrator counter path produces no User subject records; and
2. the current User RAM Meter Export endpoint is not supported by this C450i firmware.

Recommended engineering change: capture and implement the C450i-specific User counter/export protocol, or provide a model-specific alternate read-only endpoint. This device requires its own real-device regression case rather than reusing only the C750i export behavior.

## Runner route finding

The runner has Ethernet address `10.244.116.72` and Tailscale address `100.80.139.46`. Windows currently has two routes for `10.244.116.0/24`:

- Tailscale subnet route: route metric `0`, interface metric `5`
- directly connected Ethernet route: route metric `256`, interface metric `25`

Windows therefore selects Tailscale automatically for both printers, even though the runner is already connected directly to the same Ethernet subnet. Both direct Ethernet and Tailscale source tests succeeded, so this is not a basic reachability blocker. It does introduce unnecessary latency and remains a plausible source of intermittent behavior; no route or Tailscale setting was changed during the UAT.

## Release implication

- Basic V5.2.7 network, HTTPS, SNMP, and general Meter connectivity are verified for both targets.
- `10.244.116.8` proves that visible User names exist and its User export is parseable, but the normal meter path still lacks User subject records.
- `10.244.116.6` proves general Administrator meter collection, but its User schema and current export endpoint are unsupported.
- V5.2.7 should not yet be considered fully verified for end-to-end per-user collection on either tested firmware.
- Add separate real-device regression gates for C750i and C450i before the next release.
