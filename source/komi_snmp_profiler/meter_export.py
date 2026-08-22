from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass
from typing import Literal

from .connectors import (
    AuthenticatedWebConnectionCounterConnector,
    ReadOnlyWebConnectionSession,
    WebConnectionAuthenticationError,
    WebConnectionError,
    _nested,
)
from .credential_store import AdminCredential, CredentialStore

MeterExportKind = Literal["User", "Track"]


@dataclass(frozen=True)
class MeterExportTable:
    kind: MeterExportKind
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    raw_text: str
    encoding: str
    delimiter: str


def parse_meter_export(payload: bytes, kind: MeterExportKind) -> MeterExportTable:
    """Decode and parse a firmware-dependent Meter Count export without writing it to disk."""
    text = ""
    encoding = ""
    for candidate in ("utf-8-sig", "utf-16", "cp932", "shift_jis"):
        try:
            text = payload.decode(candidate)
            encoding = candidate
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if not encoding:
        text = payload.decode("latin-1")
        encoding = "latin-1"
    if not text.strip():
        raise WebConnectionError("Meter Count export ไม่มีข้อมูล")

    sample = text[:8192]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters="\t,;").delimiter
    except csv.Error:
        delimiter = "\t"
    parsed = [tuple(cell.strip() for cell in row) for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    parsed = [row for row in parsed if any(row)]
    if not parsed:
        raise WebConnectionError("Meter Count export ไม่มีแถวข้อมูล")

    width = max(len(row) for row in parsed)
    first = parsed[0]
    columns = tuple(
        first[index] if index < len(first) and first[index] else f"Column {index + 1}"
        for index in range(width)
    )
    rows = tuple(tuple(row[index] if index < len(row) else "" for index in range(width)) for row in parsed[1:])
    return MeterExportTable(kind, columns, rows, text, encoding, delimiter)


def subject_name_map(table: MeterExportTable) -> dict[str, str]:
    """Map firmware attribution indexes to names from a multi-row Meter export.

    C450i exports start with Machine/Serial/Date metadata and two or more
    heading rows.  ``AppReqGetAuthCounter`` identifies the same rows by a
    one-based ``AuthNo`` but does not return the visible User Name.
    """

    rows = (table.columns, *table.rows)
    expected_headings = {
        "user name",
        "user",
        "account name",
        "account track name",
        "account",
    }
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if row and row[0].strip().casefold() in expected_headings
        ),
        None,
    )
    if header_index is None:
        return {}

    names: dict[str, str] = {}
    for row in rows[header_index + 1 :]:
        name = row[0].strip() if row else ""
        total = row[1].strip().replace(",", "") if len(row) > 1 else ""
        if not name or not total:
            continue
        try:
            float(total)
        except ValueError:
            continue
        names[str(len(names) + 1)] = name
    return names


