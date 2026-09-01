from __future__ import annotations

import json
import secrets

import pytest

import komi_snmp_profiler.meter as meter_module
from komi_snmp_profiler.app import meter_counter_rows
from komi_snmp_profiler.connectors import (
    AuthenticatedWebConnectionCounterConnector,
    LegacyAuthenticatedWebConnectionCounterConnector,
    ReadOnlyWebConnectionSession,
    WebConnectionAuthenticationError,
    WebConnectionCertificateError,
    WebConnectionCounterConnector,
    WebConnectionError,
    WebConnectionSessionBusyError,
    WebConnectionTlsError,
    WebCounterCollection,
)
from komi_snmp_profiler.credential_store import (
    PUBLIC_FACTORY_ADMIN_PASSWORDS,
    AdminCredential,
)
from komi_snmp_profiler.exporter import export_meter_csv, export_meter_json
from komi_snmp_profiler.meter import MeterReader
from komi_snmp_profiler.meter_export import (
    MeterCountExportConnector,
    MeterExportTable,
    parse_meter_export,
    subject_name_map,
)
from komi_snmp_profiler.models import MeterReading, WebAuthState, WebCounterValue


def total_payload(total: int = 2339) -> dict[str, object]:
    return {
        "MFP": {
            "Result": {"ResultInfo": "Ack"},
            "UserCounterInfo": {
                "TotalCounterList": {
                    "TotalCounter": [
                        {"Type": "Total", "Count": str(total)},
                        {"Type": "Paper", "Count": "2041"},
                    ]
                }
            },
        }
    }


class FakeSession:
    def __init__(self, _host: str, **_kwargs) -> None:
        self.login_mode = "PublicUser"
        self.calls: list[tuple[str, str]] = []
        self.cleared = False

    def get(self, path: str, *, expect_json: bool = True):
        self.calls.append(("GET", path))
        if not expect_json:
            return {}
        return {
            "MFP": {
                "LoginMode": self.login_mode,
                "Token": "ephemeral-token",
                "AuthSetting": {
                    "AuthMode": {"AuthType": "None"},
                    "TrackMode": {"TrackType": "None"},
                },
            }
        }

    def prepare_admin_login(self) -> None:
        for path in ("spa_main.html", "spa_login.html", "login_ex.json", "top.xml"):
            self.get(path, expect_json=False)

    def prepare_meter_export(self, token: str) -> None:
        self.calls.append(("PREPARE_EXPORT", token))

    def post_json(self, path: str, _body: dict[str, object]):
        self.calls.append(("POST_JSON", path))
        assert "AppReqSet" not in path
        return total_payload()

    def post_session_form(self, path: str, _fields: dict[str, str]):
        self.calls.append(("POST_FORM", path))
        if path == "login.cgi":
            self.login_mode = "Admin"
        elif path == "a_user.cgi":
            self.login_mode = "PublicUser"
        return b""

    def clear(self) -> None:
        self.cleared = True


def test_authenticated_connector_logs_out_and_clears_session() -> None:
    sessions: list[FakeSession] = []

    def factory(host: str, **kwargs):
        session = FakeSession(host, **kwargs)
        sessions.append(session)
        return session

    connector = AuthenticatedWebConnectionCounterConnector(session_factory=factory)
    password = secrets.token_urlsafe(18)
    result = connector.collect_with_credential("10.0.0.5", AdminCredential(password=password))

    assert result.auth_state == WebAuthState.ADMIN
    assert result.counters[0].count == 2339
    assert result.warnings == (
        "User Authentication และ Account Track ยังไม่ได้เปิดใช้งานบนเครื่อง",
    )
    assert ("POST_FORM", "login.cgi") in sessions[0].calls
    assert sessions[0].calls[-1] == ("POST_FORM", "a_user.cgi")
    assert sessions[0].cleared is True


