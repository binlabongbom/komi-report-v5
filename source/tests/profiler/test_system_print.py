from __future__ import annotations

import pytest

from komi_snmp_profiler.system_print import (
    MacCupsPrintBackend,
    PrintingError,
    PrintTestRequest,
    WindowsPrintBackend,
    build_test_pdf,
    cups_driver_options,
    parse_cups_job_id,
    system_print_backend,
)


def test_request_derives_job_type() -> None:
    request = PrintTestRequest("KM-C360i", "A3", True, 3)
    assert request.job_type == "A3 Color"
    assert "3p" in request.document_name


@pytest.mark.parametrize("pages", [0, 101])
def test_request_rejects_unsafe_page_count(pages: int) -> None:
    with pytest.raises(ValueError):
        PrintTestRequest("KM-C360i", "A4", False, pages)


def test_pdf_contains_exact_a4_size_and_requested_pages() -> None:
    pdf = build_test_pdf(PrintTestRequest("KM-C360i", "A4", True, 3))
    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.endswith(b"%%EOF\n")
    assert pdf.count(b"/Type /Page /Parent") == 3
    assert b"/MediaBox [0 0 595.28 841.89]" in pdf
    assert b"0.90 0.05 0.15 rg" in pdf


def test_black_pdf_uses_grayscale_fill() -> None:
    pdf = build_test_pdf(PrintTestRequest("KM-C360i", "A3", False, 1))
    assert b"/MediaBox [0 0 841.89 1190.55]" in pdf
    assert b"0.12 g" in pdf


def test_backend_factory_is_explicit_by_platform() -> None:
    assert isinstance(system_print_backend("darwin"), MacCupsPrintBackend)
    assert isinstance(system_print_backend("win32"), WindowsPrintBackend)
    with pytest.raises(PrintingError):
        system_print_backend("linux")


def test_cups_options_use_konica_driver_capabilities_when_available() -> None:
    capabilities = """PageSize/Paper Size: A3JIS *A4JIS A5JIS
SelectColor/Select Color: *Color ColorFixed Grayscale
ColorModel/Select Color: *CMYK Gray
"""
    color = cups_driver_options(capabilities, PrintTestRequest("KM", "A3", True, 1))
    black = cups_driver_options(capabilities, PrintTestRequest("KM", "A4", False, 1))
    assert color == ["PageSize=A3JIS", "SelectColor=Color", "ColorModel=CMYK"]
    assert black == ["PageSize=A4JIS", "SelectColor=Grayscale", "ColorModel=Gray"]


def test_cups_job_id_parser_does_not_depend_on_english_message() -> None:
    assert parse_cups_job_id("request id is KM_C360i-42 (1 file(s))", "fallback") == "KM_C360i-42"
    assert parse_cups_job_id("ส่งคำขอ konicaminolta_Printer-108 แล้ว", "fallback") == "konicaminolta_Printer-108"
    assert parse_cups_job_id("", "fallback") == "fallback"
