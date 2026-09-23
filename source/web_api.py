"""Read-only LAN API for KOMI Report V5 Web Edition.

The API reuses the desktop database and reporting services.  It exposes only
report-safe fields, never printer credentials, and never implements a second
billing formula.
"""

from __future__ import annotations

import logging
import os
import re
from collections import OrderedDict, defaultdict
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from typing import Literal
from uuid import uuid4
from threading import Lock
from time import monotonic

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, RootModel

from config import PACKAGE_VERSION
from database import get_cfg, init_db
from observability import configure_logging
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfigRepository
from services.monthly_history import HistoryGranularity, load_usage_history
from services.polling import PollingPolicy
from services.pricing import PricingRepository
from services.report_scope import report_slots
from services.reporting_facade import ReportReadService
from services.peer_sync_authorization import (
    PeerSyncAuthorizationError,
    claim_pairing_window,
    consume_pairing_token,
)
from services.secondary_setup import (
    PEER_SYNC_TOKEN_HEADER,
    primary_discovery_payload,
    primary_setup_snapshot,
)
from services.subject_history import load_subject_history
from services.sync_schedule import build_daily_timeline, load_schedule_windows
from services.usage import current_device_identity

log = logging.getLogger(__name__)
MAX_PAGE_LIMIT = 500
_user_pages_lock = Lock()
_user_pages: OrderedDict[str, tuple[float, tuple[date, date] | None, list[dict]]] = OrderedDict()
_USER_PAGE_TTL = 120.0


def _user_page_snapshot(token: str | None, selected, payload):
    """Keep paged report rows from one immutable read for a bounded interval."""
    now = monotonic()
    with _user_pages_lock:
        for key, (created, _, _) in tuple(_user_pages.items()):
            if now - created > _USER_PAGE_TTL:
                _user_pages.pop(key, None)
        if token:
            saved = _user_pages.get(token)
            if saved is None:
                raise HTTPException(status_code=410, detail="Report page expired; refresh the report")
            if selected is not None and selected != saved[1]:
                raise HTTPException(status_code=400, detail="Report period does not match page")
            _user_pages.move_to_end(token)
            return token, saved[1], saved[2]
        token = uuid4().hex
        _user_pages[token] = (now, selected, payload)
        while len(_user_pages) > 4:
            _user_pages.popitem(last=False)
        return token, selected, payload


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiModel):
    status: str
    server_time: str
    device_count: int
    online_count: int


class DeviceOut(ApiModel):
    slot: int
    name: str
    host: str
    model: str
    serial: str
    status: str
    last_checked_at: str | None
    last_success_at: str | None
    last_total: int | None
    status_detail: str


class DeviceListResponse(ApiModel):
    items: list[DeviceOut]


class PeerDiscoveryResponse(ApiModel):
    contract: str
    ready: bool
    company_name: str
    printer_count: int
    version: str


class PeerContactDocument(ApiModel):
    format: Literal['komi.lan.member.v1']
    group_id: str = Field(pattern='^[0-9a-f]{64}$')
    member_id: str = Field(min_length=1, max_length=256)
    origin: str = Field(min_length=1, max_length=256)
    public_key: str = Field(min_length=43, max_length=44)
    certificate: str = Field(min_length=1, max_length=16384)
    url: str = Field(min_length=1, max_length=300)
    generation: int = Field(ge=1, lt=2**63)


class PeerContactResponse(ApiModel):
    document: PeerContactDocument
    signature: str = Field(min_length=86, max_length=88)
    proof: str = Field(pattern='^[0-9a-f]{64}$')


class PeerPriceOut(ApiModel):
    a3_color: float
    a3_bw: float
    a4_color: float
    a4_bw: float


class PeerDeviceOut(ApiModel):
    slot: int
    name: str
    host: str
    model: str
    serial: str
    tls_mode: str
    tls_fingerprint: str
    prices: PeerPriceOut


class PeerOrganizationOut(ApiModel):
    company_name: str
    first_started_at: str
    primary_installation_id: str


class PeerSettingsOut(ApiModel):
    pricing_mode: str
    billing_day: int
    waste_paper_pct: float
    work_start: str
    work_end: str
    sync_schedule_windows: str = ""


class PeerClaimRequest(ApiModel):
    token: str


class PeerClaimResponse(ApiModel):
    accepted: bool
    expires_in_seconds: int


class PeerSetupSnapshotResponse(ApiModel):
    contract: str
    generated_at: str
    organization: PeerOrganizationOut
    settings: PeerSettingsOut
    devices: list[PeerDeviceOut]


class PeriodOut(ApiModel):
    start: str
    end: str


class PeerSharedOrganizationOut(ApiModel):
    company_name: str
    first_started_at: str


