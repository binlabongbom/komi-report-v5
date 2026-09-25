from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from komi_snmp_profiler.connectors import (
    AuthenticatedWebConnectionCounterConnector,
    WebConnectionError,
    WebConnectionSessionBusyError,
)
from komi_snmp_profiler.credential_store import AdminCredential
from services.error_codes import ERROR_CODES


class SubjectSession:
    def __init__(self, subject_result, kind="user"):
        self.subject_result = subject_result
        self.kind = kind
        self.logged_out = False
        self.cleared = False

    def prepare_admin_login(self):
        pass

    def get(self, path):
        return {"MFP": {
            "LoginMode": "Admin", "Token": "private-test-token",
            "AuthSetting": {
                "AuthMode": {"AuthType": "Local" if self.kind == "user" else "None"},
                "TrackMode": {"TrackType": "Local" if self.kind == "account" else "None"},
            },
        }}

    def post_session_form(self, path, fields):
        self.logged_out |= path == "a_user.cgi"

    def post_json(self, path, body):
        if path.endswith("/_Total"):
            return {"MFP": {
                "Result": {"ResultInfo": "Ack"},
                "UserCounterInfo": {"TotalCounterList": {
                    "Counter": [{"Type": "Total", "Count": "2475"}],
                }},
            }}
        if isinstance(self.subject_result, Exception):
            raise self.subject_result
        return self.subject_result

    def clear(self):
        self.cleared = True


def collect(result, kind="user"):
    session = SubjectSession(result, kind)
    connector = AuthenticatedWebConnectionCounterConnector(
        session_factory=lambda *_args, **_kwargs: session,
    )
    reading = connector.collect_with_credential("192.0.2.10", AdminCredential("private-password"))
    assert reading.counters[0].canonical_field == "counter.total.total"
    assert reading.counters[0].count == 2475
    assert len(reading.counters) == 1
    assert session.logged_out and session.cleared
    assert len(reading.warnings) == 1
    warning = reading.warnings[0]
    assert "อ่าน Total Meter สำเร็จ" in warning
    assert "firmware นี้ไม่ได้" not in warning
    assert "request_mode=Admin" in warning
    assert "private-password" not in warning
    assert "private-test-token" not in warning
    return warning


@pytest.mark.parametrize("kind,endpoint", [
    ("user", "AppReqGetAuthCounter"),
    ("account", "AppReqGetTrackCounterInfo"),
])
def test_rejected_subject_response_retains_result_code_without_claiming_auth_failure(kind, endpoint):
    warning = collect({"MFP": {"Result": {"ResultInfo": "Nack"}}}, kind)
    assert "ResultInfo=Nack" in warning
    assert endpoint in warning
    assert "counter response" in warning
    assert f"Error Code: {ERROR_CODES['attribution_rejected']}" in warning
    assert f"Error Code: {ERROR_CODES['auth_rejected']}" not in warning
    assert ("AuthType=Local" if kind == "user" else "TrackType=Local") in warning


@pytest.mark.parametrize("response", [
    {"not_mfp": {}},
    {"MFP": {"AuthCounterList": {"AuthCounter": {
        "AuthNo": "1", "TotalCounterList": {
            "Counter": [{"Type": "Total", "Count": "not-a-number"}],
        },
    }}}},
    json.JSONDecodeError("Expected object", "not-json", 0),
])
def test_subject_parse_failure_is_response_error_not_user_input_or_firmware_claim(response):
    warning = collect(response)
    assert f"Error Code: {ERROR_CODES['response_invalid']}" in warning
    assert f"Error Code: {ERROR_CODES['input_invalid']}" not in warning


def test_subject_transport_failure_preserves_http_status_and_request_stage():
    error = WebConnectionError("อ่าน Web Connection ไม่สำเร็จ: HTTP 403")
    error.__cause__ = HTTPError("https://192.0.2.10/wcd/api/AppReqGetAuthCounter", 403, "Forbidden", {}, None)
    warning = collect(error)
    assert "HTTP=403" in warning
    assert "User counter request" in warning
    assert f"Error Code: {ERROR_CODES['http_forbidden']}" in warning


def test_subject_session_failure_preserves_existing_code():
    warning = collect(WebConnectionSessionBusyError("Another user session"))
    assert f"Error Code: {ERROR_CODES['session_busy']}" in warning


def test_subject_rejection_does_not_retain_response_payload_or_unstructured_result():
    warning = collect({"MFP": {
        "Result": {"ResultInfo": "password=private-password token=private-test-token"},
        "UserName": "private-user-name", "Token": "private-test-token",
    }})
    assert "ResultInfo=[non-code result]" in warning
    assert "private-user-name" not in warning


@pytest.mark.parametrize("auth,track,confirmed", [
    ("None", "None", True), ("", "", True),
    (None, "None", False), ("None", None, False), (None, None, False),
])
def test_public_user_evidence_requires_both_explicit_disabled_modes(auth, track, confirmed):
    from komi_snmp_profiler.models import PUBLIC_USER_DISABLED_MARKER

    setting = {}
    if auth is not None:
        setting['AuthMode'] = {'AuthType': auth}
    if track is not None:
        setting['TrackMode'] = {'TrackType': track}
    connector = AuthenticatedWebConnectionCounterConnector()
    counters, warnings = connector._collect_attributed(None, {'MFP': {'AuthSetting': setting}})
    assert not counters
    assert (PUBLIC_USER_DISABLED_MARKER in warnings) == confirmed
    if not confirmed:
        assert any('ยังยืนยันสถานะ' in warning for warning in warnings)


def test_enabled_but_empty_user_directory_is_not_public_evidence():
    from komi_snmp_profiler.models import PUBLIC_USER_DISABLED_MARKER

    session = SubjectSession({"MFP": {"Result": {"ResultInfo": "Ack"}, "AuthCounterList": {"AuthCounter": []}}})
    connector = AuthenticatedWebConnectionCounterConnector()
    counters, warnings = connector._collect_attributed(session, session.get('common'))
    assert not counters
    assert PUBLIC_USER_DISABLED_MARKER not in warnings
    assert any('ยังไม่มีรายการผู้ใช้งาน' in warning for warning in warnings)
