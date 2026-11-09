"""Synthetic-only regression tests for evidence-gated monochrome user Total."""
from dataclasses import FrozenInstanceError, replace

import pytest

from komi_snmp_profiler.models import Confidence, WebCounterValue
from komi_snmp_profiler.mono_950i import (
    APPROVED_TEMPLATE_SHA256,
    SCHEMA_VERSION,
    TEMPLATE_PATH,
    is_950i_model,
    map_950i_user_totals,
)


def row(count=17, sid="7", **changes):
    return replace(WebCounterValue(
        canonical_field="counter.user.total.bw", label="Total: Bw",
        count=count, category="Total",
        source_path=f"MFP.AuthCounterList.AuthCounter[{sid}].TotalCounterList.Counter[Type=Bw]",
        subject_type="user", subject_id=sid, subject_name=f"Synthetic {sid}",
    ), **changes)


def map_rows(rows, **options):
    return map_950i_user_totals(rows, **{
        "model": "bizhub 950i", "is_color": False,
        "template_sha256": APPROVED_TEMPLATE_SHA256, **options,
    })


@pytest.mark.parametrize("model", ["950i", " 950I ", "bizhub950i", "BIZHUB 950I", "KM bizhub 950i", "KONICA MINOLTA bizhub 950i"])
def test_exact_model(model):
    assert is_950i_model(model)


@pytest.mark.parametrize("model", ["C950i", "bizhub C950i", "9500i", "bizhub 9500i", "unknown", "950i color", "x950i", "", None])
def test_other_model_rejected(model):
    assert not is_950i_model(model)
    result = map_rows([row()], model=model)
    assert not result.changed and result.warnings


@pytest.mark.parametrize("count", [0, 19, 12.0])
@pytest.mark.parametrize("flag", [False, "False"])
def test_explicit_bw_alias_preserves_evidence(count, flag):
    original = row(count)
    result = map_rows([original], is_color=flag)
    assert result.changed and not result.warnings
    assert result.counters[0] is original
    alias = result.counters[1]
    assert alias.count == count
    assert alias.canonical_field == "counter.user.total.total"
    assert alias.source_path == original.source_path
    assert alias.subject_id == original.subject_id
    assert alias.subject_name == original.subject_name
    assert alias.confidence == Confidence.MAPPED
    assert "mapped" in alias.label
    with pytest.raises(FrozenInstanceError):
        result.changed = False


@pytest.mark.parametrize("flag", [True, "True", 0, 0.0, None, "false", "0", ""])
def test_monochrome_evidence_required(flag):
    original = (row(),)
    result = map_rows(original, is_color=flag)
    assert result.counters == original and not result.changed and result.warnings


@pytest.mark.parametrize("digest", ["", None, "0" * 64, APPROVED_TEMPLATE_SHA256.upper()])
def test_exact_template_hash_required(digest):
    result = map_rows([row()], template_sha256=digest)
    assert not result.changed and result.warnings


def test_evidence_constants():
    assert TEMPLATE_PATH == "spa_003_001_UCR001.tmpl.html"
    assert SCHEMA_VERSION == "komi.meter.reading.950i-monochrome.v1"
    assert APPROVED_TEMPLATE_SHA256 == "3e1c1e1b442bb8ce77b3cf74d97d6fdcda97fb20b6da985958a80084a0cbf30e"


def test_extreme_integer_is_not_promoted_into_a_total_that_downstream_cannot_render():
    original = row(10 ** 400)
    result = map_rows([original])
    assert result.counters == (original,)
    assert not result.changed and result.warnings


def test_duplicate_bw_kept_but_only_one_alias_and_idempotent():
    raw = row()
    result = map_rows([raw, raw])
    assert result.counters[:2] == (raw, raw)
    assert len(result.counters) == 3
    second = map_rows(result.counters)
    assert second.counters == result.counters and not second.changed


@pytest.mark.parametrize("changed", [{"count": 18}, {"subject_name": "Another synthetic name"}])
def test_conflicting_bw_stays_unknown(changed):
    original = (row(), row(**changed))
    result = map_rows(original)
    assert result.counters == original and not result.changed and result.warnings


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), float("-inf"), True, False, None, "19"])
def test_invalid_bw_never_becomes_zero(value):
    raw = row(value)
    result = map_rows([raw])
    assert result.counters == (raw,) and not result.changed and result.warnings


@pytest.mark.parametrize("count", [0, 99, -1, None, float("nan")])
def test_never_replace_existing_explicit_total(count):
    raw = (row(), row(count, canonical_field="counter.user.total.total"))
    result = map_rows(raw)
    assert result.counters == raw and not result.changed


@pytest.mark.parametrize("source", ["arbitrary Bw", "MFP.AuthCounterList.AuthCounter[8].TotalCounterList.Counter[Type=Bw]", "MFP.UserCounterInfo.TotalCounterList.Counter[Type=Bw]", "MFP.AuthCounterList.AuthCounter[7].TotalCounterList.Counter[Type=BW]"])
def test_source_requires_exact_authcounter_and_bw_type(source):
    result = map_rows([row(source_path=source)])
    assert not result.changed and result.warnings


def test_missing_bw_is_unknown_and_no_component_sums():
    raw = tuple(row(3, canonical_field=field) for field in (
        "counter.user.copy.bw", "counter.user.print.bw", "counter.user.paper.a3",
        "counter.user.paper.a4", "counter.user.document.bw", "counter.user.print_page_total.bw",
    ))
    result = map_rows(raw)
    assert result.counters == raw and not result.changed and result.warnings


@pytest.mark.parametrize("sid", [None, "", " "])
def test_missing_id_rejected(sid):
    result = map_rows([row(subject_id=sid)])
    assert not result.changed and result.warnings


def test_preserve_raw_machine_track_accounts_and_separate_users():
    raw = (
        row(2, "7"), row(0, "42"), row(3, "99", source_path="untrusted"),
        row(555, subject_type=None, subject_id=None, canonical_field="counter.total.total"),
        row(321, subject_type="track", canonical_field="counter.track.total.bw"),
        row(123, subject_type="account", canonical_field="counter.account.total.bw"),
    )
    result = map_rows(iter(raw))
    assert all(actual is expected for actual, expected in zip(result.counters[:len(raw)], raw, strict=True))
    aliases = result.counters[len(raw):]
    assert [(alias.subject_id, alias.count) for alias in aliases] == [("7", 2), ("42", 0)]
    assert result.warnings


def test_empty_input_has_no_invented_users_or_totals():
    result = map_rows([])
    assert result.counters == () and not result.changed
