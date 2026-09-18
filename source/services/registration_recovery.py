"""Opt-in registration recovery gate; no TLS exception is enabled by default.

The installer must supply an independently authenticated transport. This module
does not select trust anchors, learn pins from the network, or alter global TLS.
"""
from __future__ import annotations

from database import _open
from services.v5_2_contract import validate_registration_payload


class RegistrationRecovery:
    def __init__(self, transport, *, endpoint: str) -> None:
        if endpoint != "https://www.dmskm.com/api/v1/installations/register":
            raise ValueError("Recovery is restricted to the production registration endpoint")
        self.transport = transport
        self.endpoint = endpoint

    @staticmethod
    def _schema(connection):
        connection.execute("""CREATE TABLE IF NOT EXISTS registration_recovery (
            installation_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            closed INTEGER NOT NULL DEFAULT 0 CHECK(closed IN (0,1)))""")

    @classmethod
    def close(cls, installation_id: str) -> None:
        with _open() as connection:
            cls._schema(connection)
            connection.execute("""INSERT INTO registration_recovery VALUES (?, '', '', 1)
                ON CONFLICT(installation_id) DO UPDATE SET closed=1""", (installation_id,))

    def send(self, client, operation):
        from services.v5_2_client import V52ContractClient

        denied = client._failure("tls_certificate_error", retryable=True, retry_after_seconds=300)
        if operation.event_type != "register" or client.config.endpoint("register") != self.endpoint:
            return denied
        try:
            validate_registration_payload(operation.payload)
        except (ValueError, TypeError, AttributeError, KeyError):
            return client._failure("payload_invalid", retryable=False)
        installation_id = str(operation.payload["installation_id"])
        # Persist the binding BEFORE network I/O: a lost response may only retry
        # the exact original payload and idempotency key, including after restart.
        with _open() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._schema(connection)
            previous = connection.execute("""SELECT 1 FROM v52_telemetry_outbox
                WHERE event_type='register' AND state='succeeded'
                AND json_extract(payload_json, '$.installation_id')=? LIMIT 1""",
                (installation_id,)).fetchone()
            state = connection.execute("""SELECT 1 FROM v52_runtime_state
                WHERE installation_id=? AND (status='registered'
                OR last_registered_inventory_json != '[]')""", (installation_id,)).fetchone()
            history = connection.execute("SELECT 1 FROM v52_telemetry_success WHERE event_type='register'").fetchone()
            connection.execute("INSERT OR IGNORE INTO registration_recovery VALUES (?, ?, ?, ?)",
                (installation_id, operation.idempotency_key, operation.request_fingerprint,
                 int(bool(previous or state or history))))
            if previous or state or history:
                connection.execute("UPDATE registration_recovery SET closed=1 WHERE installation_id=?",
                                   (installation_id,))
        # Serialize recovery attempts across processes. Success and permanent
        # closure commit together. No token is persisted in this gate.
        with _open() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT closed, idempotency_key, fingerprint FROM registration_recovery WHERE installation_id=?",
                                     (installation_id,)).fetchone()
            if row[0] or row[1] != operation.idempotency_key or row[2] != operation.request_fingerprint:
                return denied
            recovery_client = V52ContractClient(client.config, transport=self.transport, policy=client.policy)
            result = recovery_client.send(operation, _record_registration=False)
            if result.success:
                connection.execute("UPDATE registration_recovery SET closed=1 WHERE installation_id=?",
                                   (installation_id,))
            return result
