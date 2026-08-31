from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QCoreApplication

from database import _open
from services.contract_adapters.v1_draft import DraftV1SigningAdapter
from services.installation_identity import load_or_create_installation_identity
from services.registration_data_notice import REGISTRATION_NOTICE_VERSION
from services.registration_vault import (
    SessionRegistrationSecretStore,
    installation_token_reference,
)
from services.v5_2_client import V52ClientResult
from services.v5_2_outbox import V52OutboxRepository
from services.v5_2_runtime import (
    OfflineLicenseConfigurationError,
    V52RuntimeCoordinator,
    V52RuntimeProcessor,
)
from services.v5_2_runtime_state import V52RuntimeStateRepository

NOW = datetime(2026, 8, 25, 8, tzinfo=UTC)
INSTALLATION_ID = "55555555-5555-4555-8555-555555555555"


class FakeDevices:
    def __init__(self, *, total: int | None = 100) -> None:
        self.items = [
            SimpleNamespace(
                slot=0,
                serial="SYNTH-RUNTIME-1",
                model="Synthetic Printer",
                last_total=total,
                last_success_at="2026-08-25T07:59:00Z",
                last_checked_at="2026-08-25T07:59:00Z",
            )
        ]

    def list(self, *, enabled_only: bool = False) -> list[object]:  # noqa: ARG002
        return self.items


class FakeClient:
    def __init__(self, results: list[V52ClientResult]) -> None:
        self.results = list(results)
        self.operations = []
        self.tokens: list[str | None] = []

    def send(self, operation, *, installation_token=None):
        self.operations.append(operation)
        self.tokens.append(installation_token)
        return self.results.pop(0)


def _success(*, token: str = "") -> V52ClientResult:
    return V52ClientResult(
        success=True,
        http_status=200,
        error_code="",
        retryable=False,
        retry_after_seconds=None,
        installation_token=token,
        next_status_after_seconds=21_600,
        next_meter_after_seconds=21_600,
    )


def _failure(*, retryable: bool, code: str) -> V52ClientResult:
    return V52ClientResult(
        success=False,
        http_status=503 if retryable else 422,
        error_code=code,
        retryable=retryable,
        retry_after_seconds=None,
        installation_token="",
        next_status_after_seconds=21_600,
        next_meter_after_seconds=21_600,
    )


def _inventory(
    serial: str = "SYNTH-RUNTIME-1",
    model: str = "Synthetic Printer",
) -> list[dict[str, object]]:
    return [
        {
            "serial_number": serial,
            "model": model,
            "selected": True,
            "device_slot": 1,
        }
    ]


def _configured(mode: str = "online") -> V52RuntimeStateRepository:
    state = V52RuntimeStateRepository()
    state.configure(
        mode,
        "Synthetic Company",
        INSTALLATION_ID,
        "2026-08-25T08:00:00Z",
        REGISTRATION_NOTICE_VERSION,
        "2026-08-25T08:00:00Z",
        now=NOW,
    )
    return state


def _processor(
    *,
    client=None,
    state=None,
    outbox=None,
    vault=None,
    devices=None,
    now: datetime = NOW,
):
    return V52RuntimeProcessor(
        client=client,
        state_repository=state or _configured(),
        outbox=outbox or V52OutboxRepository(),
        vault=vault or SessionRegistrationSecretStore(),
        device_repository=devices or FakeDevices(),
        clock=lambda: now,
        random_unit=lambda: 0.5,
        adapter=DraftV1SigningAdapter(),
    )


def test_missing_client_is_fail_closed_and_never_attempts_network():
    state = _configured()
    outbox = V52OutboxRepository()
    processor = _processor(client=None, state=state, outbox=outbox)

    assert processor.run_once() is False
    assert outbox.pending_count("register") == 1
    assert state.snapshot()["support_code"] == "client_not_configured"


