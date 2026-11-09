"""Verified-shape, synthetic registration reads; no devices or saved credentials."""
import hashlib
import json
import secrets
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from komi_snmp_profiler.connectors import (
    AuthenticatedWebConnectionCounterConnector,
    ReadOnlyWebConnectionSession,
    WebConnectionError,
)
from komi_snmp_profiler.credential_store import AdminCredential

ENDPOINT = "api/AppReqGetUserAuthSetting"


def registration(rows=None, result="Ack"):
    return {"MFP": {"Result": {"ResultInfo": result}, "AuthUserSettingList": {
        "AuthUserSetting": rows if rows is not None else [
            {"AuthNo": "7", "UserName": "Synthetic Beta", "UserType": "User",
             "Password": "DO-NOT-RETAIN-PASSWORD", "Token": "DO-NOT-RETAIN-TOKEN"},
            {"AuthNo": "1", "UserName": "Synthetic Alpha", "UserType": "User"},
        ]}}}


class Session:
    def __init__(self, response=None, auth_type="Device", direct_names=False, is_color="False"):
        self.response = registration() if response is None else response
        self.auth_type, self.direct_names = auth_type, direct_names
        self.is_color = is_color
        self.template = b"synthetic-reviewed-950i-counter-template"
        self.calls, self.bodies = [], []

    def prepare_admin_login(self):
        self.calls.append("prepare")

    def get(self, _path):
        self.calls.append("get-common")
        return {"MFP": {"LoginMode": "Admin", "Token": "SYNTHETIC-SESSION-TOKEN", "MaxUserNW2": 100,
                        "isColor": self.is_color,
                        "AuthSetting": {"AuthMode": {"AuthType": self.auth_type},
                                        "TrackMode": {"TrackType": "None"}}}}

    def get_bytes(self, path):
        self.calls.append(path)
        if isinstance(self.template, Exception):
            raise self.template
        return self.template

    def post_session_form(self, path, _fields):
        self.calls.append(path)

    def post_json(self, path, body):
        self.calls.append(path)
        if path == ENDPOINT:
            self.bodies.append(body)
            if isinstance(self.response, Exception):
                raise self.response
            return self.response
        if path.endswith("/_Total"):
            return {"MFP": {"Result": {"ResultInfo": "Ack"}, "UserCounterInfo": {
                "TotalCounterList": {"Counter": [{"Type": "Total", "Count": "123"}]}}}}
        assert path == "api/AppReqGetAuthCounter"
        return {"MFP": {"Result": {"ResultInfo": "Ack"}, "AuthCounterList": {"AuthCounter": [
            {"AuthNo": sid, **({"UserName": f"Direct {sid}"} if self.direct_names else {}),
             "TotalCounterList": {"Counter": [{"Type": "Bw", "Count": count}]}}
            for sid, count in (("1", "0"), ("7", "17"))]}}}

    def clear(self):
        self.calls.append("clear")


def collect(session, enabled=True):
    connector = AuthenticatedWebConnectionCounterConnector(
        read_user_registration=enabled, session_factory=lambda *_args, **_kwargs: session,
    )
    result = connector.collect_with_credential("192.0.2.10", AdminCredential(password=secrets.token_urlsafe(16)))
    assert session.calls.count("login.cgi") == 1
    assert session.calls.count("a_user.cgi") == 1
    assert session.calls[-2:] == ["a_user.cgi", "clear"]
    assert session.calls.count(ENDPOINT) <= 1
    return result