class PeerSharedSettingsOut(ApiModel):
    organization: PeerSharedOrganizationOut
    settings: PeerSettingsOut
    devices: list[PeerDeviceOut]


class PeerSharedDeviceOut(ApiModel):
    slot: int
    name: str
    host: str
    model: str
    serial: str
    tls_mode: str
    tls_fingerprint: str


class PeerDatedPriceOut(PeerPriceOut):
    # Preserve JSON number representation: it participates in the revision hash.
    a3_color: float | int
    a3_bw: float | int
    a4_color: float | int
    a4_bw: float | int
    slot: int
    effective_date: str


class PeerSharedSettingsV2Out(ApiModel):
    format_version: Literal[2]
    organization: PeerSharedOrganizationOut
    settings: PeerSettingsOut
    devices: list[PeerSharedDeviceOut]
    price_history: list[PeerDatedPriceOut]


class PeerSlotEpochReference(ApiModel):
    slot: int = Field(ge=0, le=2)
    epoch_id: str


class PeerSharedSettingsV3Out(PeerSharedSettingsV2Out):
    format_version: Literal[3]
    slot_epochs: list[PeerSlotEpochReference]


class PeerSettingsRevisionOut(ApiModel):
    parents: list[str]
    payload: PeerSharedSettingsV3Out | PeerSharedSettingsV2Out | PeerSharedSettingsOut
    actor: str
    created_at: str
    reason: str


class PeerSettingsHistoryResponse(ApiModel):
    contract: Literal["komi-peer-settings-history/v1"]
    head: str
    revisions: dict[str, PeerSettingsRevisionOut]


class PeerSettingsPageResponse(ApiModel):
    contract: Literal["komi-peer-settings-page/v1"]
    head: str
    offset: int
    next_offset: int | None
    revisions: dict[str, PeerSettingsRevisionOut]


class PeriodListResponse(ApiModel):
    billing_day: int
    items: list[PeriodOut]


class UsageOut(ApiModel):
    remarks: list[str] = Field(default_factory=list)
    device_slot: int
    period_start: str
    period_end: str
    total: float
    a3_color: float
    a3_bw: float
    a4_color: float
    a4_bw: float
    scan: float
    gross_cost: float
    net_cost: float
    day_count: int
    incomplete_days: int
    held_days: int
    device_identity: str
    device_name_snapshot: str
    device_serial_snapshot: str
    color: float
    bw: float
    confirmed_total: float
    confirmed_gross_cost: float
    confirmed_net_cost: float
    provisional_total: float
    provisional_a3_color: float
    provisional_a3_bw: float
    provisional_a4_color: float
    provisional_a4_bw: float
    provisional_print_color: float
    provisional_print_bw: float
    provisional_copy_color: float
    provisional_copy_bw: float
    provisional_scan: float
    provisional_gross_cost: float
    provisional_net_cost: float
    provisional_days: int
    provisional_cost_available: bool
    print_a3_color: float
    print_a4_color: float
    print_a3_bw: float
    print_a4_bw: float
    print_other: float
    copy_a3_color: float
    copy_a4_color: float
    copy_a3_bw: float
    copy_a4_bw: float
    copy_other: float
    provisional_print_a3_color: float
    provisional_print_a4_color: float
    provisional_print_a3_bw: float
    provisional_print_a4_bw: float
    provisional_print_other: float
    provisional_copy_a3_color: float
    provisional_copy_a4_color: float
    provisional_copy_a3_bw: float
    provisional_copy_a4_bw: float
    provisional_copy_other: float
    print_available: bool
    copy_available: bool


class DeviceUsageOut(DeviceOut):
    device_identity: str
    is_current_identity: bool
    usage: UsageOut


class OverviewTotals(ApiModel):
    usage: float
    color: float
    bw: float
    scan: float
    print_color: float
    print_bw: float
    copy_color: float
    copy_bw: float
    print_available: bool
    copy_available: bool
    gross_cost: float
    net_cost: float
    incomplete_days: int
    held_days: int
    confirmed_usage: float
    confirmed_net_cost: float
    provisional_usage: float
    provisional_net_cost: float
    provisional_days: int
    provisional_cost_available: bool


class TopUserOut(ApiModel):
    name: str
    type: str
    usage: float
    needs_review: bool
    device_identities: list[str]


class DataQualityOut(ApiModel):
    status: str
    incomplete_days: int
    held_days: int
    subject_warnings: int
    mixed_identity_slots: list[int]
    historical_identity_slots: list[int]
    provisional_days: int


class OverviewResponse(ApiModel):
    period: PeriodOut | None
    billing_day: int
    waste_pct: float
    last_sync_at: str | None
    totals: OverviewTotals
    devices: list[DeviceUsageOut]
    top_users: list[TopUserOut]
    data_quality: DataQualityOut
    empty: bool


