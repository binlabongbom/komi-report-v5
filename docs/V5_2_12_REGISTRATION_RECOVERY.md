# 5.2.12 registration recovery — implementation candidate

Based on committed 5.2.11 revision `bf453738b934dcf5bea59dd8c70e191b52ba6b89`.
The original working copy and its uncommitted changes were not modified or imported.
This is preparatory source work, not a released 5.2.12 installer; version metadata
remains 5.2.11 until the recovery transport and installer configuration are complete.

## Implemented boundary

`V52ContractClient` defaults to the existing validating urllib transport. An
explicitly injected `RegistrationRecovery` can be consulted only after a
certificate-verification error on registration. Status and meter never use it;
their failures remain retryable through the existing outbox.

Recovery validates the existing signed registration contract with exact fields,
including its permitted device inventory. No IP addresses, passwords, documents,
logs, or new configuration fields are added. The endpoint is fixed to production
registration and the supplied transport must independently authenticate the Host
and prohibit redirects. No transport is supplied or activated by this change.

A SQLite record binds the first recovery request's installation ID, idempotency
key, and payload fingerprint before transmission. Timeouts can retry this same
request after restart. Different keys or changed payloads cannot use the recovery
channel. A contract-valid registration success closes the gate durably before
returning to the runtime. Normal registration success closes it too. Upgrade
checks existing registration history and runtime state conservatively. Resetting
setup, changing inventory, or losing the vault token must not reopen the gate.

No local activation, seven-day trial, or registration-pending collection policy
was introduced. The baseline setup and activation rules remain applicable.

## Decisions still needed before shipping

Choose an authenticated recovery transport and installer-controlled opt-in:

* Native Windows trust for registration only can help when Python's chain
  building fails but Windows validation succeeds. It still rejects a Host that
  Windows cannot validate. The prior uncommitted truststore implementation is
  reference material only; it has not been copied into monitoring.
* A separately verified certificate/SPKI pin can provide a different trust
  anchor when ordinary chain validation fails. This needs an actual trusted pin,
  rotation policy, and tests proving verification occurs before any HTTP data.
  No pin has been approved, discovered, or embedded.

Verify Host idempotency behavior and retention for replay of the same request
after a lost response. Client-side keys alone cannot guarantee Host deduplication.
No live registration request was sent during this work.

## Failure boundaries requiring release review

Recovery serializes sends with a SQLite write transaction during the bounded
network call. This can temporarily block other database writers. Before enabling
it in an installer, assess UI/database latency on customer hardware.

If the process dies after Host success but before closure commits, it can replay
the same idempotent request. If it dies after closure but before the token reaches
the OS vault, recovery remains closed; normal authenticated transport or support
must restore registration. The gate intentionally stores no token in plaintext.
Deleting/restoring the entire installation database is outside the durable-state
guarantee. A stronger guarantee across backup rollback requires Host enforcement.

Tests cover durable gate recreation, identical timeout retries, upgrade history,
normal success closure, contract field rejection, and real local TLS handshakes
for status/meter with valid, expired, wrong-hostname, and untrusted certificates.
Setup/runtime regression tests exercise the unchanged baseline flows. These do
not establish that the unreproduced Windows 10 customer TLS failure is repaired.