def test_direct_ids_not_row_positions_and_only_identity_fields_leave_session():
    session = Session()
    result = collect(session)
    subjects = {item.subject_id: item for item in result.counters if item.subject_type == "user"}
    assert subjects["1"].subject_name == "Synthetic Alpha"
    assert subjects["7"].subject_name == "Synthetic Beta"
    assert [subjects[sid].count for sid in ("1", "7")] == [0, 17]
    assert len(result.counters) == 3 and result.counters[0].count == 123
    assert result.warnings == ()
    assert session.bodies == [{"UserListCondition": {"UserType": "User", "ObtainCondition": {
        "Type": "IndexList", "IndexRange": {"Start": 1, "End": 7}}, "BackUp": "false"},
        "Token": "SYNTHETIC-SESSION-TOKEN"}]
    serialized = json.dumps(asdict(result))
    for secret in ("DO-NOT-RETAIN-PASSWORD", "DO-NOT-RETAIN-TOKEN", "SYNTHETIC-SESSION-TOKEN"):
        assert secret not in serialized
    assert ENDPOINT in ReadOnlyWebConnectionSession.JSON_POST_PATHS
    assert not any("AppReqSet" in path for path in session.calls)


@pytest.mark.parametrize("response", [
    registration(result="Nack"), {"MFP": {}}, registration(rows="invalid"),
    registration(rows=[{"AuthNo": "1", "UserName": "A", "UserType": "Public"}]),
    registration(rows=[{"AuthNo": "1", "UserName": "", "UserType": "User"}]),
    registration(rows=[{"AuthNo": 1, "UserName": "A", "UserType": "User"}]),
    registration(rows=[{"AuthNo": "1", "UserName": "A", "UserType": "User"},
                       {"AuthNo": "1", "UserName": "B", "UserType": "User"}]),
    WebConnectionError("password=DO-NOT-RETAIN-PASSWORD token=DO-NOT-RETAIN-TOKEN"),
    json.JSONDecodeError("DO-NOT-RETAIN-PASSWORD", "DO-NOT-RETAIN-TOKEN", 0),
])
def test_registration_failure_retains_counters_without_export_retry_or_secret_diagnostics(response):
    session = Session(response)
    result = collect(session)
    assert len(result.counters) == 3
    assert [(item.subject_id, item.count) for item in result.counters[1:]] == [("1", 0), ("7", 17)]
    assert all(not item.subject_name for item in result.counters[1:])
    assert result.warnings
    assert "DO-NOT-RETAIN" not in json.dumps(asdict(result))


def test_partial_registration_does_not_shift_a_name_to_a_missing_id():
    result = collect(Session(registration(rows=[{"AuthNo": "7", "UserName": "Synthetic Beta", "UserType": "User"}])))
    assert result.counters[1].subject_id == "1" and not result.counters[1].subject_name
    assert result.counters[2].subject_id == "7" and result.counters[2].subject_name == "Synthetic Beta"
    assert any("บางเลขบัญชี" in warning for warning in result.warnings)


def test_same_id_mixed_direct_and_placeholder_names_are_not_overwritten():
    from dataclasses import replace

    from komi_snmp_profiler.models import WebCounterValue

    direct = WebCounterValue("counter.user.total.bw", "BW", 17, "Total", "synthetic",
                             subject_type="user", subject_id="7", subject_name="Direct Counter Name")
    placeholder = replace(direct, canonical_field="counter.user.print.bw", subject_name="7")
    session = Session()
    connector = AuthenticatedWebConnectionCounterConnector(read_user_registration=True)
    rows, warnings = connector._attach_registered_user_names(
        session, [direct, placeholder], token="SYNTHETIC-SESSION-TOKEN", max_user=100, auth_type="Device",
    )
    assert rows == [direct, placeholder]
    assert any("ขัดแย้ง" in warning for warning in warnings)


@pytest.mark.parametrize("enabled,auth_type,direct_names", [(False, "Device", False),
                                                         (True, "MiddleServer", False),
                                                         (True, "DeviceAndExtServer", False),
                                                         (True, "Device", True)])
def test_no_new_request_for_unenabled_or_unverified_modes_or_direct_names(enabled, auth_type, direct_names):
    session = Session(auth_type=auth_type, direct_names=direct_names)
    result = collect(session, enabled=enabled)
    assert ENDPOINT not in session.calls
    assert len(result.counters) == 3
    if direct_names:
        assert [item.subject_name for item in result.counters[1:]] == ["Direct 1", "Direct 7"]