def test_admin_login_fields_match_web_connection_contract() -> None:
    password = secrets.token_urlsafe(18)
    fields = AuthenticatedWebConnectionCounterConnector._login_fields(
        {
            "MFP": {
                "AuthSetting": {
                    "AuthMode": {"AuthType": "Device"},
                    "TrackMode": {"TrackType": "On"},
                }
            }
        },
        AdminCredential(password=password),
    )

    assert fields == {
        "func": "PSL_LP1_LOG",
        "AuthType": "Device",
        "TrackType": "",
        "ExtSvType": "0",
        "PswcForm": "",
        "Mode": "",
        "publicuser": "",
        "username": "",
        "password": password,
        "AuthorityType": "",
        "R_ADM": "AdminAdmin",
        "ExtServ": "0",
        "ViewMode": "",
        "BrowserMode": "",
        "Lang": "",
        "trackname": "",
        "trackpassword": "",
    }


class FakeLegacySession:
    def __init__(self, _host: str, **kwargs) -> None:
        self.scheme = kwargs["scheme"]
        self.calls: list[tuple[str, str]] = []
        self.cleared = False

    def get_bytes(self, path: str) -> bytes:
        self.calls.append(("GET", path))
        if path == "a_system_counter.xml":
            return b"""<MFP><UserCounterInfo><TotalCounterList>
            <TotalCounter><Type>Total</Type><Count>243744</Count></TotalCounter>
            </TotalCounterList></UserCounterInfo></MFP>"""
        return b"<MFP/>"

    def prepare_legacy_admin_login(self) -> None:
        self.calls.append(("PREPARE", "legacy_admin"))

    def post_session_form(self, path: str, fields: dict[str, str]) -> bytes:
        self.calls.append(("POST_FORM", path))
        if path == "login.cgi":
            assert fields["R_ADM"] == "AdminAdmin"
            assert fields["password"]
        return b""

    def clear(self) -> None:
        self.cleared = True


def test_legacy_admin_connector_reads_once_then_logs_out_and_clears_session() -> None:
    sessions: list[FakeLegacySession] = []

    def factory(host: str, **kwargs):
        session = FakeLegacySession(host, **kwargs)
        sessions.append(session)
        return session

    connector = LegacyAuthenticatedWebConnectionCounterConnector(session_factory=factory)
    result = connector.collect_with_credential(
        "10.0.0.5",
        AdminCredential(password=secrets.token_urlsafe(18)),
    )

    assert result.counters[0].count == 243_744
    assert sessions[0].scheme == "https"
    assert sessions[0].calls == [
        ("PREPARE", "legacy_admin"),
        ("POST_FORM", "login.cgi"),
        ("GET", "a_system_counter.xml"),
        ("POST_FORM", "a_user.cgi"),
    ]
    assert sessions[0].cleared is True


def test_legacy_admin_login_fields_match_web_connection_contract() -> None:
    password = secrets.token_urlsafe(18)

    fields = LegacyAuthenticatedWebConnectionCounterConnector._legacy_login_fields(
        AdminCredential(password=password)
    )

    assert fields["func"] == "PSL_LP1_LOG"
    assert fields["AuthType"] == "MiddleServer"
    assert fields["R_ADM"] == "AdminAdmin"
    assert "R_ADM1" not in fields
    assert fields["password"] == password


class LegacyCertificateFailureSession(FakeLegacySession):
    def get_bytes(self, path: str) -> bytes:
        raise WebConnectionCertificateError("self-signed")


def test_legacy_admin_connector_preserves_certificate_error_for_pinning_flow() -> None:
    connector = LegacyAuthenticatedWebConnectionCounterConnector(
        session_factory=lambda host, **kwargs: LegacyCertificateFailureSession(host, **kwargs)
    )

    with pytest.raises(WebConnectionCertificateError, match="self-signed"):
        connector.collect_with_credential(
            "10.0.0.5",
            AdminCredential(password=secrets.token_urlsafe(18)),
        )


class LegacyTlsFailureSession(FakeLegacySession):
    def prepare_legacy_admin_login(self) -> None:
        raise WebConnectionTlsError("TLS compatibility failed")


