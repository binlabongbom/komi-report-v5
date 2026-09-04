# Printer Connectivity UAT — 2026-09-04

## Scope

- Product under test: KOMI Report V5.2.7 installed on self-hosted Windows x64 runner `DESKTOP-P9TSQEJ`
- Targets: `10.244.116.8`, `10.244.116.10`
- Mode: read-only diagnostics
- No database writes, printer-setting changes, persistent credential changes, or user-name values were recorded.

## Result summary

| Target | Network | SNMP | Web Connection | Full KOMI meter read | User RAM Meter Export |
|---|---|---|---|---|---|
| `10.244.116.8` | Reachable but route is unstable/overlapping | PASS | Administrator required | PASS for general counters | PASS; 2 mapped nonnumeric names |
| `10.244.116.10` | Unreachable from runner | FAIL / timeout | FAIL / timeout | FAIL / timeout | Not testable |

## Target 10.244.116.8

- Ping completed with 0% packet loss during the successful run; average RTT was about 133 ms.
- TCP ports 80, 443, 515, 631, and 9100 were reachable.
- HTTP redirected to HTTPS; HTTPS returned 200 OK over TLS 1.2.
- SNMP returned model `KONICA MINOLTA bizhub C750i` and total meter `446152`.
- Public Web Connection access is disabled. The device requires Administrator access.
- KOMI Report completed an Administrator read-only meter read and returned 96 general counters.
- The current firmware parser returned zero User subject counters in that full meter-read path and reported that User Authentication is enabled but its User counter schema is not currently readable.
- A direct read-only User RAM Meter Export succeeded:
  - UTF-16, tab-delimited
  - 70 columns and 7 data rows
  - 2 mapped User IDs (`1`, `2`)
  - 2 unique visible names
  - all mapped names are nonnumeric
  - no empty mapped names
- Actual user-name values were intentionally omitted from logs and this document.

### Interpretation

The printer contains valid visible User names and V5.2.7 can download and parse the User RAM Meter Export. However, the normal Administrator meter-read path produces no User subject records on this C750i firmware. Name enrichment can only replace IDs on subject records that already exist; it cannot currently create those records from the export. Therefore, the end-to-end User report path is not yet fully proven for this device.

Recommended engineering change: when User Authentication is enabled and the Administrator read returns no User subjects, derive the per-user subject counters from the User RAM Meter Export, or add explicit parsing support for this C750i firmware's User counter schema. Add a real-device regression gate before the next release.

## Target 10.244.116.10

- Ping timed out with 100% packet loss.
- TCP ports 80, 443, 515, 631, and 9100 timed out.
- HTTP, HTTPS, TLS handshake, SNMP, public Web Connection, and full KOMI meter read all timed out.
- No application-level conclusion is possible until basic network reachability is restored and the target IP is confirmed.

## Runner route finding

The runner has Ethernet address `10.244.116.72` and Tailscale address `100.80.139.46`. Windows had two routes for `10.244.116.0/24`:

- a Tailscale subnet route with the preferred metric;
- a directly connected Ethernet route with a higher metric.

Windows selected the Tailscale route for the printer subnet. During one route-diagnostic run, `10.244.116.8` timed out; a later UAT run reached it with approximately 133 ms average latency. This overlapping route is a likely cause of intermittent access and should be corrected separately. No route or Tailscale setting was changed during this UAT.

## Release implication

- V5.2.7 installation and basic device connectivity are valid for `10.244.116.8`.
- The direct User export confirms that real names exist and are parseable.
- V5.2.7 should not yet be considered fully verified for end-to-end per-user collection on this C750i firmware.
- `10.244.116.10` remains blocked by network reachability.