class HistoryItemOut(ApiModel):
    remarks: list[str] = Field(default_factory=list)
    period_start: str
    period_end: str
    usage: float
    color: float
    bw: float
    scan: float
    net_cost: float
    incomplete_days: int
    held_days: int
    device_identities: list[str]
    mixed_identity_slots: list[int]
    provisional_usage: float
    provisional_net_cost: float
    provisional_days: int
    provisional_cost_available: bool


class HistoryResponse(ApiModel):
    granularity: HistoryGranularity
    total: int
    limit: int
    offset: int
    next_offset: int | None
    items: list[HistoryItemOut]


class UserOut(ApiModel):
    device_slot: int
    device_identity: str
    device_name_snapshot: str
    device_serial_snapshot: str
    subject_type: str
    subject_id: str
    subject_name: str
    usage: float
    latest_total: float
    needs_review: bool
    warnings: list[str]


class UserReportResponse(ApiModel):
    period_start: str | None
    period_end: str | None
    total: int
    limit: int
    offset: int
    next_offset: int | None
    snapshot_token: str
    items: list[UserOut]


class SyncDeviceOut(ApiModel):
    slot: int
    name: str
    host: str
    status: str
    last_checked_at: str | None
    last_success_at: str | None
    next_poll_at: str | None
    sample_count_today: int
    heartbeat_count_today: int
    last_cache_status: str
    status_detail: str


class TimelineOut(ApiModel):
    time_range: str
    mode: str
    snmp: str
    web: str
    ram: str
    database: str
    note: str


class SyncStatusResponse(ApiModel):
    server_time: str
    snmp_interval_minutes: int
    devices: list[SyncDeviceOut]
    timeline: list[TimelineOut]


class PriceOut(ApiModel):
    a3_color: float
    a3_bw: float
    a4_color: float
    a4_bw: float


class DevicePriceOut(ApiModel):
    slot: int
    name: str
    prices: PriceOut


class SettingsResponse(ApiModel):
    mode: Literal["read_only"] = "read_only"
    billing_day: int
    waste_pct: float
    work_start: str
    work_end: str
    snmp_interval_minutes: int
    web_interval_minutes: int
    peak_web_interval_minutes: int
    device_prices: list[DevicePriceOut]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    init_db()
    responder = None
    if os.environ.get("KOMI_DISCOVERY_DISABLED") != "1" and os.environ.get("KOMI_WEB_PORT"):
        from database import _open
        from services.lan_discovery import DiscoveryResponder
        from services.secondary_setup import _active_ipv4_subnets
        with _open(commit=False) as conn:
            ready = bool(get_cfg("company_name", "") and conn.execute(
                "SELECT 1 FROM devices WHERE enabled=1 LIMIT 1").fetchone())
        responder = DiscoveryResponder(lambda: [network for _, network in _active_ipv4_subnets()],
            https_port=lambda: os.environ["KOMI_WEB_PORT"], ready=lambda: ready)
        responder.start()
    try:
        yield
    finally:
        if responder is not None:
            responder.stop()


app = FastAPI(
    title="KOMI Report V5 LAN API",
    version=PACKAGE_VERSION,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    """Return a correlation ID for support without changing route payloads."""

    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    try:
        response = await call_next(request)
    except Exception:
        log.exception(
            "api request failed",
            extra={"event": "api_request_failed", "request_id": request_id, "operation": request.url.path},
        )
        raise
    response.headers["X-Request-ID"] = request_id
    return response


def _devices() -> list:
    return DeviceConfigRepository().list(enabled_only=True)


def _report_service() -> ReportReadService:
    """Keep route presentation separate from report storage/query details."""

    return ReportReadService(
        usage_loader=load_usage_history,
        subject_loader=load_subject_history,
        slots_loader=report_slots,
    )


def _page(items: list[dict], *, limit: int, offset: int) -> dict:
    total = len(items)
    next_offset = offset + limit if offset + limit < total else None
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": next_offset,
        "items": items[offset : offset + limit],
    }


def _redact_status_detail(value: str, *, secrets: tuple[str, ...] = ()) -> str:
    text = str(value or "")
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    patterns = (
        r"(?i)\b(basic|bearer)\s+[A-Za-z0-9._~+/=-]+",
        r"(?i)(password|passwd|pwd|community|authorization)\s*[:=]\s*(?:(?:basic|bearer)\s+)?[^\s,;]+",
        r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@",
    )
    for pattern in patterns:
        text = re.sub(pattern, lambda match: match.group(0).split("=", 1)[0] + "=[redacted]" if "=" in match.group(0) else "[redacted]", text)
    return text[:240]