def test_legacy_admin_connector_preserves_tls_error_without_calling_it_bad_password() -> None:
    connector = LegacyAuthenticatedWebConnectionCounterConnector(
        session_factory=lambda host, **kwargs: LegacyTlsFailureSession(host, **kwargs)
    )

    with pytest.raises(WebConnectionTlsError, match="TLS compatibility"):
        connector.collect_with_credential(
            "10.0.0.5",
            AdminCredential(password=secrets.token_urlsafe(18)),
        )


class LegacyBusyCounterSession(FakeLegacySession):
    def get_bytes(self, path: str) -> bytes:
        self.calls.append(("GET", path))
        if path == "a_system_counter.xml":
            return b"<MFP><DirectAccessError>Another user session is active</DirectAccessError></MFP>"
        return b"<MFP/>"


def test_legacy_admin_connector_reports_explicit_session_busy_without_logging_out_other_user() -> None:
    session = LegacyBusyCounterSession("10.0.0.5", scheme="https")
    connector = LegacyAuthenticatedWebConnectionCounterConnector(
        session_factory=lambda *_args, **_kwargs: session
    )

    with pytest.raises(WebConnectionSessionBusyError, match="Logout"):
        connector.collect_with_credential(
            "10.0.0.5",
            AdminCredential(password=secrets.token_urlsafe(18)),
        )

    assert session.calls.count(("POST_FORM", "login.cgi")) == 1
    assert ("POST_FORM", "a_user.cgi") not in session.calls
    assert session.cleared is True


class LegacyMalformedCounterSession(FakeLegacySession):
    def get_bytes(self, path: str) -> bytes:
        self.calls.append(("GET", path))
        return b"not-xml"


def test_legacy_admin_connector_does_not_call_parser_failure_bad_password() -> None:
    session = LegacyMalformedCounterSession("10.0.0.5", scheme="https")
    connector = LegacyAuthenticatedWebConnectionCounterConnector(
        session_factory=lambda *_args, **_kwargs: session
    )

    with pytest.raises(WebConnectionError, match="XML") as raised:
        connector.collect_with_credential(
            "10.0.0.5",
            AdminCredential(password=secrets.token_urlsafe(18)),
        )

    assert not isinstance(raised.value, WebConnectionAuthenticationError)
    assert ("POST_FORM", "a_user.cgi") not in session.calls
    assert session.cleared is True


class LegacyRejectedLoginPageSession(FakeLegacySession):
    def post_session_form(self, path: str, fields: dict[str, str]) -> bytes:
        self.calls.append(("POST_FORM", path))
        if path == "login.cgi":
            assert fields["password"]
            return b"<html><form action='login.cgi'><input type='password' name='password'></form></html>"
        return b""


def test_legacy_admin_connector_calls_only_explicit_login_page_bad_password() -> None:
    session = LegacyRejectedLoginPageSession("10.0.0.5", scheme="https")
    connector = LegacyAuthenticatedWebConnectionCounterConnector(
        session_factory=lambda *_args, **_kwargs: session
    )

    with pytest.raises(WebConnectionAuthenticationError, match="ปฏิเสธรหัส"):
        connector.collect_with_credential(
            "10.0.0.5",
            AdminCredential(password=secrets.token_urlsafe(18)),
        )

    assert session.calls.count(("POST_FORM", "login.cgi")) == 1
    assert ("POST_FORM", "a_user.cgi") not in session.calls
    assert session.cleared is True


class LegacyContextFailureSession(FakeLegacySession):
    def post_session_form(self, path: str, fields: dict[str, str]) -> bytes:
        self.calls.append(("POST_FORM", path))
        if path == "login.cgi":
            assert fields["password"]
            return b"<MFP><DirectAccessError><Redirect>/wcd/index.html</Redirect></DirectAccessError></MFP>"
        return b""


