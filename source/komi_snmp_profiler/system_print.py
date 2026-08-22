from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

PAPER_SIZES: dict[str, tuple[float, float]] = {
    "A4": (595.28, 841.89),
    "A3": (841.89, 1190.55),
}


class PrintingError(RuntimeError):
    """Raised when an installed printer cannot accept a calibration job."""


@dataclass(frozen=True)
class PrintTestRequest:
    printer: str
    paper_size: str
    color: bool
    pages: int

    def __post_init__(self) -> None:
        if not self.printer.strip():
            raise ValueError("กรุณาเลือก printer queue")
        if self.paper_size not in PAPER_SIZES:
            raise ValueError("รองรับเฉพาะ A4 และ A3")
        if not 1 <= self.pages <= 100:
            raise ValueError("จำนวนหน้าทดสอบต้องอยู่ระหว่าง 1–100")

    @property
    def job_type(self) -> str:
        return f"{self.paper_size} {'Color' if self.color else 'Black'}"

    @property
    def document_name(self) -> str:
        return f"KOMI Calibration {self.job_type} {self.pages}p"


class PrintBackend(Protocol):
    def list_printers(self) -> list[str]: ...

    def submit(self, request: PrintTestRequest) -> str: ...

    def wait_for_completion(self, printer: str, job_id: str, timeout: float = 180.0) -> None: ...


def _pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_test_pdf(request: PrintTestRequest) -> bytes:
    """Build a small dependency-free PDF with exact page size and visible color/black marks."""
    width, height = PAPER_SIZES[request.paper_size]
    objects: list[bytes] = [b""]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"")  # Filled after page object IDs are known.
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids: list[int] = []
    for page_number in range(1, request.pages + 1):
        page_id = len(objects)
        content_id = page_id + 1
        page_ids.append(page_id)
        page = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode()
        objects.append(page)

        fill = "0.90 0.05 0.15 rg" if request.color else "0.12 g"
        label = _pdf_text(f"KOMI SNMP CALIBRATION - {request.job_type} - PAGE {page_number}/{request.pages}")
        box_width = max(100.0, width - 144.0)
        box_height = max(100.0, height / 3.0)
        content = (
            f"q\n{fill}\n72 {height / 3:.2f} {box_width:.2f} {box_height:.2f} re f\nQ\n"
            f"BT\n/F1 16 Tf\n72 {height - 72:.2f} Td\n({label}) Tj\nET\n"
        ).encode("ascii")
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"endstream")

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {request.pages} >>".encode()

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, payload in enumerate(objects[1:], start=1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode())
        output.extend(payload)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects)}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode())
    return bytes(output)


def _run(command: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, check=True, timeout=timeout)
    except FileNotFoundError as err:
        raise PrintingError(f"ไม่พบคำสั่งระบบสำหรับพิมพ์: {command[0]}") from err
    except subprocess.TimeoutExpired as err:
        raise PrintingError("ระบบพิมพ์ไม่ตอบสนองภายในเวลาที่กำหนด") from err
    except subprocess.CalledProcessError as err:
        details = (err.stderr or err.stdout or str(err)).strip()
        raise PrintingError(f"ระบบพิมพ์ปฏิเสธคำสั่ง: {details}") from err


def cups_driver_options(capabilities: str, request: PrintTestRequest) -> list[str]:
    """Add vendor PPD options only when the installed driver advertises them."""
    options: list[str] = []
    page_token = "A4JIS" if request.paper_size == "A4" else "A3JIS"
    if re.search(rf"^PageSize/[^:]+:.*\b{page_token}\b", capabilities, re.MULTILINE):
        options.append(f"PageSize={page_token}")
    select_color = "Color" if request.color else "Grayscale"
    if re.search(rf"^SelectColor/[^:]+:.*\b{select_color}\b", capabilities, re.MULTILINE):
        options.append(f"SelectColor={select_color}")
    color_model = "CMYK" if request.color else "Gray"
    if re.search(rf"^ColorModel/[^:]+:.*\b{color_model}\b", capabilities, re.MULTILINE):
        options.append(f"ColorModel={color_model}")
    return options


def parse_cups_job_id(output: str, fallback: str) -> str:
    """Extract the CUPS destination-number token without depending on UI language."""
    match = re.search(r"([^\s]+-\d+)(?:\s|$)", output)
    return match.group(1) if match else fallback