def _device_payload(device) -> dict:
    return {
        "slot": device.slot,
        "name": device.name,
        "host": device.host,
        "model": device.model,
        "serial": device.serial,
        "status": device.connection_status,
        "last_checked_at": device.last_checked_at,
        "last_success_at": device.last_success_at,
        "last_total": device.last_total,
        "status_detail": _redact_status_detail(device.last_error, secrets=(device.password, device.username)),
    }


def _usage_payload(record) -> dict:
    result = asdict(record)
    for internal_field in ("print_color", "print_bw", "copy_color", "copy_bw"):
        result.pop(internal_field, None)
    result["period_start"] = record.period_start.isoformat()
    result["period_end"] = record.period_end.isoformat()
    result["confirmed_total"] = record.total
    result["confirmed_gross_cost"] = record.gross_cost
    result["confirmed_net_cost"] = record.net_cost
    result["total"] = record.total + record.provisional_total
    result["color"] = (
        record.a3_color
        + record.a4_color
        + record.provisional_a3_color
        + record.provisional_a4_color
    )
    result["bw"] = (
        record.a3_bw
        + record.a4_bw
        + record.provisional_a3_bw
        + record.provisional_a4_bw
    )
    result["scan"] = record.scan + record.provisional_scan
    result["gross_cost"] = record.gross_cost + record.provisional_gross_cost
    result["net_cost"] = record.net_cost + record.provisional_net_cost
    return result


def _device_usage_payload(record, current_device) -> dict:
    is_current = (
        current_device is not None
        and record.device_identity == current_device_identity(record.device_slot)
    )
    if is_current:
        payload = _device_payload(current_device)
    else:
        historical_host = (
            record.device_identity.removeprefix("host:")
            if record.device_identity.startswith("host:")
            else ""
        )
        payload = {
            "slot": record.device_slot,
            "name": record.device_name_snapshot or f"Historical device {record.device_slot + 1}",
            "host": historical_host,
            "model": "",
            "serial": record.device_serial_snapshot,
            "status": "historical",
            "last_checked_at": None,
            "last_success_at": None,
            "last_total": None,
            "status_detail": "Frozen historical identity; not the device currently configured in this slot.",
        }
    return {
        **payload,
        "device_identity": record.device_identity,
        "is_current_identity": is_current,
        "usage": _usage_payload(record),
    }


def _integer_cfg(key: str, default: int) -> int:
    try:
        return max(1, int(get_cfg(key, str(default)) or default))
    except (TypeError, ValueError):
        return default


def _clock_cfg(key: str, fallback: time) -> time:
    try:
        hour, minute = (int(part) for part in get_cfg(key, fallback.strftime("%H:%M")).split(":", 1))
        return time(hour, minute)
    except (TypeError, ValueError):
        return fallback


def _policy() -> PollingPolicy:
    return PollingPolicy(
        web_interval=timedelta(minutes=_integer_cfg("web_interval_minutes", 15)),
        peak_web_interval=timedelta(minutes=_integer_cfg("peak_web_interval_minutes", 5)),
        work_start=_clock_cfg("work_start", time(8, 0)),
        work_end=_clock_cfg("work_end", time(17, 0)),
        schedule_windows=load_schedule_windows(get_cfg("sync_schedule_windows", "")),
    )


@app.get("/api/v1/health", response_model=HealthResponse)
@app.get("/api/health", response_model=HealthResponse)
def health() -> dict:
    devices = _devices()
    return {
        "status": "ok",
        "server_time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "device_count": len(devices),
        "online_count": sum(device.connection_status.casefold() == "online" for device in devices),
    }


@app.get("/api/v1/devices", response_model=DeviceListResponse)
@app.get("/api/devices", response_model=DeviceListResponse)
def devices() -> dict:
    return {"items": [_device_payload(device) for device in _devices()]}


@app.get("/api/v1/peer/discovery", response_model=PeerDiscoveryResponse)
def peer_discovery() -> dict:
    """Minimal LAN beacon used by a Secondary Desktop."""

    return primary_discovery_payload()


@app.get('/api/v1/peer/contact', response_model=PeerContactResponse)
def peer_public_contact() -> dict:
    """Public installation proof for already-enrolled LAN address recovery."""
    from database import get_db_path
    from services.peer_contact_discovery import public_contact
    try:
        packet = public_contact(get_db_path())
    except (ValueError, TypeError, KeyError):
        packet = None
    if packet is None:
        raise HTTPException(status_code=404, detail='Peer contact unavailable')
    return packet


