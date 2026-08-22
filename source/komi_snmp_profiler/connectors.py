from __future__ import annotations

import json
import re
import ssl
from dataclasses import dataclass
from http.cookiejar import Cookie, CookieJar
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener

from .credential_store import AdminCredential
from .models import WebAuthState, WebCounterValue


class WebConnectionError(RuntimeError):
    """Raised when a bizhub Web Connection counter request cannot be completed."""


class WebConnectionAuthenticationError(WebConnectionError):
    """Raised after one rejected Administrator login attempt; callers must not retry automatically."""


class AccountCounterConnector(Protocol):
    """Extension boundary for model-specific Web Connection or counter export readers."""

    def supported(self, model: str) -> bool: ...

    def collect(self, host: str) -> list[WebCounterValue]: ...


@dataclass(frozen=True)
class WebCounterCollection:
    counters: tuple[WebCounterValue, ...]
    source: str
    auth_state: WebAuthState
    warnings: tuple[str, ...] = ()


def _snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).replace("__", "_").lower()


def _as_list(value: object) -> list[dict[str, object]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _nested(payload: dict[str, object], path: str, default: object = None) -> object:
    value: object = payload
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


class ReadOnlyWebConnectionSession:
    """Cookie session with strict read and temporary Meter-export allowlists."""

    GET_PATHS = {
        "index.html",
        "spa_main.html",
        "spa_login.html",
        "login_ex.json",
        "top.xml",
        "spa_000_002_IMP000.tmpl.html",
        "spa_000_002_IMP003.tmpl.html",
        "a_system_impexp.json",
        "api/AppReqGetCustomData/_A-00-00001",
        "api/AppReqGetCustomData/_000_002_IMP000",
    }
    JSON_POST_PATHS = {
        "api/AppReqGetCounterInfo/_Total",
        "api/AppReqGetAuthCounter",
        "api/AppReqGetTrackCounterInfo",
    }
    SESSION_FORM_PATHS = {"login.cgi", "a_user.cgi"}
    TEMP_EXPORT_FUNCTIONS = {
        "api/AppReqSetCustomMessage/_000_002_IMP003": "PSL_AS_CNL_EXP",
        "api/AppReqSetCustomMessage/_000_002_IMP014": "PSL_AS_CLR_IMP",
    }
    TEMP_PROGRESS_PATHS = {"progress", "result.html"}
    METER_EXPORT_TELEMETRY_PATH = "api/Request/_CommonExecutor"

    def __init__(self, host: str, *, timeout: float = 5.0, verify_tls: bool = False) -> None:
        self.timeout = timeout
        self.base_url = f"https://{host}/wcd"
        self.cookies = CookieJar()
        context = ssl.create_default_context()
        if not verify_tls:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        self.opener = build_opener(HTTPCookieProcessor(self.cookies), HTTPSHandler(context=context))

    def get(self, path: str, *, expect_json: bool = True) -> dict[str, object]:
        if path not in self.GET_PATHS:
            raise WebConnectionError(f"endpoint ไม่อยู่ใน read-only allowlist: {path}")
        raw = self._request(path, method="GET")
        return json.loads(raw) if expect_json else {}

    def prepare_admin_login(self) -> None:
        """Create the same read-only login context as the Web Connection UI."""
        for path in ("spa_main.html", "spa_login.html", "login_ex.json", "top.xml"):
            self.get(path, expect_json=False)

    def prepare_meter_export(self, token: str) -> None:
        """Initialize the firmware's temporary Meter-export CustomID context."""
        # These client-side UI flags are normally created by Integrated_main.js.
        # The firmware expects the cookie names (including blank cou/adm) when
        # selecting the CustomID table for the Meter Count screen.
        for name, value in {
            "pf": "PC",
            "uatype": "NN",
            "vm": "Html",
            "lang": "En",
            "selno": "En",
            "menuType": "Admin",
            "sourcePage": "1",
            "loginState": "true",
            "webUI": "new",
            "cou": "",
            "adm": "",
        }.items():
            self._set_session_cookie(name, value)
        self.get("spa_000_002_IMP000.tmpl.html", expect_json=False)
        self.post_temporary_export(
            "api/AppReqSetCustomMessage/_000_002_IMP014",
            {"func": "PSL_AS_CLR_IMP", "h_token": token},
        )
        for path in (
            "api/AppReqGetCustomData/_000_002_IMP000",
            "spa_000_002_IMP003.tmpl.html",
            "a_system_impexp.json",
        ):
            self.get(path, expect_json=False)
        self.post_meter_export_telemetry()

    def _set_session_cookie(self, name: str, value: str) -> None:
        domain = urlsplit(self.base_url).hostname or ""
        self.cookies.set_cookie(
            Cookie(
                version=0,
                name=name,
                value=value,
                port=None,
                port_specified=False,
                domain=domain,
                domain_specified=False,
                domain_initial_dot=False,
                path="/wcd",
                path_specified=True,
                secure=True,
                expires=None,
                discard=True,
                comment=None,
                comment_url=None,
                rest={},
                rfc2109=False,
            )
        )

    def post_meter_export_telemetry(self) -> None:
        """Mirror the UI's fixed PcmLog initialization without accepting arbitrary calls."""
        self._request(
            self.METER_EXPORT_TELEMETRY_PATH,
            method="POST",
            data=b'{"WebApiKey":"PcmLog"}',
            content_type="application/x-www-form-urlencoded; charset=UTF-8",
        )

    def post_json(self, path: str, body: dict[str, object]) -> dict[str, object]:
        if path not in self.JSON_POST_PATHS or "AppReqSet" in path:
            raise WebConnectionError(f"endpoint ไม่อยู่ใน read-only allowlist: {path}")
        raw = self._request(
            path,
            method="POST",
            data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            content_type="application/json",
        )
        return json.loads(raw)

    def post_session_form(self, path: str, fields: dict[str, str]) -> bytes:
        if path not in self.SESSION_FORM_PATHS:
            raise WebConnectionError(f"endpoint ไม่อยู่ใน session allowlist: {path}")
        return self._request(
            path,
            method="POST",
            data=urlencode(fields).encode("utf-8"),
            content_type="application/x-www-form-urlencoded",
        )

    def post_temporary_export(self, path: str, body: dict[str, object]) -> dict[str, object]:
        expected_func = self.TEMP_EXPORT_FUNCTIONS.get(path)
        if expected_func is None or body.get("func") != expected_func:
            raise WebConnectionError(f"endpoint ไม่อยู่ใน temporary Meter export allowlist: {path}")
        if path.endswith("IMP014"):
            data = urlencode({key: str(value) for key, value in body.items()}).encode("utf-8")
        else:
            # Web Connection sends a raw JSON body with this legacy content type.
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        raw = self._request(
            path,
            method="POST",
            data=data,
            content_type="application/x-www-form-urlencoded; charset=UTF-8",
        )
        if path.endswith("IMP014") and not raw.lstrip().startswith(b"{"):
            return {}
        return json.loads(raw)

    def post_export_progress(self, path: str) -> dict[str, object]:
        if path not in self.TEMP_PROGRESS_PATHS:
            raise WebConnectionError(f"progress endpoint ไม่ปลอดภัย: {path}")
        return json.loads(
            self._request(
                path,
                method="POST",
                data=b"",
                content_type="application/x-www-form-urlencoded",
            )
        )

    def download_temporary_export(self, path: str, fields: dict[str, str]) -> bytes:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", path) or ".." in path:
            raise WebConnectionError("temporary download endpoint ไม่ปลอดภัย")
        return self._request(
            path,
            method="POST",
            data=urlencode(fields).encode("utf-8"),
            content_type="application/x-www-form-urlencoded",
        )

    def _request(
        self,
        path: str,
        *,
        method: str,
        data: bytes | None = None,
        content_type: str | None = None,
    ) -> bytes:
        headers = {} if content_type is None else {"Content-Type": content_type}
        request = Request(f"{self.base_url}/{path}", data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as err:
            raise WebConnectionError(f"อ่าน Web Connection ไม่สำเร็จ: {type(err).__name__}") from err

    def clear(self) -> None:
        self.cookies.clear()


class WebConnectionCounterConnector:
    """Read public counter data from the bizhub Web Connection JSON API."""

    def __init__(
        self,
        *,
        timeout: float = 5.0,
        verify_tls: bool = False,
        session_factory=ReadOnlyWebConnectionSession,
    ) -> None:
        self.timeout = timeout
        self.verify_tls = verify_tls
        self.session_factory = session_factory

    def supported(self, model: str) -> bool:
        return "bizhub" in model.lower() or not model

    def collect(self, host: str) -> list[WebCounterValue]:
        return list(self.collect_result(host).counters)

    def collect_result(self, host: str) -> WebCounterCollection:
        session = self.session_factory(host, timeout=self.timeout, verify_tls=self.verify_tls)
        try:
            session.get("index.html", expect_json=False)
            common = session.get("api/AppReqGetCustomData/_A-00-00001")
            if _nested(common, "MFP.LoginMode") != "PublicUser":
                raise WebConnectionError("Web Connection public session ไม่พร้อมใช้งาน")
            payload = session.post_json("api/AppReqGetCounterInfo/_Total", {"NetworkType": "NW1"})
            counters = self._parse_total_payload(payload)
            return WebCounterCollection(tuple(counters), "web_connection_public", WebAuthState.PUBLIC)
        except json.JSONDecodeError as err:
            raise WebConnectionError("Web Connection คืน JSON ไม่ถูกต้อง") from err
        finally:
            session.clear()

    @classmethod
    def _parse_total_payload(cls, payload: dict[str, object]) -> list[WebCounterValue]:
        mfp = payload.get("MFP", {})
        if not isinstance(mfp, dict) or _nested(mfp, "Result.ResultInfo") != "Ack":
            detail = mfp.get("ErrorDetails") if isinstance(mfp, dict) else None
            raise WebConnectionError(f"Web Connection counter ถูกปฏิเสธ: {detail or 'unknown response'}")
        info = mfp.get("UserCounterInfo")
        if not isinstance(info, dict):
            raise WebConnectionError("Web Connection ไม่คืน UserCounterInfo")
        return cls._parse_counter_info(info)

    @staticmethod
    def _parse_counter_info(
        info: dict[str, object],
        *,
        source_root: str = "MFP.UserCounterInfo",
        subject_type: str | None = None,
        subject_id: str | None = None,
        subject_name: str | None = None,
    ) -> list[WebCounterValue]:
        counters: list[WebCounterValue] = []

        def append_list(items: object, *, category: str, prefix: str, source: str) -> None:
            for item in _as_list(items):
                if "Type" not in item or "Count" not in item:
                    continue
                counter_type = str(item["Type"])
                raw_count = str(item["Count"])
                try:
                    count: int | float = int(raw_count)
                except ValueError:
                    count = float(raw_count)
                counters.append(
                    WebCounterValue(
                        canonical_field=f"{prefix}.{_snake(counter_type)}",
                        label=f"{category}: {counter_type}",
                        count=count,
                        category=category,
                        source_path=f"{source}[Type={counter_type}]",
                        subject_type=subject_type,
                        subject_id=subject_id,
                        subject_name=subject_name,
                    )
                )

        total = info.get("TotalCounterList", {})
        if isinstance(total, dict):
            append_list(
                total.get("TotalCounter", total.get("Counter")),
                category="Total",
                prefix="counter.total" if subject_type is None else f"counter.{subject_type}.total",
                source=f"{source_root}.TotalCounterList.Counter",
            )

        paper = info.get("PaperSheetCounter", {})
        if isinstance(paper, dict):
            for key, color in (
                ("BlackCounterList", "black"),
                ("FullColorCounterList", "full_color"),
                ("DoubleColorCounterList", "single_two_color"),
            ):
                group = paper.get(key, {})
                if not isinstance(group, dict):
                    continue
                item_key = key.removesuffix("List")
                append_list(
                    group.get(item_key, group.get("Counter")),
                    category=f"Paper size {color}",
                    prefix=f"counter.paper.{color}",
                    source=f"{source_root}.PaperSheetCounter.{key}.{item_key}",
                )

        for list_key, category, prefix in (
            ("CopyCounterList", "Copy", "counter.copy"),
            ("PrintCounterList", "Print", "counter.print"),
            ("ScanFaxCounterList", "Scan/Fax", "counter.scan_fax"),
        ):
            group = info.get(list_key, {})
            if isinstance(group, dict):
                subject_prefix = (
                    prefix if subject_type is None else prefix.replace("counter", f"counter.{subject_type}", 1)
                )
                append_list(
                    group.get(list_key.removesuffix("List"), group.get("Counter")),
                    category=category,
                    prefix=subject_prefix,
                    source=f"{source_root}.{list_key}.Counter",
                )
        return counters


class AuthenticatedWebConnectionCounterConnector(WebConnectionCounterConnector):
    """Open one Administrator session, read counters, and always log out and clear cookies."""

    def collect_with_credential(self, host: str, credential: AdminCredential) -> WebCounterCollection:
        session = self.session_factory(host, timeout=self.timeout, verify_tls=self.verify_tls)
        login_attempted = False
        result: WebCounterCollection | None = None
        failure: Exception | None = None
        try:
            session.prepare_admin_login()
            common = session.get("api/AppReqGetCustomData/_A-00-00001")
            login_attempted = True
            session.post_session_form("login.cgi", self._login_fields(common, credential))
            common = session.get("api/AppReqGetCustomData/_A-00-00001")
            if _nested(common, "MFP.LoginMode") != "Admin":
                raise WebConnectionAuthenticationError(
                    "Administrator login ไม่สำเร็จ; แอปจะไม่ลองรหัสซ้ำอัตโนมัติเพื่อลดความเสี่ยง account lockout"
                )
            total_payload = session.post_json("api/AppReqGetCounterInfo/_Total", {"NetworkType": "NW1"})
            counters = self._parse_total_payload(total_payload)
            attributed, warnings = self._collect_attributed(session, common)
            counters.extend(attributed)
            result = WebCounterCollection(
                tuple(counters),
                "web_connection_admin_read_only",
                WebAuthState.ADMIN,
                tuple(warnings),
            )
        except Exception as err:
            failure = err
        finally:
            if login_attempted:
                try:
                    session.post_session_form("a_user.cgi", {"func": "PSL_ACO_LGO", "h_token": ""})
                except WebConnectionError:
                    if failure is None:
                        failure = WebConnectionError("อ่าน Meter ได้แต่ logout Administrator session ไม่สำเร็จ")
                    else:
                        failure.add_note("Administrator logout request failed; local cookies were cleared")
            session.clear()
        if failure is not None:
            raise failure
        if result is None:  # pragma: no cover - defensive guard
            raise WebConnectionError("ไม่ได้ผลลัพธ์จาก Administrator session")
        return result

    @staticmethod
    def _login_fields(common: dict[str, object], credential: AdminCredential) -> dict[str, str]:
        # Administrator is selected by R_ADM.  C450i firmware rejects later
        # Import/Export operations when the display account name is also sent
        # as username, even though the initial login appears successful.
        return {
            "func": "PSL_LP1_LOG",
            "AuthType": str(_nested(common, "MFP.AuthSetting.AuthMode.AuthType", "")),
            "TrackType": "",
            "ExtSvType": "0",
            "PswcForm": "",
            "Mode": "",
            "publicuser": "",
            "username": "",
            "password": credential.password,
            "AuthorityType": "",
            "R_ADM": "AdminAdmin",
            "ExtServ": "0",
            "ViewMode": "",
            "BrowserMode": "",
            "Lang": "",
            "trackname": "",
            "trackpassword": "",
        }

    def _collect_attributed(
        self,
        session: ReadOnlyWebConnectionSession,
        common: dict[str, object],
    ) -> tuple[list[WebCounterValue], list[str]]:
        counters: list[WebCounterValue] = []
        warnings: list[str] = []
        token = str(_nested(common, "MFP.Token", ""))
        auth_type = str(_nested(common, "MFP.AuthSetting.AuthMode.AuthType", "None"))
        track_type = str(_nested(common, "MFP.AuthSetting.TrackMode.TrackType", "None"))
        if auth_type not in {"", "None"}:
            try:
                max_user = self._bounded_max(_nested(common, "MFP.MaxUserNW2", 100))
                payload = session.post_json(
                    "api/AppReqGetAuthCounter",
                    {
                        "UserCounterListCondition": {
                            "UserType": "User",
                            "ObtainCondition": {"Type": "IndexList", "IndexRange": {"Start": 1, "End": max_user}},
                        },
                        "Token": token,
                    },
                )
                counters.extend(self._parse_attributed_payload(payload, "user"))
            except (TypeError, ValueError, WebConnectionError):
                warnings.append("เปิด User Authentication อยู่ แต่ยังอ่าน User counter schema ของ firmware นี้ไม่ได้")
        if track_type not in {"", "None"}:
            try:
                max_track = self._bounded_max(_nested(common, "MFP.MaxTrack", 100))
                payload = session.post_json(
                    "api/AppReqGetTrackCounterInfo",
                    {
                        "TrackCounterListCondition": {
                            "TrackType": "Private",
                            "ObtainCondition": {"Type": "IndexList", "IndexRange": {"Start": 1, "End": max_track}},
                            "BackUp": "false",
                        },
                        "Token": token,
                    },
                )
                counters.extend(self._parse_attributed_payload(payload, "account"))
            except (TypeError, ValueError, WebConnectionError):
                warnings.append("เปิด Account Track อยู่ แต่ยังอ่าน Track counter schema ของ firmware นี้ไม่ได้")
        return counters, warnings

    @staticmethod
    def _bounded_max(value: object) -> int:
        return max(1, min(int(value), 1000))

    @classmethod
    def _parse_attributed_payload(cls, payload: dict[str, object], subject_type: str) -> list[WebCounterValue]:
        result_info = _nested(payload, "MFP.Result.ResultInfo")
        if result_info not in {None, "Ack"}:
            raise WebConnectionError("Web Connection attribution counter ถูกปฏิเสธ")
        list_key = "AuthCounterList" if subject_type == "user" else "TrackCounterList"
        item_key = "AuthCounter" if subject_type == "user" else "TrackCounter"
        items = _as_list(_nested(payload, f"MFP.{list_key}.{item_key}", []))
        counters: list[WebCounterValue] = []
        for item in items:
            if subject_type == "user":
                subject_id = str(item.get("AuthNo", ""))
                subject_name = str(item.get("UserName", item.get("AuthUserName", "")))
            else:
                subject_id = str(item.get("TrackID", ""))
                subject_name = str(item.get("TrackName", item.get("TrackInfo", "")))
            counters.extend(
                cls._parse_counter_info(
                    item,
                    source_root=f"MFP.{list_key}.{item_key}[{subject_id}]",
                    subject_type=subject_type,
                    subject_id=subject_id,
                    subject_name=subject_name,
                )
            )
        return counters