class MacCupsPrintBackend:
    def list_printers(self) -> list[str]:
        # `-e` returns one destination per line and is stable across macOS UI languages.
        result = _run(["lpstat", "-e"])
        printers = {line.strip() for line in result.stdout.splitlines() if line.strip()}
        return sorted(printers, key=str.casefold)

    def submit(self, request: PrintTestRequest) -> str:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix="komi-calibration-", suffix=".pdf", delete=False) as handle:
                temporary_path = Path(handle.name)
                handle.write(build_test_pdf(request))
            media = "iso_a4_210x297mm" if request.paper_size == "A4" else "iso_a3_297x420mm"
            color_mode = "color" if request.color else "monochrome"
            capabilities = _run(["lpoptions", "-p", request.printer, "-l"]).stdout
            command = [
                "lp",
                "-d",
                request.printer,
                "-t",
                request.document_name,
                "-o",
                f"media={media}",
                "-o",
                f"print-color-mode={color_mode}",
                "-o",
                "sides=one-sided",
            ]
            for option in cups_driver_options(capabilities, request):
                command.extend(("-o", option))
            command.append(str(temporary_path))
            result = _run(command)
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)
        return parse_cups_job_id(result.stdout, request.document_name)

    def wait_for_completion(self, printer: str, job_id: str, timeout: float = 180.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = _run(["lpstat", "-W", "not-completed", "-o", printer])
            pending = result.stdout.strip()
            if not pending or (re.search(r"-\d+$", job_id) and job_id not in pending):
                return
            time.sleep(2)
        raise PrintingError(f"งาน {job_id} ยังไม่ออกจาก print queue ภายใน {int(timeout)} วินาที")


WINDOWS_PRINT_SCRIPT = r"""
param(
  [Parameter(Mandatory=$true)][string]$PrinterName,
  [Parameter(Mandatory=$true)][ValidateSet('A4','A3')][string]$Paper,
  [Parameter(Mandatory=$true)][string]$UseColor,
  [Parameter(Mandatory=$true)][int]$Pages,
  [Parameter(Mandatory=$true)][string]$DocumentName
)
Add-Type -AssemblyName System.Drawing
$doc = New-Object System.Drawing.Printing.PrintDocument
$doc.PrinterSettings.PrinterName = $PrinterName
if (-not $doc.PrinterSettings.IsValid) { throw "Printer queue not found: $PrinterName" }
$doc.DocumentName = $DocumentName
$doc.DefaultPageSettings.Color = [System.Convert]::ToBoolean($UseColor)
$rawKind = if ($Paper -eq 'A3') { 8 } else { 9 }
$paperSize = $doc.PrinterSettings.PaperSizes | Where-Object { $_.RawKind -eq $rawKind } | Select-Object -First 1
if ($null -eq $paperSize) { throw "$Paper is not available in printer driver $PrinterName" }
$doc.DefaultPageSettings.PaperSize = $paperSize
$script:page = 0
$doc.add_PrintPage({
  param($sender, $eventArgs)
  $script:page++
  $brush = if ([System.Convert]::ToBoolean($UseColor)) {
    New-Object System.Drawing.SolidBrush([System.Drawing.Color]::Crimson)
  } else {
    New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(32,32,32))
  }
  $eventArgs.Graphics.FillRectangle($brush, 80, 180, $eventArgs.MarginBounds.Width - 80, 320)
  $font = New-Object System.Drawing.Font('Arial', 16)
  $label = "KOMI SNMP CALIBRATION - $Paper - PAGE $script:page/$Pages"
  $eventArgs.Graphics.DrawString(
    $label,
    $font,
    [System.Drawing.Brushes]::Black,
    80,
    80
  )
  $eventArgs.HasMorePages = $script:page -lt $Pages
  $brush.Dispose()
  $font.Dispose()
})
$doc.Print()
$doc.Dispose()
Write-Output $DocumentName
"""


class WindowsPrintBackend:
    def list_printers(self) -> list[str]:
        result = _run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "Get-Printer | Select-Object -ExpandProperty Name",
            ]
        )
        return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()}, key=str.casefold)

    def submit(self, request: PrintTestRequest) -> str:
        job_id = f"{request.document_name} {uuid.uuid4().hex[:8]}"
        script_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="komi-print-", suffix=".ps1", mode="w", encoding="utf-8-sig", delete=False
            ) as handle:
                handle.write(WINDOWS_PRINT_SCRIPT)
                script_path = Path(handle.name)
            _run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script_path),
                    "-PrinterName",
                    request.printer,
                    "-Paper",
                    request.paper_size,
                    "-UseColor",
                    str(request.color),
                    "-Pages",
                    str(request.pages),
                    "-DocumentName",
                    job_id,
                ],
                timeout=60,
            )
        finally:
            if script_path:
                script_path.unlink(missing_ok=True)
        return job_id

    def wait_for_completion(self, printer: str, job_id: str, timeout: float = 180.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            command = (
                "$job = Get-PrintJob -PrinterName $args[0] -ErrorAction SilentlyContinue | "
                "Where-Object { $_.DocumentName -eq $args[1] }; if ($job) { 'PENDING' }"
            )
            result = _run(["powershell.exe", "-NoProfile", "-Command", command, printer, job_id])
            if "PENDING" not in result.stdout:
                return
            time.sleep(2)
        raise PrintingError(f"งาน {job_id} ยังไม่ออกจาก print queue ภายใน {int(timeout)} วินาที")


def system_print_backend(platform: str | None = None) -> PrintBackend:
    selected = platform or sys.platform
    if selected == "darwin":
        return MacCupsPrintBackend()
    if selected == "win32":
        return WindowsPrintBackend()
    raise PrintingError("Print & Calibrate รุ่นนี้รองรับ macOS และ Windows")