def test_default_empty_terminal_baseline_does_not_block_initial_registration():
    state = _configured()
    outbox = V52OutboxRepository()
    devices = FakeDevices()
    devices.items = []
    processor = _processor(
        client=None,
        state=state,
        outbox=outbox,
        devices=devices,
    )

    assert processor.prepare_due() == 1
    operation = outbox.claim_due(now=NOW)
    assert operation is not None
    assert operation.event_type == "register"
    assert operation.payload["device_inventory"]["devices"] == []


def test_registration_uses_complete_discovery_inventory_and_marks_selected_devices():
    state = V52RuntimeStateRepository()
    state.configure(
        "online",
        "Synthetic Company",
        INSTALLATION_ID,
        "2026-08-25T08:00:00Z",
        REGISTRATION_NOTICE_VERSION,
        "2026-08-25T08:00:00Z",
        registration_devices=[
            {
                "serial_number": "DISCOVERED-1",
                "model": "Synthetic Selected",
                "selected": True,
                "device_slot": 1,
            },
            {
                "serial_number": "DISCOVERED-2",
                "model": "Synthetic Unselected",
                "selected": False,
                "device_slot": None,
            },
        ],
        now=NOW,
    )
    outbox = V52OutboxRepository()
    processor = _processor(client=None, state=state, outbox=outbox)

    assert processor.run_once() is False
    operation = outbox.claim_due(now=NOW)
    assert operation is not None
    devices = operation.payload["device_inventory"]["devices"]
    assert len(devices) == 2
    assert [item["selected"] for item in devices] == [True, False]


def test_registration_success_saves_token_only_in_vault_then_schedules_status_meter():
    state = _configured()
    vault = SessionRegistrationSecretStore()
    client = FakeClient([_success(token="synthetic-installation-token")])
    processor = _processor(client=client, state=state, vault=vault)

    assert processor.run_once() is True
    assert client.operations[0].event_type == "register"
    assert client.tokens == [None]
    assert vault.load(installation_token_reference(INSTALLATION_ID)) == (
        "synthetic-installation-token"
    )
    serialized = json.dumps(state.snapshot(), sort_keys=True)
    assert "synthetic-installation-token" not in serialized
    assert state.snapshot()["status"] == "registered"


def test_inventory_change_reregisters_same_installation_with_new_idempotency_and_keeps_token():
    state = V52RuntimeStateRepository()
    state.configure(
        "online",
        "Synthetic Company",
        INSTALLATION_ID,
        "2026-08-25T08:00:00Z",
        REGISTRATION_NOTICE_VERSION,
        "2026-08-25T08:00:00Z",
        registration_devices=_inventory(),
        now=NOW,
    )
    vault = SessionRegistrationSecretStore()
    reference = installation_token_reference(INSTALLATION_ID)
    client = FakeClient(
        [
            _success(token="initial-installation-token"),
            # A successful inventory update may retain the existing token.
            _success(token=""),
        ]
    )
    processor = _processor(client=client, state=state, vault=vault)

    assert processor.run_once() is True
    first = client.operations[0]
    assert vault.load(reference) == "initial-installation-token"
    assert json.loads(str(state.internal()["last_registered_inventory_json"])) == _inventory()

    replacement = _inventory("SYNTH-RUNTIME-2", "Replacement Printer")
    state.update_registration_devices(replacement, now=NOW)
    assert processor.run_once() is True
    second = client.operations[1]

    assert second.event_type == "register"
    assert second.payload["installation_id"] == INSTALLATION_ID
    assert second.idempotency_key != first.idempotency_key
    assert second.payload["device_inventory"]["devices"] == replacement
    assert client.tokens == [None, None]
    assert vault.load(reference) == "initial-installation-token"
    assert json.loads(str(state.internal()["last_registered_inventory_json"])) == replacement
    assert state.internal()["last_registration_terminal_inventory_json"] == "[]"