def _peer_requester_ip(request: Request) -> str:
    """Return the address injected by the local HTTPS edge, not a client hint."""

    remote = request.headers.get("x-komi-remote-address", "").strip()
    if remote:
        return remote.removeprefix("::ffff:")
    return str(request.client.host if request.client is not None else "")


@app.post(
    "/api/v1/peer/claim",
    response_model=PeerClaimResponse,
    status_code=202,
)
def peer_claim(request: Request, body: PeerClaimRequest) -> dict:
    """Claim an approval window; this endpoint never returns setup data."""

    try:
        remaining = claim_pairing_window(body.token, _peer_requester_ip(request))
    except PeerSyncAuthorizationError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    return {"accepted": True, "expires_in_seconds": remaining}


@app.get("/api/v1/peer/setup-snapshot", response_model=PeerSetupSnapshotResponse)
def peer_setup_snapshot(request: Request) -> dict:
    """Consume one approved capability before returning the allow-list."""

    _authorize_peer_snapshot(request)
    return primary_setup_snapshot()


class PeerEnrollmentRequest(ApiModel):
    operation: Literal['begin', 'settings', 'origins', 'epoch', 'finish']
    data: dict


class PeerEnrollmentInvitation(ApiModel):
    format: Literal['komi.lan.enrollment.v1']
    group_id: str
    company: str
    primary_id: str
    capability: str


class PeerEnrollmentStart(ApiModel):
    invitation: PeerEnrollmentInvitation
    source: PeerContactResponse
    head: str


class PeerEnrollmentOrigins(ApiModel):
    contacts: list[PeerContactResponse]
    after: str
    more: bool


class PeerEnrollmentEpoch(ApiModel):
    # Signed/hash-addressed documents retain their JSON number representation.
    # SlotEpochExchange validates their exact schema and proof before export.
    epoch: dict[str, object]
    parent_evidence: list[dict[str, object]]


class PeerEnrollmentReceipt(ApiModel):
    member_id: str
    committed: Literal[True]


class PeerEnrollmentResponse(RootModel[PeerEnrollmentStart | PeerSettingsPageResponse |
        PeerEnrollmentOrigins | PeerEnrollmentEpoch | PeerEnrollmentReceipt]):
    pass


@app.post('/api/v3/peer/enrollment', response_model=PeerEnrollmentResponse)
def peer_enrollment(request: Request, body: PeerEnrollmentRequest) -> dict:
    from services.peer_enrollment import EnrollmentSource
    from services.initial_slot_baselines import InitialBaselineRequired
    from services.peer_transport_factory import local_membership
    try:
        return EnrollmentSource(local_membership()).call(
            request.headers.get(PEER_SYNC_TOKEN_HEADER, ''), _peer_requester_ip(request),
            body.operation, body.data)
    except (PermissionError, PeerSyncAuthorizationError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except InitialBaselineRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=409, detail='เข้ากลุ่มยังไม่สำเร็จ ข้อมูลต้นทางเปลี่ยนหรือไม่สมบูรณ์ กรุณาดึงการตั้งค่าใหม่') from exc


def _authorize_peer_snapshot(request: Request, *, history_transfer=False) -> None:

    token = request.headers.get(PEER_SYNC_TOKEN_HEADER, "")
    try:
        consume_pairing_token(
            token,
            _peer_requester_ip(request),
            get_cfg("installation_id", ""),
            history_transfer=history_transfer,
        )
    except PeerSyncAuthorizationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/api/v2/peer/settings-history", response_model=PeerSettingsHistoryResponse)
def peer_settings_history(request: Request) -> dict:
    """Versioned history through the existing single-use approved capability."""
    from services.peer_settings_history import SettingsHistory

    _authorize_peer_snapshot(request)
    history = SettingsHistory()
    try:
        history.observe_current()
        return history.export()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v2/peer/settings-history/page", response_model=PeerSettingsPageResponse)
def peer_settings_history_page(request: Request, head: str | None = None, offset: int = 0, limit: int = 64) -> dict:
    from services.peer_settings_history import SettingsHistory
    from services.peer_sync_authorization import history_transfer_head
    token = request.headers.get(PEER_SYNC_TOKEN_HEADER, "")
    requester, installation = _peer_requester_ip(request), get_cfg("installation_id", "")
    try:
        bound_head = history_transfer_head(token, requester, installation)
    except PeerSyncAuthorizationError as exc:
        if head is not None or offset != 0:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        _authorize_peer_snapshot(request, history_transfer=True)
        bound_head = ""
    if head is not None and head != bound_head:
        raise HTTPException(status_code=401, detail="History transfer does not authorize this revision")
    history = SettingsHistory()
    try:
        selected = bound_head or history.observe_current()
        history_transfer_head(token, requester, installation, bind_head=selected)
        return history.export_page(head=selected, offset=offset, limit=limit)
    except PeerSyncAuthorizationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/reports/periods", response_model=PeriodListResponse)
