"""Safe first-run connectivity checks for required KOMI Host endpoints.

The checks use HEAD requests only. They never register an installation or send
company, printer, credential, counter or device data.
"""

from __future__ import annotations

import platform
import socket
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from komi_version import APP_VERSION
from services.registration_errors import classify_network_error, error_message

DEFAULT_SETUP_BASE_URL = "https://www.dmskm.com"
SETUP_API_PATHS = (
    ("Registration API", "/api/v1/installations/register"),
    ("Status API", "/api/v1/installations/status"),
    ("Meter API", "/api/v1/installations/meter-observations"),
)
REACHABLE_HTTP_STATUSES = frozenset({200, 201, 202, 204, 400, 401, 403, 405, 409, 415, 422})


@dataclass(frozen=True)
class SetupConnectivityCheck:
    name: str
    target: str
    ok: bool
    detail: str
    support_code: str = ""
    duration_ms: int = 0
    required: bool = True


@dataclass(frozen=True)
class SetupConnectivityReport:
    started_at: str
    base_url: str
    checks: tuple[SetupConnectivityCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks if check.required)

    def support_text(self) -> str:
        lines = [
            "KOMI Setup Connectivity Diagnostic",
            f"App version: {APP_VERSION}",
            f"Time: {self.started_at}",
            f"OS: {platform.system()} {platform.release()}",
            f"Target: {self.base_url}",
            f"Result: {'PASS' if self.ok else 'FAILED'}",
            "",
        ]
        for check in self.checks:
            state = "PASS" if check.ok else "FAIL"
            suffix = f" | Support code: {check.support_code}" if check.support_code else ""
            lines.append(
                f"[{state}] {check.name} | {check.target} | "
                f"{check.detail} | {check.duration_ms} ms{suffix}"
            )
        lines.extend(
            (
                "",
                "Privacy: no company name, printer address, credential, counter, document or log was sent.",
            )
        )
        return "\n".join(lines)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ARG002
        return None


def _request_status(request: Request, timeout: float) -> int:
    opener = build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:  # noqa: S310
            return int(response.status)
    except HTTPError as error:
        return int(error.code)


def _http_result(status: int) -> tuple[bool, str, str]:
    if status in REACHABLE_HTTP_STATUSES:
        return True, f"HTTP {status} | endpoint reachable", ""
    if 300 <= status < 400:
        return False, f"HTTP {status} | unexpected redirect", "host_redirect"
    if status == 404:
        return False, "HTTP 404 | endpoint not found", "host_endpoint_missing"
    if status == 407:
        return False, "HTTP 407 | proxy authentication required", "proxy_auth_required"
    if status == 429:
        return False, "HTTP 429 | service rate limited", "rate_limited"
    if status >= 500:
        return False, f"HTTP {status} | Host unavailable", "host_unavailable"
    return False, f"HTTP {status} | unexpected response", "http_error"


def check_setup_connectivity(
    *,
    base_url: str = DEFAULT_SETUP_BASE_URL,
    timeout: float = 6.0,
    resolver: Callable[..., object] = socket.getaddrinfo,
    requester: Callable[[Request, float], int] = _request_status,
) -> SetupConnectivityReport:
    """Check DNS and every required Host API without sending customer data."""

    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Setup connectivity target must be an absolute HTTPS URL")
    hostname = parsed.hostname
    port = parsed.port or 443
    checks: list[SetupConnectivityCheck] = []

    dns_started = perf_counter()
    try:
        answers = resolver(hostname, port, type=socket.SOCK_STREAM)
        addresses = {
            str(item[4][0])
            for item in answers
            if isinstance(item, tuple) and len(item) > 4 and item[4]
        }
        dns_ok = bool(addresses)
        dns_detail = f"resolved {len(addresses)} address(es)" if dns_ok else "no address returned"
        dns_code = "" if dns_ok else "dns_error"
    except (OSError, TypeError, ValueError) as error:
        dns_ok = False
        dns_code = classify_network_error(error)
        dns_detail = error_message(dns_code)[1]
    checks.append(
        SetupConnectivityCheck(
            name="DNS",
            target=hostname,
            ok=dns_ok,
            detail=dns_detail,
            support_code=dns_code,
            duration_ms=round((perf_counter() - dns_started) * 1000),
            # A configured HTTPS proxy may resolve the host remotely. The API
            # checks below are authoritative for whether the app can connect.
            required=False,
        )
    )

    def probe(name: str, path: str) -> SetupConnectivityCheck:
        target = f"{base_url.rstrip('/')}{path}"
        request = Request(
            target,
            headers={
                "Accept": "application/json",
                "User-Agent": f"KOMI-Report-V5-Setup/{APP_VERSION}",
            },
            method="HEAD",
        )
        request_started = perf_counter()
        try:
            status = int(requester(request, timeout))
            ok, detail, code = _http_result(status)
        except (OSError, TimeoutError, URLError) as error:
            code = classify_network_error(error)
            ok = False
            detail = error_message(code)[1]
        return SetupConnectivityCheck(
            name=name,
            target=target,
            ok=ok,
            detail=detail,
            support_code=code,
            duration_ms=round((perf_counter() - request_started) * 1000),
        )

    with ThreadPoolExecutor(max_workers=len(SETUP_API_PATHS)) as executor:
        futures = [executor.submit(probe, name, path) for name, path in SETUP_API_PATHS]
        checks.extend(future.result() for future in futures)

    return SetupConnectivityReport(started_at, base_url, tuple(checks))
