from __future__ import annotations

from komi_snmp_profiler.credential_store import AdminCredential
from komi_snmp_profiler.meter import MeterReader
from komi_snmp_profiler.meter_export import MeterExportTable
from komi_snmp_profiler.models import WebAuthState, WebCounterValue
from komi_snmp_profiler.connectors import WebCounterCollection


class MemoryStore:
    def __init__(self, credential: AdminCredential | None = None) -> None:
        self.credential = credential

    def save(self, _host: str, credential: AdminCredential) -> None:
        self.credential = credential

    def load(self, _host: str) -> AdminCredential | None:
        return self.credential

    def delete(self, _host: str) -> None:
        self.credential = None


class PublicConnectorWithUnnamedUser:
    def collect_result(self, _host: str) -> WebCounterCollection:
        value = WebCounterValue(
            "counter.user.total.total",
            "Total: Total",
            2,
            "Total",
            "MFP.AuthCounterList.AuthCounter[1]",
            subject_type="user",
            subject_id="1",
            subject_name="",
        )
        return WebCounterCollection(
            (value,),
            "web_connection_public",
            WebAuthState.PUBLIC,
        )


class UserNameExportReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def read(self, host: str, kind: str) -> MeterExportTable:
        self.calls.append((host, kind))
        return MeterExportTable(
            kind="User",
            columns=("Machine Name", "Column 2"),
            rows=(
                ("User Name", "Total Counter"),
                ("", ""),
                ("DMS", "2"),
            ),
            raw_text="",
            encoding="utf-16",
            delimiter="\t",
        )


def test_public_meter_read_enriches_subject_name_instead_of_leaking_numeric_id() -> None:
    export_reader = UserNameExportReader()
    reader = MeterReader(
        MemoryStore(),
        public_connector=PublicConnectorWithUnnamedUser(),
        export_reader=export_reader,
    )

    reading = reader.read("10.0.0.5")

    assert reading.auth_state == WebAuthState.PUBLIC
    assert reading.counters[0].subject_id == "1"
    assert reading.counters[0].subject_name == "DMS"
    assert export_reader.calls == [("10.0.0.5", "User")]


def test_public_meter_read_reuses_cached_name_mapping() -> None:
    export_reader = UserNameExportReader()
    reader = MeterReader(
        MemoryStore(),
        public_connector=PublicConnectorWithUnnamedUser(),
        export_reader=export_reader,
    )

    first = reader.read("10.0.0.5")
    second = reader.read("10.0.0.5")

    assert first.counters[0].subject_name == "DMS"
    assert second.counters[0].subject_name == "DMS"
    assert export_reader.calls == [("10.0.0.5", "User")]
