"""Worker-owned Web evidence export; no widgets cross the thread boundary."""
from concurrent.futures import CancelledError
from pathlib import Path
import os
import tempfile
import html
from PyQt6.QtCore import QSizeF, QRectF
from PyQt6.QtGui import QTextDocument, QPdfWriter, QPainter, QFont
from services.web_evidence_report import export_evidence_xlsx, review_labels
from i18n import tr


def check(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise CancelledError()


def display_number(value):
    return f"{float(value):,.2f}".rstrip("0").rstrip(".")


def projection_pdf(path, projection, *, title, cancelled=None, progress=None):
    """Paginated evidence/remarks, escaped data; no rasterized tiny printout."""
    check(cancelled)
    rows = []
    for item in projection.intervals:
        check(cancelled)
        rows.append("<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in (
            item.start.at.strftime("%d/%m/%Y %H:%M"), item.end.at.strftime("%d/%m/%Y %H:%M"),
            display_number(item.amount), item.allocation_day.isoformat(), item.remark,
            review_labels(item.holds))) + "</tr>")
    if progress: progress(15, tr("จัดหน้ารายงาน PDF…", "Laying out PDF…"))
    # Bound each rich-text layout pass: one 4,000-row document holds Qt's
    # text/font work too long even on a worker, delaying the GUI. Separate
    # documents also provide cancellation points during layout and printing.
    header = (
        "<style>body{font-family:'Tahoma';font-size:9pt}td,th{padding:5px}th{background:#eaf2f8}</style>"
        f"<h2>{html.escape(title)}</h2><p>เริ่มนับจากจุด Web แรกในช่วงที่เลือก · รายงานหลักฐาน ไม่ใช่ยอดเรียกเก็บ</p>"
        f"<p>ช่วงฐานมิเตอร์: {html.escape(projection.epoch_id)} · รุ่นหลักฐาน: {html.escape(projection.revision)}</p>"
        f"<p>ข้อควรตรวจ: {html.escape(review_labels(projection.issues))}</p>"
    )
    # Keep each row intact in the generated HTML, including long gap remarks.
    graph_rows = ["<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in (
        item.day.isoformat(), display_number(item.total), "ประมาณการ" if item.estimated else "ยอดตามช่วงอ่าน",
        "\n".join(item.remarks))) + "</tr>" for item in projection.daily_graph()]
    sections = (
        (rows, "ยอดตามช่วงอ่าน", ("เริ่ม", "ถึง", "ผลต่าง", "วันลงยอด", "หมายเหตุ", "รอตรวจ")),
        (graph_rows, "ข้อมูลกราฟรายวัน (ค่าเฉลี่ยแทนช่วงขาด ไม่บวกซ้ำ)", ("วันที่", "ยอดแสดง", "ชนิด", "หมายเหตุ")),
    )
    chunks = [(section_rows[offset:offset+48], heading, columns)
              for section_rows, heading, columns in sections
              for offset in range(0, max(1, len(section_rows)), 48)]
    writer = QPdfWriter(str(path))
    writer.setTitle(title)
    writer.setResolution(144)
    from PyQt6.QtGui import QPageLayout
    writer.setPageOrientation(QPageLayout.Orientation.Landscape)
    painter = QPainter(writer)
    if not painter.isActive():
        raise OSError("Cannot open PDF output")
    first_page = True
    try:
        for index, (chunk, heading, columns) in enumerate(chunks):
            check(cancelled)
            document = QTextDocument()
            document.setDefaultFont(QFont("Tahoma", 9))
            document.documentLayout().setPaintDevice(writer)
            document.setPageSize(QSizeF(writer.width(), writer.height()))
            document.setHtml(header + f"<h3>{heading}</h3><table border='1' cellspacing='0' width='100%'><thead><tr>"
                + "".join(f"<th>{column}</th>" for column in columns) + "</tr></thead>"
                + "".join(chunk) + "</table>")
            for page in range(max(1, document.pageCount())):
                check(cancelled)
                if not first_page and not writer.newPage():
                    raise OSError("Cannot write PDF page")
                first_page = False
                painter.save()
                painter.translate(0, -page * writer.height())
                document.drawContents(painter, QRectF(0, page * writer.height(), writer.width(), writer.height()))
                painter.restore()
            del document
            if progress:
                progress(20 + int(70 * (index + 1) / len(chunks)),
                    tr("เขียน PDF ชุด {part}/{parts}", "Writing PDF section {part}/{parts}").format(part=index+1, parts=len(chunks)))
    finally:
        painter.end()
        del writer
    check(cancelled)


def export_web_evidence(path, projection, *, kind, printer, serial, counter_label, cancelled, progress):
    """Publish only a complete export. Cancel/error preserves the old destination."""
    destination = Path(path)
    check(cancelled)
    progress(1, tr("เตรียมหลักฐาน Web…", "Preparing Web evidence…"))
    descriptor, name = tempfile.mkstemp(prefix=".komi-evidence-", suffix="." + kind, dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        if kind == "xlsx":
            export_evidence_xlsx(temporary, projection, printer=printer, serial=serial,
                                 counter_label=counter_label, cancelled=cancelled, progress=progress)
        elif kind == "pdf":
            projection_pdf(temporary, projection, title=f"{printer} · {serial} · {counter_label}",
                           cancelled=cancelled, progress=progress)
        else:
            raise ValueError("Unsupported export format")
        progress(95, tr("บันทึกไฟล์ปลายทาง…", "Saving destination file…"))
        check(cancelled)
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)