def test_terminal_registration_conflict_is_not_requeued_until_inventory_changes():
    state = V52RuntimeStateRepository()
    original = _inventory()
    state.configure(
        "online",
        "Synthetic Company",
        INSTALLATION_ID,
        "2026-08-25T08:00:00Z",
        REGISTRATION_NOTICE_VERSION,
        "2026-08-25T08:00:00Z",
        registration_devices=original,
        now=NOW,
    )
    vault = SessionRegistrationSecretStore()
    reference = installation_token_reference(INSTALLATION_ID)
    conflict = V52ClientResult(
        success=False,
        http_status=409,
        error_code="conflict",
        retryable=False,
        retry_after_seconds=None,
        installation_token="",
        next_status_after_seconds=21_600,
        next_meter_after_seconds=21_600,
    )
    client = FakeClient([_success(token="existing-token"), conflict])
    outbox = V52OutboxRepository()
    processor = _processor(
        client=client,
        state=state,
        outbox=outbox,
        vault=vault,
    )

    assert processor.run_once() is True
    baseline = str(state.internal()["last_registered_inventory_json"])
    rejected = _inventory("SYNTH-RUNTIME-2", "Replacement Printer")
    state.update_registration_devices(rejected, now=NOW)
    assert processor.run_once() is True
    terminal_operation = client.operations[-1]

    assert outbox.get(terminal_operation.operation_id).state == "terminal"
    assert state.snapshot()["support_code"] == "registration_conflict"
    assert str(state.internal()["last_registered_inventory_json"]) == baseline
    assert json.loads(
        str(state.internal()["last_registration_terminal_inventory_json"])
    ) == rejected
    assert vault.load(reference) == "existing-token"

    # The same rejected body stays terminal instead of being regenerated every tick.
    assert processor.run_once() is False
    assert len(client.operations) == 2

    # A real inventory correction is a new signed registration attempt.
    state.update_registration_devices(
        _inventory("SYNTH-RUNTIME-3", "Corrected Printer"), now=NOW
    )
    assert processor.prepare_due() == 1
    next_operation = outbox.claim_due(now=NOW)
    assert next_operation is not None
    assert next_operation.event_type == "register"
    assert next_operation.idempotency_key != terminal_operation.idempotency_key


def test_registered_runtime_batches_latest_aggregate_meter_and_status():
    state = _configured()
    state.mark_registration_succeeded(_inventory(), now=NOW)
    vault = SessionRegistrationSecretStore()
    vault.save(
        installation_token_reference(INSTALLATION_ID), "synthetic-installation-token"
    )
    client = FakeClient([_success(), _success()])
    processor = _processor(client=client, state=state, vault=vault, devices=FakeDevices(total=321))

    assert processor.run_once() is True
    assert processor.run_once() is True
    assert [item.event_type for item in client.operations] == ["status", "meter"]
    observation = client.operations[1].payload["observations"][0]
    assert observation == {
        "serial_number": "SYNTH-RUNTIME-1",
        "model": "Synthetic Printer",
        "device_slot": 1,
        "total_meter": 321,
        "meter_observed_at": "2026-08-25T07:59:00Z",
        "meter_status": "ok",
    }
    assert client.tokens == ["synthetic-installation-token"] * 2


def test_status_success_replaces_rotated_token_in_vault_without_exposing_it():
    state = _configured()
    state.mark_registration_succeeded(_inventory(), now=NOW)
    vault = SessionRegistrationSecretStore()
    reference = installation_token_reference(INSTALLATION_ID)
    vault.save(reference, "synthetic-installation-token")
    client = FakeClient([_success(token="rotated-installation-token")])
    processor = _processor(client=client, state=state, vault=vault)

    assert processor.run_once() is True
    assert client.operations[0].event_type == "status"
    assert vault.load(reference) == "rotated-installation-token"
    assert "rotated-installation-token" not in json.dumps(state.snapshot(), sort_keys=True)


