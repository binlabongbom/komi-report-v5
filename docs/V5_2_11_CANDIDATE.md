# KOMI Report 5.2.11 candidate

This is an unapproved candidate, not a Production GO. Main is unchanged.

- Normal: Online Registration, redacted transport diagnostics and late-result handling.
- Offline: no Registration/Status/Meter transport; a Host-signed Offline License remains required. No private/master key is bundled. Missing public verification keys are a delivery blocker, never a reason to bypass activation.
- Primary: persistent Peer Sync default after setup/startup, including one-time legacy migration. Explicit Off in this version survives restarts. Legacy Off was represented by an absent file and cannot be distinguished from never-configured; upgrading therefore applies the requested new default once.
- The LAN service is available while Desktop/tray is running, not after Exit, sleep or power-off. Existing explicit Web-service disable is respected.
- Always-open claims are not device authentication. Use a trusted LAN, scope the OS firewall to approved subnets/profiles, never expose the service to the Internet. Secrets/history are excluded from setup snapshots.
- Both installers share the existing per-user AppId/data path: alternatives for in-place install, not side-by-side editions. Back up before switching edition; switching to Offline requires offline activation.

Required validation: native Windows tests; fresh install and 5.2.10 upgrade; second-machine handoff; no Internet with LAN retained; license import/mismatch/expiry; no credentials in diagnostics; final installer SHA256 and signature evidence. No automatic publish or installation onto the runner's real user data.