def read_profile(monkeypatch, session, model="950i", *, approve_synthetic_template=True):
    from komi_snmp_profiler import meter, mono_950i

    if approve_synthetic_template:
        monkeypatch.setattr(mono_950i, "APPROVED_TEMPLATE_SHA256",
                            hashlib.sha256(b"synthetic-reviewed-950i-counter-template").hexdigest())
    constructor = AuthenticatedWebConnectionCounterConnector
    monkeypatch.setattr(meter, "AuthenticatedWebConnectionCounterConnector",
                        lambda **kwargs: constructor(session_factory=lambda *_args, **_kwargs: session, **kwargs))
    store = SimpleNamespace(load=lambda _host: AdminCredential(password=secrets.token_urlsafe(16)))
    reading = meter.MeterReader(store, public_factory_credentials=()).read("192.0.2.10", model=model)
    assert session.calls.count("login.cgi") == session.calls.count("a_user.cgi") == 1
    assert session.calls[-2:] == ["a_user.cgi", "clear"]
    return reading


def test_normal_reader_maps_verified_names_and_mono_totals_in_one_session(monkeypatch):
    from komi_snmp_profiler.mono_950i import SCHEMA_VERSION, TEMPLATE_PATH
    from services.subject_history import extract_subject_totals

    session = Session()
    reading = read_profile(monkeypatch, session)
    assert reading.schema_version == SCHEMA_VERSION
    assert reading.warnings == ()
    assert len(reading.counters) == 5
    raw = [item for item in reading.counters if item.canonical_field == "counter.user.total.bw"]
    totals = extract_subject_totals(reading)
    assert [(row.subject_id, row.subject_name, row.total_counter) for row in totals] == [
        ("1", "Synthetic Alpha", 0), ("7", "Synthetic Beta", 17)]
    assert [row.count for row in raw] == [0, 17]
    assert reading.counters[0].count == 123
    assert session.calls.count(ENDPOINT) == 1
    assert session.calls.count(TEMPLATE_PATH) == 1
    assert "DO-NOT-RETAIN" not in json.dumps(reading.to_dict())


@pytest.mark.parametrize("flag", [True, "True", None, 0])
def test_reader_does_not_read_template_or_map_without_explicit_mono_flag(monkeypatch, flag):
    from komi_snmp_profiler.mono_950i import TEMPLATE_PATH

    session = Session(is_color=flag)
    reading = read_profile(monkeypatch, session)
    assert reading.schema_version == "komi.meter.reading.v1"
    assert not any(item.canonical_field == "counter.user.total.total" for item in reading.counters)
    assert TEMPLATE_PATH not in session.calls
    assert reading.warnings


@pytest.mark.parametrize("failure", [False, True])
def test_unverified_or_unreadable_firmware_template_keeps_total_unknown(monkeypatch, failure):
    session = Session()
    if failure:
        session.template = WebConnectionError("private-token-must-not-be-logged")
    reading = read_profile(monkeypatch, session, approve_synthetic_template=False)
    assert reading.schema_version == "komi.meter.reading.v1"
    assert not any(item.canonical_field == "counter.user.total.total" for item in reading.counters)
    assert reading.warnings
    assert "private-token" not in json.dumps(reading.to_dict())


@pytest.mark.parametrize("model", ["bizhub C450i", "950i color", "unknown 950i", "C950i"])
def test_non_950i_model_adds_neither_new_endpoint_nor_mapped_total(monkeypatch, model):
    from komi_snmp_profiler.mono_950i import TEMPLATE_PATH

    session = Session()
    reading = read_profile(monkeypatch, session, model=model)
    assert ENDPOINT not in session.calls and TEMPLATE_PATH not in session.calls
    assert reading.schema_version == "komi.meter.reading.v1"
    assert not any(item.canonical_field == "counter.user.total.total" for item in reading.counters)