def test_restart_recovers_inflight_with_same_idempotency_and_recovery_honors_cooldown():
    state = _configured()
    outbox = V52OutboxRepository()
    processor = _processor(state=state, outbox=outbox)
    processor.prepare_due()
    claimed = outbox.claim_due(now=NOW)
    assert claimed is not None

    assert processor.recover_after_restart() == 1
    recovered = outbox.claim_due(now=NOW)
    assert recovered is not None
    assert recovered.idempotency_key == claimed.idempotency_key

    outbox.complete_success(recovered, observed_at=NOW)
    assert outbox.recovery_send_allowed("register", now=NOW + timedelta(minutes=14)) is False
    assert outbox.recovery_send_allowed("register", now=NOW + timedelta(minutes=16)) is True


def test_startup_recovery_does_not_create_extra_status_or_meter_inside_cooldown():
    state = _configured()
    state.mark_registration_succeeded(_inventory(), now=NOW)
    vault = SessionRegistrationSecretStore()
    vault.save(
        installation_token_reference(INSTALLATION_ID), "synthetic-installation-token"
    )
    outbox = V52OutboxRepository()
    for event_type in ("status", "meter"):
        with _open() as connection:
            connection.execute(
                "INSERT INTO v52_telemetry_success(event_type,last_successful_at) VALUES(?,?)",
                (event_type, "2026-08-25T07:50:00+00:00"),
            )
    processor = _processor(state=state, outbox=outbox, vault=vault)

    assert processor.prepare_due(force_recovery=True) == 0
    assert outbox.active_count("status") == 0
    assert outbox.active_count("meter") == 0


def test_offline_mode_blocks_and_terminally_closes_all_unsent_telemetry():
    state = _configured()
    outbox = V52OutboxRepository()
    processor = _processor(state=state, outbox=outbox)
    processor.prepare_due()
    assert outbox.pending_count("register") == 1

    state.set_mode("offline", now=NOW)
    assert processor.run_once() is False
    assert outbox.active_count("register") == 0
    assert state.snapshot()["mode"] == "offline"


def test_notice_is_a_hard_online_send_gate():
    state = V52RuntimeStateRepository()
    state.configure(
        "online",
        "Synthetic Company",
        INSTALLATION_ID,
        "2026-08-25T08:00:00Z",
        "",
        "",
        now=NOW,
    )
    processor = _processor(state=state)

    assert processor.prepare_due() == 0
    assert V52OutboxRepository().active_count("register") == 0
    assert state.snapshot()["support_code"] == "notice_required"
    assert state.snapshot()["notice_accepted"] is False


def test_retry_and_terminal_results_update_durable_state_without_raw_error():
    state = _configured()
    client = FakeClient(
        [_failure(retryable=True, code="offline"), _failure(retryable=False, code="private_raw")]
    )
    processor = _processor(client=client, state=state)

    assert processor.run_once() is True
    assert state.snapshot()["status"] == "retrying"
    assert state.snapshot()["support_code"] == "offline"
    V52OutboxRepository().make_due("register", now=NOW)
    assert processor.run_once() is True
    assert state.snapshot()["status"] == "needs_review"
    assert state.snapshot()["support_code"] == "contract_invalid"
    assert "private_raw" not in json.dumps(state.snapshot())


def test_coordinator_offline_request_and_import_without_host_keys_fail_closed(tmp_path):
    state = _configured("offline")
    vault = SessionRegistrationSecretStore()
    coordinator = V52RuntimeCoordinator(
        None,
        state_repository=state,
        vault=vault,
        device_repository=FakeDevices(),
        clock=lambda: NOW,
        random_unit=lambda: 0.5,
    )
    request_path = tmp_path / "runtime.komirequest"

    assert coordinator.create_offline_request(request_path) == request_path
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["selected_devices"][0]["serial_number"] == "SYNTH-RUNTIME-1"
    with pytest.raises(OfflineLicenseConfigurationError):
        coordinator.import_offline_license(tmp_path / "missing.komilicense", {})
    coordinator.stop()


