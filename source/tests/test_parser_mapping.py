from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

import database
from komi_snmp_profiler.models import (
    Confidence,
    MeterReading,
    WebAuthState,
    WebCounterValue,
)
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.parser_mapping import (
    LEGACY_ONLY_TARGET,
    ParserMappingOverride,
    ParserMappingRepository,
    apply_parser_mapping_overrides,
    raw_counter_key,
)
from services.reconciliation import ReconciliationReport


def _counter(
    field: str,
    value: float,
    *,
    path: str,
    subject_type: str | None = None,
) -> WebCounterValue:
    return WebCounterValue(
        canonical_field=field,
        label=field,
        count=value,
        category="Raw",
        source_path=path,
        confidence=Confidence.VERIFIED,
        subject_type=subject_type,
        subject_id="u-1" if subject_type else None,
        subject_name="alice" if subject_type else None,
    )


def test_parser_mapping_repository_is_per_serial_and_audited(tmp_path):
    original = database.get_db_path()
    database.set_db_path(tmp_path / "parser-mapping.sqlite3")
    try:
        database.init_db()
        repository = ParserMappingRepository()
        changed = repository.replace_all(
            "SERIAL-A",
            {
                ("raw.print.a5", "/counter.xml"): "mapped.print.a4.color",
                ("fax.total", "/counter.xml"): LEGACY_ONLY_TARGET,
            },
        )
        assert changed == 2
        loaded = repository.load("SERIAL-A")
        assert loaded[
            raw_counter_key("raw.print.a5", "/counter.xml")
        ].target_field == "mapped.print.a4.color"
        assert repository.load("SERIAL-B") == {}

        # Replacing one explicit rule with the system default removes only that
        # override and records the reversible change without touching Raw data.
        changed = repository.replace_all(
            "SERIAL-A",
            {("fax.total", "/counter.xml"): LEGACY_ONLY_TARGET},
        )
        assert changed == 1
        assert raw_counter_key("raw.print.a5", "/counter.xml") not in repository.load(
            "SERIAL-A"
        )
        with database._open(commit=False) as connection:
            audit_count = connection.execute(
                "SELECT COUNT(*) FROM parser_mapping_change_log WHERE device_serial=?",
                ("SERIAL-A",),
            ).fetchone()[0]
        assert audit_count == 3
    finally:
        database.set_db_path(original)


class _RepositoryDouble:
    def __init__(self, values: Mapping[str, ParserMappingOverride]) -> None:
        self.values = dict(values)

    def load(self, _device_serial: str) -> dict[str, ParserMappingOverride]:
        return dict(self.values)


def test_parser_mapping_changes_only_device_normalized_counters():
    raw_key = raw_counter_key("raw.print.a5", "/counter.xml")
    fax_key = raw_counter_key("fax.total", "/counter.xml")
    repository = _RepositoryDouble(
        {
            raw_key: ParserMappingOverride(
                "SERIAL-A",
                raw_key,
                "raw.print.a5",
                "/counter.xml",
                "mapped.print.a4.color",
                "2026-08-26T10:00:00+07:00",
            ),
            fax_key: ParserMappingOverride(
                "SERIAL-A",
                fax_key,
                "fax.total",
                "/counter.xml",
                LEGACY_ONLY_TARGET,
                "2026-08-26T10:00:00+07:00",
            ),
        }
    )
    reading = MeterReading(
        host="192.0.2.10",
        collected_at="2026-08-26T10:00:00+07:00",
        counters=(
            _counter("raw.print.a5", 5, path="/counter.xml"),
            _counter(
                "raw.print.a5",
                2,
                path="/counter.xml",
                subject_type="user",
            ),
            _counter("fax.total", 1, path="/counter.xml"),
        ),
        source="legacy_xml",
        auth_state=WebAuthState.PUBLIC,
    )

    normalized = apply_parser_mapping_overrides(
        reading,
        "SERIAL-A",
        repository=repository,
    )

    assert reading.counters[0].canonical_field == "raw.print.a5"
    assert [item.canonical_field for item in normalized.counters] == [
        "raw.print.a5",
        "mapped.print.a4.color",
    ]
    assert normalized.counters[0].subject_type == "user"
    assert normalized.counters[0].count == 2
    assert normalized.counters[1].subject_type is None
    assert normalized.counters[1].count == 5
    assert normalized.counters[1].category == "Print"


def test_mapping_revision_rebaselines_and_holds_same_day_billing(tmp_path):
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Printer", "192.0.2.10", serial="SERIAL-A")]
    )
    repository = ParserMappingRepository()
    cache = DailyCacheStore(tmp_path / "cache")
    first_at = datetime.fromisoformat("2026-08-26T08:00:00+07:00")
    second_at = datetime.fromisoformat("2026-08-26T09:00:00+07:00")
    safe = ReconciliationReport(checked_count=1, issues=())

    repository.replace_all(
        "SERIAL-A",
        {("raw.print", "/counter.xml"): "mapped.print.a4.color"},
    )
    first = MeterReading(
        host="192.0.2.10",
        collected_at=first_at.isoformat(),
        counters=(_counter("raw.print", 100, path="/counter.xml"),),
        source="legacy_xml",
        auth_state=WebAuthState.ADMIN,
    )
    normalized_first = apply_parser_mapping_overrides(
        first,
        "SERIAL-A",
        repository=repository,
    )
    cache.update_reading(0, normalized_first, at=first_at, reconciliation=safe)

    repository.replace_all(
        "SERIAL-A",
        {("raw.print", "/counter.xml"): "mapped.print.a3.color"},
    )
    second = MeterReading(
        host="192.0.2.10",
        collected_at=second_at.isoformat(),
        counters=(_counter("raw.print", 130, path="/counter.xml"),),
        source="legacy_xml",
        auth_state=WebAuthState.ADMIN,
    )
    normalized_second = apply_parser_mapping_overrides(
        second,
        "SERIAL-A",
        repository=repository,
    )
    state = cache.update_reading(
        0,
        normalized_second,
        at=second_at,
        reconciliation=safe,
    )

    assert normalized_first.schema_version != normalized_second.schema_version
    assert state["normalization_rebaseline"] == {
        "at": second_at.isoformat(timespec="seconds"),
        "from_schema": normalized_first.schema_version,
        "to_schema": normalized_second.schema_version,
    }
    assert state["opening"] == {"mapped.print.a3.color": 130.0}
    assert state["latest"] == {"mapped.print.a3.color": 130.0}
    assert state["delta"] == {"mapped.print.a3.color": 0}
    assert state["unsafe_reconciliation_seen"] is True
