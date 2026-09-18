"""On-demand Web inspection, with a separate explicit billing amendment review."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import html
import logging
from threading import Event

from PyQt6.QtCore import QDate, QDateTime, QTimer, Qt
from PyQt6.QtGui import QColor, QPen, QTextDocument, QPdfWriter
from PyQt6.QtCharts import QChart, QChartView, QBarSeries, QBarSet, QBarCategoryAxis, QValueAxis, QLineSeries, QScatterSeries
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QDateEdit,
    QPushButton, QTabWidget, QTableWidget, QTableWidgetItem, QAbstractItemView, QFileDialog, QHeaderView)

from database import get_db_path
from services.web_evidence_report import load_evidence, inspect_counter, export_evidence_xlsx, review_labels
from ui.counter_review import plain


def display_number(value):
    return f"{float(value):,.2f}".rstrip("0").rstrip(".")


def projection_pdf(path, projection, *, title):
    """Paginated evidence/remarks, escaped data; no rasterized tiny printout."""
    rows = []
    for item in projection.intervals:
        rows.append("<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in (
            item.start.at.strftime("%d/%m/%Y %H:%M"), item.end.at.strftime("%d/%m/%Y %H:%M"),
            display_number(item.amount), item.allocation_day.isoformat(), item.remark,
            review_labels(item.holds))) + "</tr>")
    graph_rows = "".join("<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in (
        item.day.isoformat(), display_number(item.total), "ประมาณการ" if item.estimated else "ยอดตามช่วงอ่าน",
        "\n".join(item.remarks))) + "</tr>" for item in projection.daily_graph())
    document = QTextDocument()
    document.setHtml(
        "<style>body{font-family:'Tahoma';font-size:9pt}td,th{padding:5px}th{background:#eaf2f8}</style>"
        f"<h2>{html.escape(title)}</h2><p>เริ่มนับจากจุด Web แรกในช่วงที่เลือก · รายงานหลักฐาน ไม่ใช่ยอดเรียกเก็บ</p>"
        f"<p>ช่วงฐานมิเตอร์: {html.escape(projection.epoch_id)}</p>"
        f"<p>รุ่นหลักฐาน: {projection.revision}</p><p>ข้อควรตรวจ: {html.escape(review_labels(projection.issues))}</p>"
        "<h3>ยอดตามช่วงอ่าน</h3><table border='1' cellspacing='0'><thead><tr><th>เริ่ม</th><th>ถึง</th><th>ผลต่าง</th>"
        "<th>วันลงยอด</th><th>หมายเหตุ</th><th>รอตรวจ</th></tr></thead>" + "".join(rows) + "</table>"
        "<h3>ข้อมูลกราฟรายวัน</h3><p>แทนยอดช่วงขาดด้วยค่าเฉลี่ย ไม่บวกซ้ำกับยอดลงวันก่อนกลับมาอ่านได้</p>"
        "<table border='1' cellspacing='0'><thead><tr><th>วันที่</th><th>ยอดแสดง</th><th>ชนิด</th><th>หมายเหตุ</th>"
        "</tr></thead>" + graph_rows + "</table>")
    writer = QPdfWriter(str(path))
    writer.setTitle(title)
    writer.setResolution(144)
    from PyQt6.QtGui import QPageLayout
    writer.setPageOrientation(QPageLayout.Orientation.Landscape)
    document.print(writer)


class WebEvidenceDialog(QDialog):
    def __init__(self, devices, parent=None, *, today=None, database_path=None, calendar_timezone=None):
        super().__init__(parent)
        self.setWindowTitle("ประวัติ Web และช่วงขาดการอ่าน")
        self.resize(1050, 750)
        self.path = database_path or get_db_path()
        self.zone = calendar_timezone or datetime.now().astimezone().tzinfo
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="komi-evidence")
        self.cancelled = Event()
        pool, cancelled = self.pool, self.cancelled
        self.destroyed.connect(lambda: (cancelled.set(), pool.shutdown(wait=False, cancel_futures=True)))
        self.finished.connect(lambda _: cancelled.set())
        self.future = None
        self.evidence = None
        self.projection = None
        self.request = None
        self.counter_label = ""
        layout = QVBoxLayout(self)
        layout.addWidget(plain("ดูเฉพาะผล Web ที่บันทึกแล้ว เริ่มนับจากจุดแรกในช่วงที่เลือก · นี่คือการตรวจหลักฐาน ยังไม่เปลี่ยนยอดเรียกเก็บหรือยืนยันฐานหลัง reset"))
        controls = QHBoxLayout()
        self.devices = QComboBox()
        for device in devices:
            if device.serial:
                self.devices.addItem(f"Slot {device.slot + 1} · {device.name} · {device.serial}", (device.slot, device.serial, device.name))
        controls.addWidget(self.devices, 2)
        current = today or datetime.now().date()
        self.start_date = QDateEdit(QDate(current - timedelta(days=30)))
        self.end_date = QDateEdit(QDate(current))
        for picker in (self.start_date, self.end_date):
            picker.setDisplayFormat("dd/MM/yyyy")
            picker.setCalendarPopup(True)
            controls.addWidget(picker)
        self.load_button = QPushButton("เรียกดูข้อมูล")
        self.load_button.setEnabled(self.devices.count() > 0)
        controls.addWidget(self.load_button)
        layout.addLayout(controls)
        self.counters = QComboBox()
        layout.addWidget(self.counters)
        self.epochs = QComboBox()
        self.epochs.setAccessibleName("ช่วงฐานมิเตอร์ · แยกก่อนและหลังรีเซ็ต")
        layout.addWidget(self.epochs)
        self.status = plain("")
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.chart = QChartView(QChart())
        self.cumulative = QChartView(QChart())
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ช่วงอ่านจริง", "ผลต่าง", "วันลงยอด", "วันขาด Web", "รอตรวจ", "หมายเหตุ"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.chart, "กราฟรายวัน")
        self.tabs.addTab(self.cumulative, "มิเตอร์สะสมจริง")
        self.tabs.addTab(self.table, "รายละเอียดและหมายเหตุ")
        self.tabs.currentChanged.connect(lambda index: self.table.resizeRowsToContents() if index == 2 else None)
        actions = QHBoxLayout()
        self.xlsx_button = QPushButton("ส่งออก Excel")
        self.pdf_button = QPushButton("ส่งออก PDF")
        for button in (self.xlsx_button, self.pdf_button):
            button.setEnabled(False)
            actions.addWidget(button)
        self.amend_button = QPushButton("ตรวจแก้การแบ่งยอด")
        self.amend_button.setEnabled(False)
        self.amend_button.clicked.connect(self.amend)
        actions.addWidget(self.amend_button)
        actions.addStretch()
        close = QPushButton("ปิด")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.collect)
        self.load_button.clicked.connect(self.load)
        self.counters.currentIndexChanged.connect(self.project)
        self.epochs.currentIndexChanged.connect(self.project)
        self.xlsx_button.clicked.connect(lambda: self.export("xlsx"))
        self.pdf_button.clicked.connect(lambda: self.export("pdf"))
        self.devices.currentIndexChanged.connect(self.invalidate)
        self.start_date.dateChanged.connect(self.invalidate)
        self.end_date.dateChanged.connect(self.invalidate)

    def invalidate(self, *_):
        self.evidence = self.projection = None
        self.xlsx_button.setEnabled(False)
        self.pdf_button.setEnabled(False)
        self.amend_button.setEnabled(False)
        self.counters.clear()
        self.epochs.clear()
        self.table.setRowCount(0)
        self._replace_chart(self.chart, QChart())
        self._replace_chart(self.cumulative, QChart())
        self.status.setText("เลือกช่วงแล้วกดเรียกดูข้อมูล")

    def _busy(self, value):
        for control in (self.devices, self.start_date, self.end_date, self.counters, self.epochs):
            control.setEnabled(not value)
        self.load_button.setEnabled(not value and self.devices.count() > 0)
        self.xlsx_button.setEnabled(not value and self.projection is not None)
        self.pdf_button.setEnabled(not value and self.projection is not None)
        self.amend_button.setEnabled(not value and self.projection is not None
                                     and self.epochs.currentData() not in (None, "legacy"))

    def amend(self):
        if not self.amend_button.isEnabled() or not self.request:
            return
        from ui.billing_web_amendment import BillingWebAmendmentDialog
        request = self.request
        scope = (request["slot"], self.epochs.currentData(), request["start"], request["end"], self.zone)
        dialog = BillingWebAmendmentDialog(scope, self, database_path=self.path)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.status.setText("บันทึกฉบับแก้ไขบนคอมนี้แล้ว · รายงานยอดใช้ฉบับล่าสุด หลักฐานอ่านจริงยังคงเดิม")

    def load(self):
        if self.future is not None or self.devices.currentData() is None:
            return
        self.invalidate()
        slot, serial, name = self.devices.currentData()
        self.request = dict(slot=slot, serial=serial, start=self.start_date.date().toPyDate(),
                            end=self.end_date.date().toPyDate(), calendar_timezone=self.zone)
        self.printer_name = name
        self.cancelled.clear()
        self._busy(True)
        self.status.setText("กำลังเรียกหลักฐาน Web…")
        self.job = "load"
        self.future = self.pool.submit(load_evidence, self.path, **self.request, cancelled=self.cancelled)
        self.timer.start()

    def project(self, *_):
        if self.evidence is None or self.future is not None or self.counters.currentData() is None:
            return
        self.projection = None
        self.counter_label = self.counters.currentText()
        self._busy(True)
        self.status.setText("กำลังตรวจช่วงข้อมูลและคำนวณค่าเฉลี่ย…")
        self.job = "project"
        self.future = self.pool.submit(inspect_counter, self.evidence, self.counters.currentData(),
            epoch_id=self.epochs.currentData(), **self.request)
        self.timer.start()

    def collect(self):
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        future, self.future = self.future, None
        if self.cancelled.is_set():
            return
        try:
            result = future.result()
        except Exception as error:
            logging.getLogger(__name__).exception("Web evidence inspection failed")
            self.status.setText(str(error) if isinstance(error, ValueError) else "เรียกข้อมูลไม่ได้ กรุณาตรวจฐานข้อมูลและไฟล์ Archive")
            self._busy(False)
            return
        self._busy(False)
        if self.job == "load":
            self.evidence = result
            self.epochs.blockSignals(True)
            for epoch_id, group in result["epochs"].items():
                self.epochs.addItem(group["label"], epoch_id or "legacy")
            preferred_epoch = self.epochs.findData(result["current_epoch"])
            if preferred_epoch >= 0:
                self.epochs.setCurrentIndex(preferred_epoch)
            self.epochs.blockSignals(False)
            self.counters.blockSignals(True)
            for key, label in result["choices"]:
                self.counters.addItem(label, key)
            for field in ("counter.total.total", "counter.user.total.total"):
                preferred = next((index for index in range(self.counters.count())
                                  if self.counters.itemData(index).field == field), None)
                if preferred is not None:
                    self.counters.setCurrentIndex(preferred)
                    break
            self.counters.blockSignals(False)
            if not self.counters.count():
                self.status.setText("ไม่มีผล Web ที่บันทึกไว้ในช่วงที่เลือก")
            else:
                self.project()
        else:
            self.projection = result
            self.render_projection()
            self._busy(False)

    @staticmethod
    def _replace_chart(view, chart):
        old = view.chart()
        view.setChart(chart)
        if old is not None:
            old.deleteLater()

    def render_projection(self):
        result = self.projection
        held = sum(bool(item.holds) for item in result.intervals)
        self.status.setText(f"{len(result.points):,} จุดอ่านจริง · ผลต่างรวม {display_number(result.total_usage)} · รอตรวจ {held:,} ช่วง · สีส้ม = ประมาณการ")
        if result.issues:
            self.status.setText(self.status.text() + "\n" + review_labels(result.issues))
        chart = QChart()
        chart.setTitle("ยอดรายวันจากช่วงอ่าน Web · สีส้มเป็นค่าประมาณ แม้แสดงเป็นจำนวนเต็ม")
        series = QBarSeries()
        actual, estimated = QBarSet("ยอดตามช่วงอ่าน"), QBarSet("ประมาณการ")
        actual.setColor(QColor("#1677C8"))
        estimated.setColor(QColor("#D97706"))
        bars = result.daily_graph()
        actual.append([round(float(row.observed_interval_usage), 2) for row in bars])
        estimated.append([round(float(row.estimated_usage), 2) for row in bars])
        if any(row.observed_interval_usage for row in bars) or not any(row.estimated for row in bars):
            series.append(actual)
        if any(row.estimated for row in bars):
            series.append(estimated)
        series.setLabelsVisible(True)
        series.setLabelsFormat("@value")
        series.setLabelsPrecision(12)
        chart.addSeries(series)
        axis = QBarCategoryAxis()
        axis.append([row.day.strftime("%d/%m") for row in bars])
        chart.addAxis(axis, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis)
        values = QValueAxis()
        values.setRange(0, max((float(row.total) for row in bars), default=0) * 1.15 or 1)
        values.setLabelFormat("%.2f")
        values.applyNiceNumbers()
        chart.addAxis(values, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(values)
        self._replace_chart(self.chart, chart)
        cumulative = QChart()
        cumulative.setTitle("จุดมิเตอร์ที่อ่านจริง · เส้นประเชื่อมช่วงที่ขาดข้อมูล ไม่ใช่จุดอ่านประมาณ")
        points = QScatterSeries()
        points.setName("อ่านจริง")
        points.setMarkerSize(7)
        for point in result.points:
            points.append(point.at.timestamp() * 1000, float(point.value))
        cumulative.addSeries(points)
        run = None
        for interval in result.intervals:
            if interval.empty_days or run is None:
                segment = QLineSeries()
                pen = QPen(QColor("#D97706" if interval.empty_days else "#1677C8"))
                pen.setStyle(Qt.PenStyle.DashLine if interval.empty_days else Qt.PenStyle.SolidLine)
                segment.setPen(pen)
                segment.append(interval.start.at.timestamp() * 1000, float(interval.start.value))
                cumulative.addSeries(segment)
                run = None if interval.empty_days else segment
            else:
                segment = run
            segment.append(interval.end.at.timestamp() * 1000, float(interval.end.value))
        from PyQt6.QtCharts import QDateTimeAxis
        dates = QDateTimeAxis()
        dates.setFormat("dd/MM HH:mm")
        cumulative.addAxis(dates, Qt.AlignmentFlag.AlignBottom)
        absolute = QValueAxis()
        cumulative.addAxis(absolute, Qt.AlignmentFlag.AlignLeft)
        if result.points:
            first, last = result.points[0].at, result.points[-1].at
            if first == last:
                last = last + timedelta(minutes=1)
            dates.setRange(QDateTime.fromMSecsSinceEpoch(int(first.timestamp() * 1000)),
                           QDateTime.fromMSecsSinceEpoch(int(last.timestamp() * 1000)))
            low = min(float(point.value) for point in result.points)
            high = max(float(point.value) for point in result.points)
            margin = max(1, (high - low) * .1)
            absolute.setRange(max(0, low - margin), high + margin)
        for item in cumulative.series():
            item.attachAxis(dates)
            item.attachAxis(absolute)
        cumulative.legend().hide()
        self._replace_chart(self.cumulative, cumulative)
        self.table.setRowCount(len(result.intervals))
        for row, item in enumerate(result.intervals):
            for col, value in enumerate((f"{item.start.at:%d/%m %H:%M} → {item.end.at:%d/%m %H:%M}", display_number(item.amount),
                item.allocation_day.isoformat(), ", ".join(day.isoformat() for day in item.empty_days), review_labels(item.holds), item.remark)):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                self.table.setItem(row, col, cell)
        for column, width in enumerate((195, 70, 120, 140, 120)):
            self.table.setColumnWidth(column, width)
        self.table.resizeRowsToContents()

    def export(self, kind):
        if self.projection is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "ส่งออกหลักฐาน Web", f"KOMI-Web-evidence.{kind}", f"{kind.upper()} (*.{kind})")
        if not path:
            return
        try:
            if kind == "xlsx":
                export_evidence_xlsx(path, self.projection, printer=self.printer_name,
                    serial=self.request["serial"], counter_label=self.counter_label)
            else:
                projection_pdf(path, self.projection, title=f"{self.printer_name} · {self.request['serial']} · {self.counter_label}")
        except Exception:
            logging.getLogger(__name__).exception("Web evidence export failed")
            self.status.setText("ส่งออกไม่สำเร็จ กรุณาตรวจพื้นที่และสิทธิ์ไฟล์")
        else:
            self.status.setText(f"ส่งออกแล้ว: {path}")