class MeterCountExportConnector:
    """Download the Web Connection Meter Count PC export into memory and always clean its session."""

    def __init__(
        self,
        *,
        timeout: float = 8.0,
        verify_tls: bool = False,
        max_polls: int = 30,
        session_factory=ReadOnlyWebConnectionSession,
    ) -> None:
        self.timeout = timeout
        self.verify_tls = verify_tls
        self.max_polls = max_polls
        self.session_factory = session_factory

    def collect(self, host: str, credential: AdminCredential, kind: MeterExportKind) -> MeterExportTable:
        if kind not in {"User", "Track"}:
            raise ValueError("Meter export kind ไม่ถูกต้อง")
        session = self.session_factory(host, timeout=self.timeout, verify_tls=self.verify_tls)
        login_attempted = False
        export_started = False
        token = ""
        failure: Exception | None = None
        table: MeterExportTable | None = None
        try:
            session.prepare_admin_login()
            common = session.get("api/AppReqGetCustomData/_A-00-00001")
            login_attempted = True
            session.post_session_form(
                "login.cgi",
                AuthenticatedWebConnectionCounterConnector._login_fields(common, credential),
            )
            common = session.get("api/AppReqGetCustomData/_A-00-00001")
            if _nested(common, "MFP.LoginMode") != "Admin":
                raise WebConnectionAuthenticationError("Administrator login ไม่สำเร็จ; ไม่ลองรหัสซ้ำอัตโนมัติ")
            self._ensure_feature(common, kind)
            token = str(_nested(common, "MFP.Token", ""))
            session.prepare_meter_export(token)
            export_started = True
            status = session.post_temporary_export(
                "api/AppReqSetCustomMessage/_000_002_IMP003",
                {
                    "h_token": token,
                    "func": "PSL_AS_CNL_EXP",
                    "AS_CNL_R_SEL": kind,
                    "AS_CL_R_EX": "on",
                    "SMB_H_CHOOSE_TYPE": "",
                    "SMB_H_HOST_NAME": "",
                    "SMB_H_USER_NAME": "",
                    "SMB_H_FILE_PATH": "",
                    "SMB_H_FILE_TITLE": "",
                },
            )
            ready = self._wait_until_ready(session, status)
            download_path = str(_nested(ready, "MFP.UserCgiName", ""))
            payload = session.download_temporary_export(
                download_path,
                {
                    "func": str(_nested(ready, "MFP.CgiName", "")),
                    "h_token": token,
                    "cginame1": str(_nested(ready, "MFP.UserCgiNameNormal", "")),
                    "cginame2": download_path,
                    "H_BAK": "0",
                    "H_TAB": "",
                    "H_DLV": str(_nested(ready, "MFP.CustomParam", "")),
                },
            )
            table = parse_meter_export(payload, kind)
        except Exception as err:
            failure = err
        finally:
            if export_started:
                try:
                    session.post_temporary_export(
                        "api/AppReqSetCustomMessage/_000_002_IMP014",
                        {"func": "PSL_AS_CLR_IMP", "h_token": token},
                    )
                except (WebConnectionError, ValueError):
                    if failure is None:
                        failure = WebConnectionError("รับ Meter export แล้ว แต่ล้าง temporary export ไม่สำเร็จ")
                    else:
                        failure.add_note("temporary Meter export cleanup failed")
            if login_attempted:
                try:
                    session.post_session_form("a_user.cgi", {"func": "PSL_ACO_LGO", "h_token": ""})
                except WebConnectionError:
                    if failure is None:
                        failure = WebConnectionError("รับ Meter export แล้ว แต่ logout ไม่สำเร็จ")
                    else:
                        failure.add_note("Administrator logout failed")
            session.clear()
        if failure is not None:
            raise failure
        if table is None:  # pragma: no cover - defensive guard
            raise WebConnectionError("ไม่ได้รับ Meter Count export")
        return table

    @staticmethod
    def _ensure_feature(common: dict[str, object], kind: MeterExportKind) -> None:
        path = "MFP.AuthSetting.AuthMode.AuthType" if kind == "User" else "MFP.AuthSetting.TrackMode.TrackType"
        if str(_nested(common, path, "None")) in {"", "None"}:
            label = "User Authentication" if kind == "User" else "Account Track"
            raise WebConnectionError(f"เครื่องนี้ยังไม่ได้เปิด {label}")

    def _wait_until_ready(
        self,
        session: ReadOnlyWebConnectionSession,
        status: dict[str, object],
    ) -> dict[str, object]:
        for _attempt in range(self.max_polls + 1):
            if self._is_ready(status):
                return status
            result_info = _nested(status, "Result.ResultInfo")
            if result_info is None:
                result_info = _nested(status, "MFP.Result.ResultInfo")
            if result_info not in {None, "", "Ack"}:
                raise WebConnectionError(f"เครื่องปฏิเสธ Meter export: {result_info}")
            redirect = str(_nested(status, "MFP.RedirectUrl", ""))
            if redirect not in ReadOnlyWebConnectionSession.TEMP_PROGRESS_PATHS:
                raise WebConnectionError("เครื่องไม่คืนสถานะ Meter export ที่รองรับ")
            interval_ms = min(max(int(_nested(status, "MFP.Interval", 0)), 0), 2000)
            if interval_ms:
                time.sleep(interval_ms / 1000)
            status = session.post_export_progress(redirect)
        raise WebConnectionError("Meter Count export ใช้เวลานานเกินกำหนด")

    @staticmethod
    def _is_ready(status: dict[str, object]) -> bool:
        items = _nested(status, "MFP.Message.Item", [])
        if isinstance(items, dict):
            items = [items]
        return isinstance(items, list) and any(
            isinstance(item, dict) and item.get("#text") == "ReadyToDownload" for item in items
        )


class MeterExportReader:
    def __init__(
        self,
        credential_store: CredentialStore,
        *,
        connector: MeterCountExportConnector | None = None,
    ) -> None:
        self.credential_store = credential_store
        self.connector = connector or MeterCountExportConnector()

    def read(self, host: str, kind: MeterExportKind) -> MeterExportTable:
        credential = self.credential_store.load(host)
        if credential is None:
            raise WebConnectionError("ไม่พบ Administrator credential")
        return self.connector.collect(host, credential, kind)