@app.get("/api/reports/periods", response_model=PeriodListResponse)
def report_periods() -> dict:
    records = _report_service().usage()
    periods = sorted({(item.period_start, item.period_end) for item in records}, reverse=True)
    return {
        "billing_day": int(get_cfg("billing_day", "31") or 31),
        "items": [{"start": start.isoformat(), "end": end.isoformat()} for start, end in periods],
    }


@app.get("/api/v1/reports/overview", response_model=OverviewResponse)
@app.get("/api/reports/overview", response_model=OverviewResponse)
def report_overview(
    period_start: date | None = None,
    period_end: date | None = None,
) -> dict:
    devices = _devices()
    by_slot = {device.slot: device for device in devices}
    reports = _report_service()
    records = reports.usage()
    available = sorted(
        {(record.period_start, record.period_end) for record in records},
        reverse=True,
    )
    if period_start is not None and period_end is not None:
        selected = (period_start, period_end)
    elif period_start is not None:
        selected = next(
            (period for period in available if period[0] == period_start),
            None,
        )
    else:
        selected = available[0] if available else None
    exact_records = [
        record
        for record in records
        if selected
        and record.period_start == selected[0]
        and record.period_end == selected[1]
    ]
    selected_records = exact_records
    if selected and not selected_records:
        selected_records = [
            record
            for record in reports.usage(granularity="daily")
            if record.period_start >= selected[0]
            and record.period_end <= selected[1]
        ]
    selected_subjects = (
        reports.subjects(period_start=selected[0], period_end=selected[1])
        if selected
        else ()
    )

    totals = {
        "usage": sum(
            item.total + item.provisional_total for item in selected_records
        ),
        "color": sum(
            item.a3_color
            + item.a4_color
            + item.provisional_a3_color
            + item.provisional_a4_color
            for item in selected_records
        ),
        "bw": sum(
            item.a3_bw
            + item.a4_bw
            + item.provisional_a3_bw
            + item.provisional_a4_bw
            for item in selected_records
        ),
        "scan": sum(
            item.scan + item.provisional_scan for item in selected_records
        ),
        "print_color": sum(
            item.print_color + item.provisional_print_color
            for item in selected_records
        ),
        "print_bw": sum(
            item.print_bw + item.provisional_print_bw
            for item in selected_records
        ),
        "copy_color": sum(
            item.copy_color + item.provisional_copy_color
            for item in selected_records
        ),
        "copy_bw": sum(
            item.copy_bw + item.provisional_copy_bw
            for item in selected_records
        ),
        "print_available": any(item.print_available for item in selected_records),
        "copy_available": any(item.copy_available for item in selected_records),
        "gross_cost": round(
            sum(
                item.gross_cost + item.provisional_gross_cost
                for item in selected_records
            ),
            2,
        ),
        "net_cost": round(
            sum(
                item.net_cost + item.provisional_net_cost
                for item in selected_records
            ),
            2,
        ),
        "incomplete_days": sum(item.incomplete_days for item in selected_records),
        "held_days": sum(item.held_days for item in selected_records),
        "confirmed_usage": sum(item.total for item in selected_records),
        "confirmed_net_cost": round(
            sum(item.net_cost for item in selected_records), 2
        ),
        "provisional_usage": sum(
            item.provisional_total for item in selected_records
        ),
        "provisional_net_cost": round(
            sum(item.provisional_net_cost for item in selected_records), 2
        ),
        "provisional_days": sum(
            item.provisional_days for item in selected_records
        ),
        "provisional_cost_available": all(
            item.provisional_cost_available
            for item in selected_records
            if item.provisional_days
        ),
    }

    subject_totals: dict[tuple[str, str, str], dict] = {}
    for item in selected_subjects:
        key = (item.device_identity, item.subject_type, item.subject_id)
        entry = subject_totals.setdefault(
            key,
            {
                "name": item.subject_name,
                "type": item.subject_type,
                "usage": 0.0,
                "needs_review": False,
                "device_identities": [item.device_identity],
            },
        )
        entry["usage"] += item.period_usage
        entry["needs_review"] = entry["needs_review"] or item.needs_review

    last_sync = max((device.last_success_at for device in devices if device.last_success_at), default=None)
    identities_by_slot: dict[int, set[str]] = defaultdict(set)
    for item in selected_records:
        identities_by_slot[item.device_slot].add(item.device_identity)
    mixed_identity_slots = sorted(
        slot for slot, identities in identities_by_slot.items() if len(identities) > 1
    )
    historical_identity_slots = sorted(
        slot
        for slot, identities in identities_by_slot.items()
        if any(identity != current_device_identity(slot) for identity in identities)
    )
    has_quality_warning = bool(
        totals["incomplete_days"]
        or totals["held_days"]
        or mixed_identity_slots
        or historical_identity_slots
    )
    return {
        "period": {
            "start": selected[0].isoformat(),
            "end": selected[1].isoformat(),
        } if selected else None,
        "billing_day": int(get_cfg("billing_day", "31") or 31),
        "waste_pct": float(get_cfg("waste_paper_pct", "2") or 2),
        "last_sync_at": last_sync,
        "totals": totals,
        "devices": [
            _device_usage_payload(item, by_slot.get(item.device_slot))
            for item in selected_records
        ],
        "top_users": sorted(subject_totals.values(), key=lambda item: item["usage"], reverse=True)[:8],
        "data_quality": {
            "status": (
                "needs_review"
                if has_quality_warning
                else ("provisional" if totals["provisional_days"] else "complete")
            ),
            "incomplete_days": totals["incomplete_days"],
            "held_days": totals["held_days"],
            "subject_warnings": sum(bool(item.needs_review) for item in selected_subjects),
            "mixed_identity_slots": mixed_identity_slots,
            "historical_identity_slots": historical_identity_slots,
            "provisional_days": totals["provisional_days"],
        },
        "empty": not selected_records,
    }


