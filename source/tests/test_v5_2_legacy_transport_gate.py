from __future__ import annotations

from PyQt6.QtCore import QCoreApplication

from services.registration_worker import RegistrationCoordinator


class FakeRepository:
    def __init__(self) -> None:
        self.retries = 0

    def manual_retry(self):
        self.retries += 1
        return 1


class FakeProcessor:
    def __init__(self) -> None:
        self.repository = FakeRepository()
        self.recovered = 0
        self.runs = 0

    def recover_after_restart(self):
        self.recovered += 1

    def run_once(self):
        self.runs += 1


def test_v5_2_runtime_cannot_start_or_retry_legacy_production_registration_transport():
    _app = QCoreApplication.instance() or QCoreApplication([])
    processor = FakeProcessor()
    coordinator = RegistrationCoordinator(processor)  # type: ignore[arg-type]

    coordinator.start()
    coordinator.tick()
    retried = coordinator.retry_now()

    assert coordinator.legacy_transport_enabled is False
    assert coordinator.timer.isActive() is False
    assert processor.recovered == 0
    assert processor.runs == 0
    assert processor.repository.retries == 0
    assert retried == 0
    coordinator.stop()
