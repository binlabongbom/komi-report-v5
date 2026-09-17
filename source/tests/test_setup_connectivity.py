from __future__ import annotations

import socket
from urllib.error import URLError

from services.setup_connectivity import SETUP_API_PATHS, check_setup_connectivity


def _resolved(*_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.10", 443))]


def test_setup_connectivity_checks_every_required_api_without_a_body():
    requests = []

    def requester(request, timeout):
        requests.append((request, timeout))
        return 405

    report = check_setup_connectivity(
        resolver=_resolved,
        requester=requester,
        timeout=2.5,
    )

    assert report.ok
    assert len(requests) == len(SETUP_API_PATHS)
    assert {request.full_url for request, _timeout in requests} == {
        f"https://www.dmskm.com{path}" for _name, path in SETUP_API_PATHS
    }
    assert all(request.get_method() == "HEAD" for request, _timeout in requests)
    assert all(request.data is None for request, _timeout in requests)
    assert all(timeout == 2.5 for _request, timeout in requests)
    assert "Result: PASS" in report.support_text()


def test_setup_connectivity_reports_the_failed_endpoint_for_support():
    def requester(request, _timeout):
        if request.full_url.endswith("/status"):
            return 503
        return 405

    report = check_setup_connectivity(resolver=_resolved, requester=requester)

    assert not report.ok
    failed = [check for check in report.checks if check.required and not check.ok]
    assert len(failed) == 1
    assert failed[0].name == "Status API"
    assert failed[0].support_code == "host_unavailable"
    assert "Support code: host_unavailable" in report.support_text()


def test_proxy_resolved_api_can_pass_when_local_dns_is_unavailable():
    def failed_dns(*_args, **_kwargs):
        raise socket.gaierror(socket.EAI_NONAME, "not found")

    report = check_setup_connectivity(
        resolver=failed_dns,
        requester=lambda _request, _timeout: 405,
    )

    assert report.ok
    assert not report.checks[0].ok
    assert report.checks[0].required is False


def test_network_error_is_reduced_to_a_safe_support_code():
    def requester(_request, _timeout):
        raise URLError(TimeoutError())

    report = check_setup_connectivity(resolver=_resolved, requester=requester)

    assert not report.ok
    assert {
        check.support_code for check in report.checks if check.required
    } == {"connection_timeout"}
    assert "TimeoutError" not in report.support_text()