@app.get("/api/v1/reports/history", response_model=HistoryResponse)
@app.get("/api/reports/history", response_model=HistoryResponse)
def report_history(
    granularity: HistoryGranularity = "monthly",
    period_start: date | None = None,
    period_end: date | None = None,
    device_identity: str | None = Query(default=None, min_length=1, max_length=256),
    limit: int = Query(default=100, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> dict:
    records = _report_service().usage(granularity=granularity)
    # A report period is an inclusive date range.  Keep records that overlap it
    # so the Web timeline cannot silently plot a different period from its KPI.
    if period_start is not None:
        records = tuple(record for record in records if record.period_end >= period_start)
    if period_end is not None:
        records = tuple(record for record in records if record.period_start <= period_end)
    if device_identity is not None:
        records = tuple(
            record
            for record in records
            if record.device_identity == device_identity
        )
    grouped: dict[tuple[date, date], dict] = defaultdict(
        lambda: {
            "usage": 0.0,
            "color": 0.0,
            "bw": 0.0,
            "scan": 0.0,
            "net_cost": 0.0,
            "incomplete_days": 0,
            "held_days": 0,
            "provisional_usage": 0.0,
            "provisional_net_cost": 0.0,
            "provisional_days": 0,
            "provisional_cost_available": True,
            "device_identities": set(),
            "identities_by_slot": defaultdict(set),
            "remarks": set(),
        }
    )
    for record in records:
        item = grouped[(record.period_start, record.period_end)]
        item["usage"] += record.total + record.provisional_total
        item["color"] += (
            record.a3_color
            + record.a4_color
            + record.provisional_a3_color
            + record.provisional_a4_color
        )
        item["bw"] += (
            record.a3_bw
            + record.a4_bw
            + record.provisional_a3_bw
            + record.provisional_a4_bw
        )
        item["scan"] += record.scan + record.provisional_scan
        item["net_cost"] += record.net_cost + record.provisional_net_cost
        item["incomplete_days"] += record.incomplete_days
        item["held_days"] += record.held_days
        item["provisional_usage"] += record.provisional_total
        item["provisional_net_cost"] += record.provisional_net_cost
        item["provisional_days"] += record.provisional_days
        item["provisional_cost_available"] = (
            item["provisional_cost_available"]
            and record.provisional_cost_available
        )
        item["device_identities"].add(record.device_identity)
        item["remarks"].update(record.remarks)
        item["identities_by_slot"][record.device_slot].add(record.device_identity)
    items = [
            {
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "usage": round(values["usage"], 2),
                "color": round(values["color"], 2),
                "bw": round(values["bw"], 2),
                "scan": round(values["scan"], 2),
                "net_cost": round(values["net_cost"], 2),
                "incomplete_days": int(values["incomplete_days"]),
                "held_days": int(values["held_days"]),
                "provisional_usage": round(values["provisional_usage"], 2),
                "provisional_net_cost": round(
                    values["provisional_net_cost"], 2
                ),
                "provisional_days": int(values["provisional_days"]),
                "provisional_cost_available": bool(
                    values["provisional_cost_available"]
                ),
                "device_identities": sorted(values["device_identities"]),
                "remarks": sorted(values["remarks"]),
                "mixed_identity_slots": sorted(
                    slot
                    for slot, identities in values["identities_by_slot"].items()
                    if len(identities) > 1
                ),
            }
            for (start, end), values in sorted(grouped.items())
        ]
    return {"granularity": granularity, **_page(items, limit=limit, offset=offset)}


@app.get("/api/v1/reports/users", response_model=UserReportResponse)
@app.get("/api/reports/users", response_model=UserReportResponse)
def report_users(
    period_start: date | None = None,
    period_end: date | None = None,
    limit: int = Query(default=100, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
    snapshot_token: str | None = None,
) -> dict:
    if snapshot_token:
        requested = (period_start, period_end) if period_start and period_end else None
        token, selected, payload = _user_page_snapshot(snapshot_token, requested, None)
        return {
            "period_start": selected[0].isoformat() if selected else None,
            "period_end": selected[1].isoformat() if selected else None,
            "snapshot_token": token,
            **_page(payload, limit=limit, offset=offset),
        }
    reports = _report_service()
    if period_start is not None and period_end is not None:
        selected = (period_start, period_end)
    else:
        records = reports.subjects()
        available = sorted(
            {(record.period_start, record.period_end) for record in records},
            reverse=True,
        )
        if period_start is not None:
            selected = next(
                (period for period in available if period[0] == period_start),
                None,
            )
        else:
            selected = available[0] if available else None
    items = (
        reports.subjects(period_start=selected[0], period_end=selected[1])
        if selected
        else ()
    )
    payload = [
            {
                "device_slot": item.device_slot,
                "device_identity": item.device_identity,
                "device_name_snapshot": item.device_name_snapshot,
                "device_serial_snapshot": item.device_serial_snapshot,
                "subject_type": item.subject_type,
                "subject_id": item.subject_id,
                "subject_name": item.subject_name,
                "usage": item.period_usage,
                "latest_total": item.latest_total,
                "needs_review": item.needs_review,
                "warnings": list(item.warnings),
            }
            for item in items
        ]
    token, selected, payload = _user_page_snapshot(None, selected, payload)
    return {
        "period_start": selected[0].isoformat() if selected else None,
        "period_end": selected[1].isoformat() if selected else None,
        "snapshot_token": token,
        **_page(payload, limit=limit, offset=offset),
    }


@app.get("/api/v1/sync/status", response_model=SyncStatusResponse)
@app.get("/api/sync/status", response_model=SyncStatusResponse)
def sync_status() -> dict:
    now = datetime.now().astimezone()
    interval_minutes = _integer_cfg("snmp_interval_minutes", 5)
    cache = DailyCacheStore()
    device_items = []
    for device in _devices():
        state = cache.load(device.slot, now.date()) or {}
        try:
            checked = datetime.fromisoformat(device.last_checked_at) if device.last_checked_at else None
            next_poll = checked + timedelta(minutes=interval_minutes) if checked else None
        except ValueError:
            next_poll = None
        device_items.append(
            {
                "slot": device.slot,
                "name": device.name,
                "host": device.host,
                "status": device.connection_status,
                "last_checked_at": device.last_checked_at,
                "last_success_at": device.last_success_at,
                "next_poll_at": next_poll.isoformat(timespec="seconds") if next_poll else None,
                "sample_count_today": int(state.get("sample_count", 0)),
                "heartbeat_count_today": int(state.get("heartbeat_count", 0)),
                "last_cache_status": str(state.get("last_status", "ยังไม่มี Cache วันนี้")),
                "status_detail": _redact_status_detail(device.last_error, secrets=(device.password, device.username)),
            }
        )
    timeline = [asdict(item) for item in build_daily_timeline(_policy(), snmp_minutes=interval_minutes)]
    return {
        "server_time": now.isoformat(timespec="seconds"),
        "snmp_interval_minutes": interval_minutes,
        "devices": device_items,
        "timeline": timeline,
    }


@app.get("/api/v1/settings", response_model=SettingsResponse)
@app.get("/api/settings", response_model=SettingsResponse)
def settings() -> dict:
    devices = _devices()
    pricing = PricingRepository()
    policy = _policy()
    today = date.today()
    return {
        "mode": "read_only",
        "billing_day": int(get_cfg("billing_day", "31") or 31),
        "waste_pct": float(get_cfg("waste_paper_pct", "2") or 2),
        "work_start": policy.work_start.strftime("%H:%M"),
        "work_end": policy.work_end.strftime("%H:%M"),
        "snmp_interval_minutes": _integer_cfg("snmp_interval_minutes", 5),
        "web_interval_minutes": int(policy.web_interval.total_seconds() // 60),
        "peak_web_interval_minutes": int(policy.peak_web_interval.total_seconds() // 60),
        "device_prices": [
            {"slot": device.slot, "name": device.name, "prices": asdict(pricing.get_prices(device.slot, today))}
            for device in devices
        ],
    }