def test_legacy_admin_connector_keeps_direct_access_context_error_separate_from_busy() -> None:
    session = LegacyContextFailureSession("10.0.0.5", scheme="https")
    connector = LegacyAuthenticatedWebConnectionCounterConnector(
        session_factory=lambda *_args, **_kwargs: session
    )

    with pytest.raises(WebConnectionError, match="context") as raised:
        connector.collect_with_credential(
            "10.0.0.5",
            AdminCredential(password=secrets.token_urlsafe(18)),
        )

    assert not isinstance(raised.value, WebConnectionSessionBusyError)
    assert ("POST_FORM", "a_user.cgi") not in session.calls
    assert session.cleared is True


class LegacyAdminPageWithPasswordSettingSession(FakeLegacySession):
    def post_session_form(self, path: str, fields: dict[str, str]) -> bytes:
        self.calls.append(("POST_FORM", path))
        if path == "login.cgi":
            assert fields["password"]
            return (
                b"<html><form action='change_login.cgi'><input type='password'></form>"
                b"<form action='notlogin.cgi'><input name='password'></form></html>"
            )
        return b""


def test_legacy_admin_connector_does_not_reject_unrelated_password_setting_form() -> None:
    session = LegacyAdminPageWithPasswordSettingSession("10.0.0.5", scheme="https")
    connector = LegacyAuthenticatedWebConnectionCounterConnector(
        session_factory=lambda *_args, **_kwargs: session
    )

    result = connector.collect_with_credential(
        "10.0.0.5",
        AdminCredential(password=secrets.token_urlsafe(18)),
    )

    assert result.counters[0].count == 243_744
    assert session.calls[-1] == ("POST_FORM", "a_user.cgi")
    assert session.cleared is True


class RejectedSession(FakeSession):
    def post_session_form(self, path: str, _fields: dict[str, str]):
        self.calls.append(("POST_FORM", path))
        return b""


def test_rejected_login_is_single_attempt_and_still_runs_logout_cleanup() -> None:
    session = RejectedSession("10.0.0.5")
    connector = AuthenticatedWebConnectionCounterConnector(session_factory=lambda *_args, **_kwargs: session)

    with pytest.raises(WebConnectionAuthenticationError, match="ไม่ลองรหัสซ้ำ"):
        connector.collect_with_credential("10.0.0.5", AdminCredential(password=secrets.token_urlsafe(18)))

    assert session.calls.count(("POST_FORM", "login.cgi")) == 1
    assert session.calls[-1] == ("POST_FORM", "a_user.cgi")
    assert session.cleared is True


def test_read_only_session_rejects_write_endpoint_before_network_call() -> None:
    session = ReadOnlyWebConnectionSession("127.0.0.1")
    with pytest.raises(WebConnectionError, match="read-only allowlist"):
        session.post_json("api/AppReqSetCustomMessage/_003_001_UCR002", {})


