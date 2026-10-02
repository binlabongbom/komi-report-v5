from komi_snmp_profiler.connectors import TlsPolicy
from komi_snmp_profiler.credential_store import CredentialStore
from komi_snmp_profiler.meter import MeterReader, _subject_name_is_placeholder
from komi_snmp_profiler.meter_export import MeterExportTable
from komi_snmp_profiler.models import WebCounterValue


class _FakeExportReader:
    def read(self, host: str, kind: str) -> MeterExportTable:
        assert host == "10.244.116.8"
        assert kind == "User"
        return MeterExportTable(
            kind="User",
            columns=("User Name", "Total"),
            rows=(("Alice Example", "100"), ("Bob Example", "50")),
            raw_text="",
            encoding="utf-16",
            delimiter="\t",
        )


class _NoopCredentialStore:
    def load(self, host):
        return None

    def save(self, host, credential):
        return None

    def delete(self, host):
        return None


def _counter(subject_id: str, subject_name: str | None) -> WebCounterValue:
    return WebCounterValue(
        canonical_field="user_total",
        label="User Total",
        count=100,
        category="user",
        source_path="test",
        subject_type="user",
        subject_id=subject_id,
        subject_name=subject_name,
    )


def test_numeric_subject_name_is_treated_as_placeholder():
    assert _subject_name_is_placeholder("39", "39") is True
    assert _subject_name_is_placeholder("039", "39") is True
    assert _subject_name_is_placeholder("39", "Alice Example") is False
    assert _subject_name_is_placeholder("39", None) is True
    assert _subject_name_is_placeholder("39", "²") is False


def test_numeric_aliases_do_not_guess_between_ambiguous_ids():
    from komi_snmp_profiler.subject_identity import numeric_name_aliases
    assert numeric_name_aliases({"001": "Alice"}) == {"1": "Alice"}
    assert numeric_name_aliases({"001": "Alice", "1": "Bob"}) == {}
    assert numeric_name_aliases({"²": "Bob"}) == {}


def test_exported_user_name_replaces_numeric_device_placeholder():
    reader = MeterReader(_NoopCredentialStore(), export_reader=_FakeExportReader())
    counters, warnings = reader._enrich_subject_names(
        "10.244.116.8",
        [_counter("1", "1"), _counter("2", "Bob Example")],
        TlsPolicy(),
    )

    assert warnings == []
    assert counters[0].subject_name == "Alice Example"
    assert counters[1].subject_name == "Bob Example"