def test_offline_mode_stops_scheduler_and_meter_signal_never_queues_telemetry():
    _application = QCoreApplication.instance() or QCoreApplication([])
    state = _configured("offline")
    outbox = V52OutboxRepository()
    coordinator = V52RuntimeCoordinator(
        None,
        state_repository=state,
        outbox=outbox,
        vault=SessionRegistrationSecretStore(),
        device_repository=FakeDevices(),
        clock=lambda: NOW,
        random_unit=lambda: 0.5,
    )

    coordinator.start()
    coordinator.meter_observed(0)

    assert coordinator.timer.isActive() is False
    assert coordinator.retry_now() == 0
    assert sum(outbox.active_count(kind) for kind in ("register", "status", "meter")) == 0
    coordinator.stop()


def test_verified_offline_import_exposes_only_expiry_and_bound_devices(tmp_path):
    state = _configured("offline")
    vault = SessionRegistrationSecretStore()
    coordinator = V52RuntimeCoordinator(
        None,
        state_repository=state,
        vault=vault,
        device_repository=FakeDevices(),
        clock=lambda: NOW,
        random_unit=lambda: 0.5,
    )
    request_path = coordinator.create_offline_request(tmp_path / "runtime.komirequest")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    host = load_or_create_installation_identity(vault, "synthetic-host-license-signer")
    license_payload = {
        "license_version": 1,
        "license_id": "99999999-9999-4999-8999-999999999999",
        "request_id": request["request_id"],
        "company_name": request["company_name"],
        "installation_id": request["installation_id"],
        "installation_public_key_sha256": hashlib.sha256(
            coordinator.processor._identity(state.internal()).public_key_bytes
        ).hexdigest(),
        "selected_devices": request["selected_devices"],
        "max_desktop_installations": 1,
        "max_selected_printers": 3,
        "issued_at": "2026-08-25T08:00:00Z",
        "valid_from": "2026-08-25T08:00:00Z",
        "expires_at": "2031-08-25T08:00:00Z",
        "algorithm": "Ed25519",
        "kid": "host-test-kid",
    }
    adapter = DraftV1SigningAdapter()
    license_payload["signature"] = host.sign(
        adapter.canonical_bytes(license_payload, exclude_fields=frozenset({"signature"}))
    )
    license_path = tmp_path / "runtime.komilicense"
    license_path.write_text(json.dumps(license_payload), encoding="utf-8")

    coordinator.import_offline_license(
        license_path, {"host-test-kid": host.public_key_base64url}
    )
    snapshot = coordinator.snapshot()
    assert snapshot["mode"] == "offline"
    assert snapshot["status"] == "offline_license"
    assert snapshot["offline_license"] == {
        "expires_at": "2031-08-25T08:00:00Z",
        "bound_devices": request["selected_devices"],
    }
    serialized = json.dumps(snapshot)
    assert "host-test-kid" not in serialized
    assert request["installation_public_key"] not in serialized
    coordinator.stop()


def test_usage_eligibility_requires_registered_state_and_vault_token():
    state = _configured()
    vault = SessionRegistrationSecretStore()
    coordinator = V52RuntimeCoordinator(
        None,
        state_repository=state,
        vault=vault,
        device_repository=FakeDevices(),
        clock=lambda: NOW,
        random_unit=lambda: 0.5,
    )

    assert coordinator.usage_eligibility() == (False, "registration_required")
    state.update_registration_devices(_inventory(), now=NOW)
    state.mark_registration_succeeded(_inventory(), now=NOW)
    assert coordinator.usage_eligibility() == (
        False,
        "installation_token_unavailable",
    )
    vault.save(
        installation_token_reference(INSTALLATION_ID),
        "synthetic-installation-token",
    )
    assert coordinator.usage_eligibility() == (True, "registered")
    coordinator.stop()