def test_meter_export_preparation_sets_required_ephemeral_ui_flags(monkeypatch) -> None:
    session = ReadOnlyWebConnectionSession("127.0.0.1")
    monkeypatch.setattr(session, "get", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(session, "post_temporary_export", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(session, "post_meter_export_telemetry", lambda: None)

    session.prepare_meter_export("ephemeral-token")

    cookies = {cookie.name: cookie.value for cookie in session.cookies}
    assert cookies["menuType"] == "Admin"
    assert cookies["sourcePage"] == "1"
    assert cookies["loginState"] == "true"
    assert cookies["cou"] == ""
    assert cookies["adm"] == ""


def test_temporary_export_allowlist_rejects_wrong_function_before_network_call() -> None:
    session = ReadOnlyWebConnectionSession("127.0.0.1")
    with pytest.raises(WebConnectionError, match="temporary Meter export allowlist"):
        session.post_temporary_export(
            "api/AppReqSetCustomMessage/_000_002_IMP003",
            {"func": "PSL_UNRELATED_WRITE"},
        )


def test_parse_user_and_track_attribution_schema() -> None:
    user_payload = {
        "MFP": {
            "AuthCounterList": {
                "AuthCounter": {
                    "AuthNo": "7",
                    "UserName": "operator-a",
                    "TotalCounterList": {"Counter": [{"Type": "Total", "Count": "42"}]},
                }
            }
        }
    }
    values = AuthenticatedWebConnectionCounterConnector._parse_attributed_payload(user_payload, "user")
    assert values[0].canonical_field == "counter.user.total.total"
    assert values[0].subject_id == "7"
    assert values[0].subject_name == "operator-a"


class MemoryStore:
    def __init__(self, credential: AdminCredential | None) -> None:
        self.credential = credential

    def save(self, _host: str, credential: AdminCredential) -> None:
        self.credential = credential

    def load(self, _host: str) -> AdminCredential | None:
        return self.credential

    def delete(self, _host: str) -> None:
        self.credential = None


class FailingAdminConnector:
    def __init__(self) -> None:
        self.attempts = 0

    def collect_with_credential(
        self,
        _host: str,
        _credential: AdminCredential,
        **_kwargs,
    ):
        self.attempts += 1
        raise WebConnectionAuthenticationError("rejected")


class PublicConnector:
    def collect_result(self, _host: str) -> WebCounterCollection:
        value = WebCounterValue("counter.total.total", "Total", 2339, "Total", "public")
        return WebCounterCollection((value,), "web_connection_public", WebAuthState.PUBLIC)


class FailingPublicConnector:
    def collect_result(self, _host: str) -> WebCounterCollection:
        raise WebConnectionError("public session unavailable")


class AdminRequiredPublicConnector:
    def collect_result(self, _host: str) -> WebCounterCollection:
        raise WebConnectionAuthenticationError("administrator required")


class LegacyPublicConnector:
    def __init__(self) -> None:
        self.hosts: list[str] = []

    def collect_result(self, host: str, *, scheme: str = "http") -> WebCounterCollection:
        self.hosts.append(f"{scheme}://{host}")
        value = WebCounterValue("counter.total.total", "Total", 25_121, "Total", "legacy")
        return WebCounterCollection((value,), "web_connection_legacy_xml_public", WebAuthState.PUBLIC)


class LegacyAdminConnector:
    def __init__(self) -> None:
        self.hosts: list[str] = []

    def collect_with_credential(
        self,
        host: str,
        _credential: AdminCredential,
        *,
        scheme: str = "https",
    ) -> WebCounterCollection:
        self.hosts.append(f"{scheme}://{host}")
        value = WebCounterValue("counter.total.total", "Total", 243_744, "Total", "legacy-admin")
        return WebCounterCollection((value,), "web_connection_legacy_xml_admin", WebAuthState.ADMIN)


class SecondFactoryPasswordLegacyAdminConnector(LegacyAdminConnector):
    def __init__(self) -> None:
        super().__init__()
        self.passwords: list[str] = []

    def collect_with_credential(
        self,
        host: str,
        credential: AdminCredential,
        *,
        scheme: str = "https",
    ) -> WebCounterCollection:
        self.passwords.append(credential.password)
        if credential.password != PUBLIC_FACTORY_ADMIN_PASSWORDS[1]:
            raise WebConnectionAuthenticationError("rejected")
        return super().collect_with_credential(host, credential, scheme=scheme)


def test_meter_reader_falls_back_to_public_once_and_exports_no_credential(tmp_path) -> None:
    password = secrets.token_urlsafe(18)
    admin = FailingAdminConnector()
    reader = MeterReader(
        MemoryStore(AdminCredential(password=password)),
        public_connector=PublicConnector(),
        admin_connector=admin,
    )

    reading = reader.read("10.0.0.5")
    assert admin.attempts == 1
    assert reading.auth_state == WebAuthState.PUBLIC_FALLBACK
    assert reading.counters[0].count == 2339

    json_path = export_meter_json(reading, tmp_path / "meter.json")
    csv_path = export_meter_csv(reading, tmp_path / "meter.csv")
    combined = json_path.read_text(encoding="utf-8") + csv_path.read_text(encoding="utf-8-sig")
    assert password not in combined
    assert "counter.total.total" in combined
    assert json.loads(json_path.read_text(encoding="utf-8"))["schema_version"] == "komi.meter.reading.v1"


def test_meter_reader_preserves_rejected_admin_error_when_public_is_unavailable() -> None:
    reader = MeterReader(
        MemoryStore(AdminCredential(password=secrets.token_urlsafe(18))),
        public_connector=FailingPublicConnector(),
        admin_connector=FailingAdminConnector(),
    )

    with pytest.raises(WebConnectionAuthenticationError, match="rejected"):
        reader.read("10.0.0.5")


def test_meter_reader_does_not_retry_factory_passwords_after_customer_password_fails() -> None:
    admin = FailingAdminConnector()
    reader = MeterReader(
        MemoryStore(AdminCredential(password=secrets.token_urlsafe(18))),
        public_connector=AdminRequiredPublicConnector(),
        admin_connector=admin,
    )

    with pytest.raises(WebConnectionAuthenticationError, match="rejected"):
        reader.read("10.0.0.5")

    assert admin.attempts == 1


def test_meter_reader_routes_confirmed_press_to_public_legacy_xml_without_admin_login() -> None:
    public = LegacyPublicConnector()
    admin = LegacyAdminConnector()
    reader = MeterReader(
        MemoryStore(AdminCredential(password=secrets.token_urlsafe(18))),
        legacy_public_connector=public,
        legacy_admin_connector=admin,
    )

    reading = reader.read("10.0.0.5", model="KONICA MINOLTA AccurioPress C5070")

    assert reading.source == "web_connection_legacy_xml_public"
    assert reading.counters[0].count == 25_121
    assert public.hosts == ["http://10.0.0.5"]
    assert admin.hosts == []
    assert any("ไม่เปิดเผยสถานะ User Authentication" in warning for warning in reading.warnings)


def test_meter_reader_routes_c458_to_bounded_admin_legacy_xml() -> None:
    admin = LegacyAdminConnector()
    reader = MeterReader(
        MemoryStore(AdminCredential(password=secrets.token_urlsafe(18))),
        legacy_public_connector=LegacyPublicConnector(),
        legacy_admin_connector=admin,
    )

    reading = reader.read("10.0.0.5", model="KONICA MINOLTA bizhub C458")

    assert reading.source == "web_connection_legacy_xml_admin"
    assert reading.counters[0].count == 243_744
    assert admin.hosts == ["https://10.0.0.5"]


def test_meter_reader_tries_two_public_factory_passwords_in_order_and_remembers_success() -> None:
    store = MemoryStore(None)
    admin = SecondFactoryPasswordLegacyAdminConnector()
    reader = MeterReader(
        store,
        legacy_public_connector=LegacyPublicConnector(),
        legacy_admin_connector=admin,
    )

    reading = reader.read("10.0.0.5", model="KONICA MINOLTA bizhub C458")

    assert admin.passwords == list(PUBLIC_FACTORY_ADMIN_PASSWORDS)
    assert reading.auth_state == WebAuthState.ADMIN
    assert store.credential is not None
    assert store.credential.password == PUBLIC_FACTORY_ADMIN_PASSWORDS[1]


def test_meter_reader_requests_customer_password_after_both_public_factory_passwords_fail() -> None:
    admin = FailingAdminConnector()
    reader = MeterReader(
        MemoryStore(None),
        legacy_admin_connector=admin,
    )

    with pytest.raises(
        WebConnectionAuthenticationError,
        match="รหัสเริ่มต้นของเครื่องทั้ง 2 แบบไม่ผ่าน",
    ):
        reader.read("10.0.0.5", model="KONICA MINOLTA bizhub C458")

    assert admin.attempts == 2


def test_public_connector_still_parses_existing_total_schema() -> None:
    values = WebConnectionCounterConnector._parse_total_payload(total_payload())
    assert {item.canonical_field: item.count for item in values}["counter.total.total"] == 2339


def test_meter_all_rows_keeps_every_web_connection_counter() -> None:
    values = [
        WebCounterValue("counter.total.total", "Total", 2339, "Total", "MFP.Total"),
        WebCounterValue("counter.copy.bw_total", "Copy BW", 124, "Copy", "MFP.Copy"),
        WebCounterValue(
            "counter.user.total.total",
            "User total",
            42,
            "Total",
            "MFP.AuthCounter[7]",
            subject_type="user",
            subject_id="7",
            subject_name="operator-a",
        ),
    ]
    reading = MeterReading.create(
        "10.0.0.5",
        values,
        "web_connection_admin_read_only",
        WebAuthState.ADMIN,
    )

    rows = meter_counter_rows(reading)

    assert len(rows) == 3
    assert {row[0] for row in rows} == {item.canonical_field for item in values}
    assert rows[2][4] == "operator-a"


def test_parse_meter_export_tsv_keeps_all_rows_in_memory() -> None:
    payload = b"User Name\tTotal\tColor\r\noperator-a\t42\t12\r\noperator-b\t7\t0\r\n"

    table = parse_meter_export(payload, "User")

    assert table.columns == ("User Name", "Total", "Color")
    assert table.rows == (("operator-a", "42", "12"), ("operator-b", "7", "0"))
    assert table.raw_text.startswith("User Name")
    assert table.delimiter == "\t"


def test_subject_name_map_skips_meter_metadata_and_multiline_headers() -> None:
    payload = (
        "Machine Name\t\tC450i\r\n"
        "Serial No.\t\tAA7R041000302\r\n"
        "Date\t\t20/7/2026 8:27\r\n"
        "User Name\tTotal Counter\tNo. of Prints Counter\r\n"
        "\t\tTotal\r\n"
        "DMS\t2\t2\r\n"
        "Public\t0\t0\r\n"
    ).encode("utf-16")

    table = parse_meter_export(payload, "User")

    assert subject_name_map(table) == {"1": "DMS", "2": "Public"}


class AdminConnectorWithUnnamedUser:
    def collect_with_credential(self, _host: str, _credential: AdminCredential) -> WebCounterCollection:
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
        return WebCounterCollection((value,), "web_connection_admin_read_only", WebAuthState.ADMIN)


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


def test_meter_reader_enriches_missing_user_name_from_ram_export() -> None:
    export_reader = UserNameExportReader()
    reader = MeterReader(
        MemoryStore(AdminCredential(password=secrets.token_urlsafe(18))),
        admin_connector=AdminConnectorWithUnnamedUser(),
        export_reader=export_reader,
    )

    reading = reader.read("10.0.0.5")

    assert reading.counters[0].subject_id == "1"
    assert reading.counters[0].subject_name == "DMS"
    assert export_reader.calls == [("10.0.0.5", "User")]


def test_meter_reader_does_not_start_name_export_without_explicit_reader() -> None:
    reader = MeterReader(
        MemoryStore(AdminCredential(password=secrets.token_urlsafe(18))),
        admin_connector=AdminConnectorWithUnnamedUser(),
    )

    reading = reader.read("10.0.0.5")

    assert reading.counters[0].subject_id == "1"
    assert reading.counters[0].subject_name == ""


def test_opted_in_meter_reader_loads_names_once_then_uses_memory_cache(monkeypatch) -> None:
    export_reader = UserNameExportReader()
    monkeypatch.setattr(
        meter_module,
        "MeterExportReader",
        lambda *_args, **_kwargs: export_reader,
    )
    reader = MeterReader(
        MemoryStore(AdminCredential(password=secrets.token_urlsafe(18))),
        admin_connector=AdminConnectorWithUnnamedUser(),
        allow_implicit_name_export=True,
    )

    first = reader.read("10.0.0.5")
    second = reader.read("10.0.0.5")

    assert first.counters[0].subject_name == "DMS"
    assert second.counters[0].subject_name == "DMS"
    assert export_reader.calls == [("10.0.0.5", "User")]


class FakeMeterExportSession(FakeSession):
    def __init__(self, host: str, **kwargs) -> None:
        super().__init__(host, **kwargs)
        self.auth_type = "Internal"
        self.track_type = "On"

    def get(self, path: str, *, expect_json: bool = True):
        self.calls.append(("GET", path))
        if not expect_json:
            return {}
        return {
            "MFP": {
                "LoginMode": self.login_mode,
                "Token": "ephemeral-token",
                "AuthSetting": {
                    "AuthMode": {"AuthType": self.auth_type},
                    "TrackMode": {"TrackType": self.track_type},
                },
            }
        }

    def post_temporary_export(self, path: str, body: dict[str, object]):
        self.calls.append(("POST_TEMP", path))
        if body["func"] == "PSL_AS_CLR_IMP":
            return {"MFP": {"Result": {"ResultInfo": "Ack"}}}
        assert body["AS_CNL_R_SEL"] == "User"
        assert body["AS_CL_R_EX"] == "on"
        return {"MFP": {"RedirectUrl": "progress", "Interval": 0}}

    def post_export_progress(self, path: str):
        self.calls.append(("POST_PROGRESS", path))
        return {
            "MFP": {
                "Message": {"Item": {"#text": "ReadyToDownload"}},
                "CgiName": "PSL_FILE_DOWNLOAD",
                "UserCgiNameNormal": "a_filedownload",
                "UserCgiName": "a_meter.cgi",
                "CustomParam": "temporary-id",
            }
        }

    def download_temporary_export(self, path: str, fields: dict[str, str]) -> bytes:
        self.calls.append(("POST_DOWNLOAD", path))
        assert fields["h_token"] == "ephemeral-token"
        return b"User\tTotal\noperator-a\t42\n"


def test_meter_count_export_downloads_to_memory_then_cleans_and_logs_out() -> None:
    session = FakeMeterExportSession("10.0.0.5")
    connector = MeterCountExportConnector(session_factory=lambda *_args, **_kwargs: session)

    table = connector.collect("10.0.0.5", AdminCredential(password=secrets.token_urlsafe(18)), "User")

    assert table.rows == (("operator-a", "42"),)
    assert ("POST_DOWNLOAD", "a_meter.cgi") in session.calls
    assert ("POST_TEMP", "api/AppReqSetCustomMessage/_000_002_IMP014") in session.calls
    assert session.calls[-1] == ("POST_FORM", "a_user.cgi")
    assert session.cleared is True


def test_meter_count_export_stops_when_feature_is_disabled_but_logs_out() -> None:
    session = FakeMeterExportSession("10.0.0.5")
    session.auth_type = "None"
    connector = MeterCountExportConnector(session_factory=lambda *_args, **_kwargs: session)

    with pytest.raises(WebConnectionError, match="ยังไม่ได้เปิด User Authentication"):
        connector.collect("10.0.0.5", AdminCredential(password=secrets.token_urlsafe(18)), "User")

    assert not any(call[0] == "POST_TEMP" for call in session.calls)
    assert session.calls[-1] == ("POST_FORM", "a_user.cgi")
    assert session.cleared is True


def test_meter_count_export_reports_device_rejection_detail_and_cleans_up() -> None:
    session = FakeMeterExportSession("10.0.0.5")

    def reject(_path: str, body: dict[str, object]):
        session.calls.append(("POST_TEMP", _path))
        if body["func"] == "PSL_AS_CLR_IMP":
            return {"MFP": {"Result": {"ResultInfo": "Ack"}}}
        return {"Result": {"ResultInfo": "Cannot find CustomID in the file."}}

    session.post_temporary_export = reject
    connector = MeterCountExportConnector(session_factory=lambda *_args, **_kwargs: session)

    with pytest.raises(WebConnectionError, match="Cannot find CustomID"):
        connector.collect("10.0.0.5", AdminCredential(password=secrets.token_urlsafe(18)), "User")

    assert ("POST_TEMP", "api/AppReqSetCustomMessage/_000_002_IMP014") in session.calls
    assert session.calls[-1] == ("POST_FORM", "a_user.cgi")
    assert session.cleared is True
