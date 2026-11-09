"""Synthetic identity checks; never infer AuthNo from export row position."""
from dataclasses import replace

import pytest

from komi_snmp_profiler.connectors import (
    WebConnectionAuthenticationError,
    WebConnectionError,
    WebCounterCollection,
)
from komi_snmp_profiler.meter import MeterReader
from komi_snmp_profiler.meter_export import MeterExportTable
from komi_snmp_profiler.models import WebAuthState, WebCounterValue


class Store:
    def __init__(self, credential=None):
        self.credential = credential

    def load(self, _host):
        return self.credential

    def save(self, _host, credential):
        self.credential = credential


class Counters:
    def __init__(self, rows, *, fail_admin=False, public_auth_required=False):
        self.rows, self.fail_admin = tuple(rows), fail_admin
        self.public_auth_required = public_auth_required

    def collect_with_credential(self, _host, _credential):
        if self.fail_admin:
            raise WebConnectionError("Synthetic admin transport failure")
        return WebCounterCollection(self.rows, "synthetic-admin", WebAuthState.ADMIN)

    def collect_result(self, _host):
        if self.public_auth_required:
            raise WebConnectionAuthenticationError("Synthetic public login requirement")
        return WebCounterCollection(self.rows, "synthetic-public", WebAuthState.PUBLIC)


class Export:
    def __init__(self):
        self.calls = 0

    def read(self, _host, _kind):
        self.calls += 1
        return MeterExportTable("User", ("User Name", "Total"),
                                (("Synthetic Alpha", "0"), ("Synthetic Beta", "0")),
                                "", "utf-16", "\t")


def rows():
    # Nonconsecutive IDs make the row-position assumption observably unsafe.
    return tuple(WebCounterValue("counter.user.total.bw", "Total: BW", 0,
                                "Total", f"synthetic/AuthCounter[{sid}]",
                                subject_type="user", subject_id=sid, subject_name=sid)
                 for sid in ("1", "7"))


@pytest.mark.parametrize("model", ["950i", "KM bizhub 950i", "KONICA MINOLTA bizhub 950I", "bizhub950i"])
@pytest.mark.parametrize("mode", ["admin", "public", "fallback", "factory"])
def test_950i_keeps_exact_ids_and_counters_without_export_position_join(model, mode):
    original = rows()
    connector = Counters(original, fail_admin=mode == "fallback", public_auth_required=mode == "factory")
    export = Export()
    reader = MeterReader(Store(object() if mode in {"admin", "fallback"} else None),
                         admin_connector=connector, public_connector=connector,
                         export_reader=export, public_factory_credentials=(object(),) if mode == "factory" else ())
    # Even a cache populated by an earlier caller/model cannot prove this join.
    reader._subject_name_cache[("192.0.2.10", "User")] = {"1": "Wrong positional name"}
    result = reader.read("192.0.2.10", model=model)
    assert result.counters == original
    assert export.calls == 0
    assert any("ยังไม่ยืนยันคู่ AuthNo/Track ID" in warning for warning in result.warnings)


def test_950i_preserves_names_returned_with_the_identity_by_the_counter_source():
    original = tuple(replace(row, subject_name=f"Direct source name {row.subject_id}") for row in rows())
    export = Export()
    reader = MeterReader(Store(), public_connector=Counters(original), export_reader=export)
    result = reader.read("192.0.2.10", model="bizhub 950i")
    assert result.counters == original
    assert result.warnings == ()
    assert export.calls == 0


@pytest.mark.parametrize("kind", ["user", "account", "track"])
def test_950i_mixed_named_and_zero_padded_id_rows_remain_unmodified(kind):
    first, second = rows()
    original = (
        replace(first, subject_type=kind, subject_name="Direct source name"),
        replace(second, subject_type=kind, subject_id="007", subject_name="7"),
    )
    export = Export()
    reader = MeterReader(Store(), public_connector=Counters(original), export_reader=export)
    result = reader.read("192.0.2.10", model="950i")
    assert result.counters == original
    assert export.calls == 0
    assert any("ยังไม่ยืนยันคู่ AuthNo/Track ID" in warning for warning in result.warnings)


@pytest.mark.parametrize("model", ["bizhub C450i", "bizhub C250i", "C950i"])
def test_existing_other_model_name_policy_is_not_changed_by_950i_guard(model):
    export = Export()
    reader = MeterReader(Store(), public_connector=Counters(rows()), export_reader=export)
    result = reader.read("192.0.2.10", model=model)
    assert result.counters[0].subject_name == "Synthetic Alpha"
    assert result.counters[1].subject_name == "7"
    assert export.calls == 1
    assert result.warnings == ()
