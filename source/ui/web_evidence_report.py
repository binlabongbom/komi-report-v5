"""On-demand Web inspection, with a separate explicit billing amendment review."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import logging
from threading import Event

from PyQt6.QtCore import QDate, QDateTime, QTimer, Qt
from PyQt6.QtGui import QColor, QPen
from PyQt6.QtCharts import QChart, QChartView, QBarSeries, QBarSet, QBarCategoryAxis, QValueAxis, QLineSeries, QScatterSeries
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QDateEdit,
    QPushButton, QTabWidget, QTableWidget, QTableWidgetItem, QAbstractItemView, QFileDialog, QHeaderView, QPlainTextEdit, QLabel)

from database import get_db_path
from services.web_evidence_report import load_evidence, inspect_counter, export_evidence_xlsx, review_labels
from ui.counter_review import plain
from ui.review_components import labeled_control, field_label
from i18n import tr
from functools import partial
from services.web_evidence_export import projection_pdf, export_web_evidence
from ui.report_export import ReportExportController


def display_number(value):
    return f"{float(value):,.2f}".rstrip("0").rstrip(".")




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
        controls.addWidget(labeled_control(self.devices, "เครื่องพิมพ์", "Printer"), 2)
        current = today or datetime.now().date()
        self.start_date = QDateEdit(QDate(current - timedelta(days=30)))
        self.end_date = QDateEdit(QDate(current))
        for picker, thai, english in ((self.start_date, "วันที่เริ่มต้น", "Start date"), (self.end_date, "วันที่สิ้นสุด", "End date")):
            picker.setDisplayFormat("dd/MM/yyyy")
            picker.setCalendarPopup(True)
            controls.addWidget(labeled_control(picker, thai, english))
        self.load_button = QPushButton("เรียกดูข้อมูล")
        self.load_button.setEnabled(self.devices.count() > 0)
        controls.addWidget(self.load_button)
        layout.addLayout(controls)
        self.counters = QComboBox()
        field_label(layout, self.counters, "มิเตอร์", "Counter")
        layout.addWidget(self.counters)
        self.epochs = QComboBox()
        self.epochs.setAccessibleName("ช่วงฐานมิเตอร์ · แยกก่อนและหลังรีเซ็ต")
        field_label(layout, self.epochs, "ช่วงฐานมิเตอร์", "Meter epoch")
        layout.addWidget(self.epochs)
        self.status = plain("")
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.chart = QChartView(QChart())
        self.cumulative = QChartView(QChart())
        self.table = QTableWidget(0, 6)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setHorizontalHeaderLabels(["ช่วงอ่านจริง", "ผลต่าง", "วันลงยอด", "วันขาด Web", "รอตรวจ", "หมายเหตุ"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.chart, "กราฟรายวัน")
        self.tabs.addTab(self.cumulative, "มิเตอร์สะสมจริง")
        self.tabs.addTab(self.table, "รายละเอียดและหมายเหตุ")
        self.tabs.currentChanged.connect(self._tab_changed)
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
        self.detail_amend_button = QPushButton('ตรวจแก้รายละเอียด')
        self.detail_amend_button.setEnabled(False)
        self.detail_amend_button.clicked.connect(self.amend_detail)
        actions.addWidget(self.detail_amend_button)
        self.row_detail_button = QPushButton(tr("อ่านหมายเหตุเต็ม", "Read full remarks"))
        self.row_detail_button.setEnabled(False)
        self.row_detail_button.clicked.connect(self.show_row_details)
        self.table.itemSelectionChanged.connect(self._update_row_detail)
        self.table.cellDoubleClicked.connect(self.show_row_details)
        actions.addWidget(self.row_detail_button)
        actions.addStretch()
        close = QPushButton("ปิด")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.export_controller = None
        self.finished.connect(self._stop_export)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.collect)
        self.load_button.clicked.connect(self.load)
        self.counters.currentIndexChanged.connect(self.project)
        self.epochs.currentIndexChanged.connect(self.project)
        self.xlsx_button.clicked.connect(self.export_xlsx)
        self.pdf_button.clicked.connect(self.export_pdf)
        self.devices.currentIndexChanged.connect(self.invalidate)
        self.start_date.dateChanged.connect(self.invalidate)
        self.end_date.dateChanged.connect(self.invalidate)

    def invalidate(self, *_):
        self.evidence = self.projection = None
        self.xlsx_button.setEnabled(False)
        self.pdf_button.setEnabled(False)
        self.amend_button.setEnabled(False)
        self.detail_amend_button.setEnabled(False)
        self.counters.clear()
        self.epochs.clear()
        self.table.setRowCount(0)
        self._replace_chart(self.chart, QChart())
        self._replace_chart(self.cumulative, QChart())
        self.status.setText(tr('เลือกช่วงแล้วกดเรียกดูข้อมูล', 'Choose dates and load evidence'))

    def _tab_changed(self, index):
        if index == 2:
            self.table.resizeRowsToContents()

    def _busy(self, value):
        for control in (self.devices, self.start_date, self.end_date, self.counters, self.epochs):
            control.setEnabled(not value)
        self.load_button.setEnabled(not value and self.devices.count() > 0)
        self.xlsx_button.setEnabled(not value and self.projection is not None)
        self.pdf_button.setEnabled(not value and self.projection is not None)
        self.amend_button.setEnabled(not value and self.projection is not None
                                     and self.epochs.currentData() not in (None, "legacy"))
        self.detail_amend_button.setEnabled(self.amend_button.isEnabled())

    def amend_detail(self):
        if not self.detail_amend_button.isEnabled() or not self.request:
            return
        from ui.report_detail_amendment import ReportDetailAmendmentDialog
        request = self.request
        scope = (request['slot'], self.epochs.currentData(), request['start'], request['end'], self.zone, self.counters.currentData())
        dialog = ReportDetailAmendmentDialog(scope, self, database_path=self.path)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.status.setText('บันทึกฉบับแก้ไขรายละเอียดแล้ว · รายงานใช้ฉบับล่าสุดและเก็บต้นฉบับไว้')

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
        self.status.setText(tr('กำลังเรียกหลักฐาน Web…', 'Loading Web evidence…'))
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
                self.status.setText(tr('ไม่มีผล Web ที่บันทึกไว้ในช่วงที่เลือก', 'No saved Web readings in the selected period.'))
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
        self.status.setText(tr("{count:,} จุดอ่านจริง · ผลต่างรวม {total} · รอตรวจ {held:,} ช่วง · สีส้ม = ประมาณการ",
            "{count:,} actual readings · Total difference {total} · {held:,} intervals need review · Orange = estimated").format(count=len(result.points), total=display_number(result.total_usage), held=held))
        if result.issues:
            self.status.setText(self.status.text() + "\n" + review_labels(result.issues))
        chart = QChart()
        chart.setTitle(tr('ยอดรายวันจากช่วงอ่าน Web · สีส้มเป็นค่าประมาณ แม้แสดงเป็นจำนวนเต็ม', 'Daily usage from Web intervals. Orange values are estimates, including whole numbers.'))
        bars = result.daily_graph()
        # A baseline is evidence, but not an interval with zero usage. Do not
        # attach empty QBarSets/axes or imply that usage was measured as zero.
        if not bars:
            chart.setTitle(tr("ยังไม่มีช่วงอ่านให้คำนวณ · ต้องมีผล Web อย่างน้อยสองครั้ง", "No usage interval yet. At least two Web readings are required."))
            chart.legend().hide()
        else:
            series = QBarSeries()
            actual, estimated = QBarSet("ยอดตามช่วงอ่าน"), QBarSet("ประมาณการ")
            actual.setColor(QColor("#1677C8"))
            estimated.setColor(QColor("#D97706"))
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

    def _stop_export(self, *_):
        if self.export_controller is not None:
            self.export_controller.shutdown()

    def _ensure_export_controller(self):
        if self.export_controller is None:
            self.export_controller = ReportExportController(self)
            self.export_controller.busy_changed.connect(self._export_busy)
            self.export_controller.succeeded.connect(self._export_succeeded)
            self.export_controller.failed.connect(self._export_failed)
        return self.export_controller

    def _export_succeeded(self, path):
        self.status.setText(tr("ส่งออกแล้ว: {path}", "Exported: {path}").format(path=path))

    def _export_failed(self, error):
        self.status.setText(tr("ส่งออกไม่สำเร็จ กรุณาปิดไฟล์ที่เปิดอยู่และตรวจพื้นที่/สิทธิ์ไฟล์", "Export failed. Close any open destination file and check disk space and permissions."))

    def _export_busy(self, busy):
        for button in (self.xlsx_button, self.pdf_button):
            button.setEnabled(not busy and self.projection is not None)

    def _update_row_detail(self):
        self.row_detail_button.setEnabled(self.table.currentRow() >= 0)

    def export_xlsx(self):
        self.export("xlsx")

    def export_pdf(self):
        self.export("pdf")

    def show_row_details(self, *_):
        row = self.table.currentRow()
        if row < 0 or row >= self.table.rowCount():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("รายละเอียดช่วงอ่านและหมายเหตุ", "Reading interval and remarks"))
        dialog.resize(720, 440)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText("\n\n".join(
            f"{self.table.horizontalHeaderItem(column).text()}:\n{self.table.item(row, column).text()}"
            for column in range(self.table.columnCount()) if self.table.item(row, column) is not None))
        layout.addWidget(text)
        close = QPushButton(tr("ปิด", "Close"))
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def export(self, kind):
        if self.projection is None or (self.export_controller is not None and self.export_controller.busy):
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("ส่งออกหลักฐาน Web", "Export Web evidence"),
                                             f"KOMI-Web-evidence.{kind}", f"{kind.upper()} (*.{kind})")
        if not path:
            return
        job = partial(export_web_evidence, path, self.projection, kind=kind, printer=self.printer_name,
                      serial=self.request["serial"], counter_label=self.counter_label)
        self._ensure_export_controller().start(job, title=tr("ส่งออกหลักฐาน Web", "Export Web evidence") + " · " + kind.upper())
