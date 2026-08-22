from datetime import UTC, datetime

from komi_snmp_profiler.models import Confidence, MeterReading, WebAuthState, WebCounterValue
from services.runtime_snapshots import RuntimeSnapshotStore


def _counter(field: str, count: int, *, subject_type=None, subject_id=None, subject_name=None):
    return WebCounterValue(
        field,
        field,
        count,
        "Test",
        f"fixture.{field}",
        Confidence.VERIFIED,
        subject_type,
        subject_id,
        subject_name,
    )


def test_runtime_snapshot_separates_web_and_attributed_counters():
    store = RuntimeSnapshotStore()
    reading = MeterReading(
        host="192.0.2.10",
        collected_at=datetime.now(UTC).isoformat(),
        counters=(
            _counter("counter.total.total", 100),
            _counter(
                "counter.user.print.bw_total",
                40,
                subject_type="user",
                subject_id="1",
                subject_name="User 1",
            ),
            _counter(
                "counter.track.copy.full_color_total",
                12,
                subject_type="track",
                subject_id="001",
                subject_name="Account 001",
            ),
        ),
        source="fixture",
        auth_state=WebAuthState.ADMIN,
    )

    snapshot = store.update(0, reading)

    assert len(snapshot.web_rows) == 1
    assert len(snapshot.subject_rows) == 2
    assert snapshot.subject_rows[0].subject_name == "User 1"
    assert store.get(0) == snapshot


def test_runtime_snapshot_clear_is_per_device():
    store = RuntimeSnapshotStore()
    reading = MeterReading(
        host="192.0.2.10",
        collected_at=datetime.now(UTC).isoformat(),
        counters=(_counter("counter.total.total", 100),),
        source="fixture",
        auth_state=WebAuthState.ADMIN,
    )
    store.update(0, reading)
    store.update(1, reading)

    store.clear(0)

    assert store.get(0) is None
    assert store.get(1) is not None