def test_registered_runtime_stays_local_first_during_transient_retry_and_restart():
    state = _configured()
    state.update_registration_devices(_inventory(), now=NOW)
    state.mark_registration_succeeded(_inventory(), now=NOW)
    vault = SessionRegistrationSecretStore()
    vault.save(
        installation_token_reference(INSTALLATION_ID),
        "synthetic-installation-token",
    )
    client = FakeClient([_failure(retryable=True, code="offline")])
    processor = _processor(client=client, state=state, vault=vault)

    assert processor.run_once() is True
    assert client.operations[0].event_type == "status"
    assert state.snapshot()["status"] == "retrying"

    restarted = V52RuntimeCoordinator(
        None,
        state_repository=V52RuntimeStateRepository(),
        vault=vault,
        device_repository=FakeDevices(),
        clock=lambda: NOW,
        random_unit=lambda: 0.5,
    )
    assert restarted.usage_eligibility() == (True, "registered")
    state.mark_status("waiting_for_internet", error_code="offline", now=NOW)
    assert restarted.usage_eligibility() == (True, "registered")
    restarted.stop()


def test_registered_runtime_still_blocks_terminal_and_inventory_mismatch():
    state = _configured()
    state.update_registration_devices(_inventory(), now=NOW)
    state.mark_registration_succeeded(_inventory(), now=NOW)
    vault = SessionRegistrationSecretStore()
    vault.save(
        installation_token_reference(INSTALLATION_ID),
        "synthetic-installation-token",
    )
    coordinator = V52RuntimeCoordinator(
        None,
        state_repository=state,
        vault=vault,
        device_repository=FakeDevices(),
        clock=lambda: NOW,
        random_unit=lambda: 0.5,
    )

    state.mark_status(
        "needs_review",
        error_code="installation_token_unavailable",
        now=NOW,
    )
    assert coordinator.usage_eligibility() == (False, "registration_required")

    state.mark_status("registered", now=NOW)
    state.update_registration_devices(
        _inventory("SYNTH-RUNTIME-2", "Replacement Printer"),
        now=NOW,
    )
    assert coordinator.usage_eligibility() == (False, "registration_required")
    coordinator.stop()


def test_expired_or_invalid_offline_license_is_a_fail_closed_usage_gate():
    state = _configured("offline")
    bound_devices = [
        {
            "serial_number": "SYNTH-RUNTIME-1",
            "model": "Synthetic Printer",
            "device_slot": 1,
        }
    ]
    state.update_registration_devices(
        [
            {
                **bound_devices[0],
                "selected": True,
            }
        ],
        now=NOW,
    )
    state.save_offline_license(
        license_id="offline-license",
        expires_at="2026-08-25T07:59:59Z",
        kid="host-test-kid",
        bound_devices=bound_devices,
        now=NOW,
    )

    assert state.usage_eligibility(now=NOW) == (
        False,
        "offline_license_expired",
    )
    snapshot = state.snapshot(now=NOW)
    assert snapshot["status"] == "offline_license_expired"
    assert snapshot["support_code"] == "offline_license_expired"

    state.save_offline_license(
        license_id="offline-license",
        expires_at="not-a-timestamp",
        kid="host-test-kid",
        bound_devices=bound_devices,
        now=NOW,
    )
    assert state.usage_eligibility(now=NOW) == (
        False,
        "offline_license_expired",
    )

    state.save_offline_license(
        license_id="offline-license",
        expires_at="2026-08-25T08:00:01Z",
        kid="host-test-kid",
        bound_devices=bound_devices,
        now=NOW,
    )
    assert state.usage_eligibility(now=NOW) == (True, "offline_license")

    state.update_registration_devices(
        [
            {
                "serial_number": "REPLACEMENT-2",
                "model": "Replacement Printer",
                "selected": True,
                "device_slot": 1,
            }
        ],
        now=NOW,
    )
    assert state.usage_eligibility(now=NOW) == (
        False,
        "offline_license_device_mismatch",
    )
    assert state.snapshot(now=NOW)["status"] == "offline_license_device_mismatch"
