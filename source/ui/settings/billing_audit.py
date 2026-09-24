"""Billing audit UI; owns its widgets and their lifecycle."""
from __future__ import annotations

import csv
import json
from datetime import date

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from i18n import ITEM_TRANSLATABLE_ROLE, apply_language, tr
from services.billing_ledger import AuditRow, audit_coverage, count_audit_rows, get_audit_row, list_audit_rows
from services.support_diagnostics import with_diagnostic
from ui.styles import reports as reports_styles
from ui.styles import text as text_styles
from ui.styles.tokens import C_TEXT2, F_2XL
from widgets import btn, fnt

_AUDIT_STATE_LABELS = {
    "effective": "มีผล",
    "open_hold": "Hold รอตรวจ",
    "open_reversal": "Reversal ยังไม่ครบคู่",
    "resolved_hold": "Hold แก้แล้ว",
    "superseded": "ถูกแทนที่",
    "paired_reversal": "Reversal จับคู่แล้ว",
}


def _pretty_audit_json(raw: str) -> str:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return str(raw)
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def audit_row_detail_text(row: AuditRow) -> str:
    """Human-readable, full-fidelity representation used by the detail dialog."""
    replaces = f"Ledger #{row.replaces_ledger_id}" if row.replaces_ledger_id is not None else "—"
    source_record = (
        f"Daily Record #{row.source_daily_record_id}"
        if row.source_daily_record_id is not None
        else "Manual / ไม่มี Daily Record"
    )
    return "\n".join(
        [
            f"Ledger ID: #{row.id}",
            f"Event: {row.entry_kind}",
            f"สถานะปัจจุบัน: {_AUDIT_STATE_LABELS.get(row.effective_state, row.effective_state)}",
            f"แทนที่ / เชื่อมโยงจาก: {replaces}",
            f"Source: {source_record}",
            f"Source hash (SHA-256): {row.source_hash}",
            f"Idempotency key: {row.idempotency_key}",
            "",
            f"เครื่อง: {row.device_name_snapshot or '—'}",
            f"Slot / Identity: {row.device_slot + 1} / {row.device_identity}",
            f"Serial snapshot: {row.device_serial_snapshot or '—'}",
            f"วันที่ข้อมูล: {row.record_date}",
            f"รอบบิลที่ถูกตรึง: {row.period_start} – {row.period_end}",
            f"วันสิ้นสุดรอบบิล: {row.billing_day}",
            f"บันทึกเมื่อ: {row.created_at}",
            "",
            f"ยอดก่อนหัก: {row.currency} {row.gross_cents / 100:,.2f}",
            f"กระดาษเสีย: {row.waste_basis_points / 100:g}% ({row.waste_basis_points} basis points)",
            f"ยอดสุทธิ: {row.currency} {row.net_cents / 100:,.2f}",
            f"Formula version: {row.formula_version}",
            f"เหตุผล / หมายเหตุ: {row.hold_reason or '—'}",
            "",
            "Delta snapshot:",
            _pretty_audit_json(row.delta_json),
            "",
            "Category snapshot:",
            _pretty_audit_json(row.category_json),
            "",
            "Price snapshot (cents):",
            _pretty_audit_json(row.price_cents_json),
            "",
            "Attestation:",
            _pretty_audit_json(row.attestation_json),
        ]
    )


class BillingAuditDetailDialog(QDialog):
    def __init__(self, row: AuditRow, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Billing Audit · Ledger #{row.id}")
        self.resize(860, 680)
        layout = QVBoxLayout(self)
        heading = QLabel(f"Ledger #{row.id} · {row.entry_kind.upper()}")
        heading.setFont(fnt(F_2XL, True))
        layout.addWidget(heading)
        from ui.counter_review import plain
        from ui.review_components import display_date, hold_reason_text, technical_details
        summary = QFormLayout()
        for caption, value in (
            (tr("เครื่องพิมพ์", "Printer"), f"Slot {row.device_slot + 1} · {row.device_name_snapshot} · {row.device_serial_snapshot}"),
            (tr("วันที่ / รอบบิล", "Day / billing period"), f"{display_date(row.record_date)} · {display_date(row.period_start)} – {display_date(row.period_end)}"),
            (tr("ผลต่อยอด", "Billing effect"), _AUDIT_STATE_LABELS.get(row.effective_state, row.effective_state)),
            (tr("ก่อนส่วนลด / สุทธิ", "Gross / net"), f"฿{row.gross_cents / 100:,.2f} / ฿{row.net_cents / 100:,.2f}"),
            (tr("หมายเหตุ", "Remark"), hold_reason_text(row.hold_reason)),
        ):
            value_label = plain(value)
            value_label.setProperty("i18n_data", True)
            summary.addRow(caption, value_label)
        layout.addLayout(summary)
        layout.addWidget(plain(tr("รายการเดิมยังคงอยู่ การแก้ยอดจะสร้างรายการใหม่พร้อมหลักฐาน", "Original entries are preserved. Corrections create new entries with evidence.")))
        evidence = technical_details(audit_row_detail_text(row))
        body = evidence.findChild(QPlainTextEdit)
        body.setObjectName("billingAuditDetail")
        layout.addWidget(evidence)
        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def _load_billing_audit_view(limit, state, search):
    return (audit_coverage(), count_audit_rows(state=state, search=search),
            list_audit_rows(limit, state=state, search=search))


class PageBillingAudit(QWidget):
    """Read-only, pageable proof of effective and intentionally held billing."""

    PAGE_SIZE = 100
    EXPORT_FIELDS = tuple(AuditRow.__dataclass_fields__)

    def __init__(self, parent=None, *, embedded=False) -> None:
        super().__init__(parent)
        self._loaded_limit = self.PAGE_SIZE
        self._rows: list[AuditRow] = []
        from ui.background_read import LatestRead
        self.audit_reader = LatestRead(self)
        self.audit_reader.ready.connect(self._apply_audit_view)
        self.audit_reader.failed.connect(self._audit_failed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0) if embedded else layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        title = QLabel("ตรวจสอบและแก้ไขรอบบิล")
        title.setFont(fnt(F_2XL, True))
        layout.addWidget(title)
        title.setVisible(not embedded)
        hint = QLabel(
            tr("รายการรอตรวจยังไม่คิดเงิน · เลือกแถวเพื่อดูหลักฐานหรือแก้ยอด",
               "Held items are not billed. Select a row to review evidence or correct an amount.")
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            reports_styles.BILLING_AUDIT_HINT
        )
        layout.addWidget(hint)
        self.coverage = QLabel()
        self.coverage.setWordWrap(True)
        layout.addWidget(self.coverage)

        self.shared_posting_button = btn(tr('ตรวจยอดจากประวัติร่วมก่อนลงบัญชี', 'Review shared history before posting'), 'outline')
        self.shared_posting_button.clicked.connect(self._shared_posting)
        layout.addWidget(self.shared_posting_button, 0, Qt.AlignmentFlag.AlignLeft)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        filters.addWidget(QLabel("สถานะ"))
        self.state_filter = QComboBox()
        self.state_filter.setProperty("i18n_items", True)
        self.state_filter.setObjectName("billingAuditStateFilter")
        self.state_filter.addItem("ทั้งหมด", None)
        self.state_filter.addItem("มีผลต่อยอด", "effective")
        self.state_filter.addItem("Hold รอตรวจ", "open_hold")
        self.state_filter.addItem("Reversal ยังไม่ครบคู่", "open_reversal")
        self.state_filter.addItem("รายการแก้ไขทั้งหมด", "correction")
        filters.addWidget(self.state_filter)
        self.search = QLineEdit()
        self.search.setObjectName("billingAuditSearch")
        self.search.setPlaceholderText("ค้นหา ID, เครื่อง, Serial, เหตุผล, hash หรือวันที่ แล้วกด Enter")
        filters.addWidget(self.search, 1)
        self.refresh_button = btn("Refresh", "outline")
        filters.addWidget(self.refresh_button)
        layout.addLayout(filters)

        self.table = QTableWidget(0, 9)
        self.table.setObjectName("billingAuditTable")
        self.table.setAccessibleName("รายการ Billing Audit")
        self.table.setHorizontalHeaderLabels(
            [
                "ID",
                "วันที่",
                "เครื่อง",
                "Event / ผล",
                "สุทธิ",
                "รอบบิล",
                "เชื่อมโยง Ledger",
                "เหตุผล",
                "บันทึกเมื่อ",
            ]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column in (0, 1, 3, 4, 5, 6, 8):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.row_count = QLabel()
        self.row_count.setStyleSheet(text_styles.label('#64748B'))
        actions.addWidget(self.row_count)
        actions.addStretch(1)
        self.load_more_button = btn("โหลดเพิ่ม", "outline")
        self.detail_button = btn("ดูรายละเอียด", "outline")
        self.detail_button.setEnabled(False)
        self.reprice_button = btn("คำนวณใหม่จากประวัติราคา", "outline")
        self.reprice_button.setEnabled(False)
        self.reprice_range_button = btn("คำนวณใหม่ตามวันที่", "outline")
        self.manual_review_button = btn("ตรวจและแก้ยอด", "outline")
        self.manual_review_button.setEnabled(False)
        self.reprice_button.setToolTip("คำนวณรายการที่เลือกใหม่จากราคาตามวันบังคับใช้")
        self.reprice_range_button.setToolTip("ตรวจรายการและคำนวณราคาใหม่ตามช่วงวันที่ที่เลือก")
        self.manual_review_button.setToolTip("ตรวจหลักฐานและกรอกยอดแก้ไขของรายการที่เลือก")
        self.export_button = btn("Export CSV", "outline")
        actions.addWidget(self.load_more_button)
        actions.addWidget(self.detail_button)
        actions.addWidget(self.export_button)
        corrections = QHBoxLayout()
        corrections.addWidget(self.reprice_button)
        corrections.addWidget(self.reprice_range_button)
        corrections.addWidget(self.manual_review_button)
        corrections.addStretch(1)
        layout.addLayout(corrections)
        layout.addLayout(actions)

        self.state_filter.currentIndexChanged.connect(self._reset_and_refresh)
        self.search.returnPressed.connect(self._reset_and_refresh)
        self.refresh_button.clicked.connect(self._reset_and_refresh)
        self.load_more_button.clicked.connect(self._load_more)
        self.detail_button.clicked.connect(self._show_selected_detail)
        self.reprice_button.clicked.connect(self._reprice_selected)
        self.reprice_range_button.clicked.connect(self._reprice_range)
        self.manual_review_button.clicked.connect(self._manual_review)
        self.export_button.clicked.connect(self._export)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(self._show_detail)
        self.coverage.setText(tr("เปิดหน้านี้เพื่อตรวจสอบรอบบิล", "Open this page to check billing history"))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def hideEvent(self, event):
        self.audit_reader.cancel()
        super().hideEvent(event)

    def _audit_failed(self, detail):
        self.row_count.setText(tr("โหลดไม่สำเร็จ · กด Refresh เพื่อลองใหม่", "Load failed · Select Refresh to retry"))
        self.row_count.setToolTip(detail)

    def _current_state(self) -> str | None:
        value = self.state_filter.currentData()
        return str(value) if value else None

    def _reset_and_refresh(self, _value=None) -> None:
        self._loaded_limit = self.PAGE_SIZE
        self.refresh()

    def _load_more(self) -> None:
        self._loaded_limit += self.PAGE_SIZE
        self.refresh()

    def _refresh_coverage(self, coverage) -> None:
        self.coverage.setText(
            tr("มีผลต่อยอด {effective} วัน · Hold รอตรวจ {held} วัน · Reversal ยังไม่ครบคู่ {reversals} วัน · "
               "มีประวัติการแก้ไข {corrected} วัน\nข้อมูลเก่าก่อนใช้ Ledger {legacy} วัน · ข้อมูลใหม่ที่ควรมี Ledger แต่หาย {missing} วัน",
               "Days: effective {effective} · held for review {held} · unpaired reversals {reversals} · "
               "corrected {corrected}\nBefore Ledger {legacy} · new records missing Ledger evidence {missing}").format(
                   effective=coverage.effective_posted, held=coverage.open_holds,
                   reversals=coverage.open_reversals, corrected=coverage.corrected_sources,
                   legacy=coverage.legacy_uncovered, missing=coverage.expected_missing)
        )
        if coverage.expected_missing or coverage.open_reversals:
            style = reports_styles.REFRESH_COVERAGE_STYLE
        elif coverage.open_holds:
            style = reports_styles.REFRESH_COVERAGE_STYLE_WARNING
        else:
            style = reports_styles.REFRESH_COVERAGE_STYLE_SUCCESS
        self.coverage.setStyleSheet(reports_styles.billing_audit_coverage(style))

    def refresh(self) -> None:
        self.row_count.setText(tr("กำลังตรวจสอบรอบบิล…", "Checking billing history…"))
        self.row_count.setToolTip("")
        for control in (self.detail_button, self.reprice_button, self.manual_review_button, self.load_more_button):
            control.setEnabled(False)
        self.audit_reader.request(_load_billing_audit_view, self._loaded_limit, self._current_state(), self.search.text())

    def _apply_audit_view(self, payload) -> None:
        coverage, total, rows = payload
        self._refresh_coverage(coverage)
        self._rows = rows
        self.table.setRowCount(len(self._rows))
        state_colors = {
            "effective": QColor("#146C4A"),
            "open_hold": QColor("#9A5A00"),
            "open_reversal": QColor("#B42318"),
            "resolved_hold": QColor("#1769AA"),
            "superseded": QColor("#64748B"),
            "paired_reversal": QColor("#64748B"),
        }
        for row_no, row in enumerate(self._rows):
            state_label = _AUDIT_STATE_LABELS.get(row.effective_state, row.effective_state)
            link = f"#{row.replaces_ledger_id}" if row.replaces_ledger_id is not None else "—"
            machine = row.device_name_snapshot or row.device_identity
            values = [
                f"#{row.id}",
                row.record_date,
                machine,
                f"{row.entry_kind.upper()} · {state_label}",
                f"฿{row.net_cents / 100:,.2f}",
                f"{row.period_start} – {row.period_end}",
                link,
                row.hold_reason or "—",
                row.created_at,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(audit_row_detail_text(row) if column in {0, 3, 6, 7} else str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row.id)
                if column == 3:
                    item.setData(ITEM_TRANSLATABLE_ROLE, True)
                    item.setForeground(state_colors.get(row.effective_state, QColor(C_TEXT2)))
                self.table.setItem(row_no, column, item)
        self.row_count.setText(f"แสดง {len(self._rows):,} จาก {total:,} รายการ")
        remaining = max(0, total - len(self._rows))
        self.load_more_button.setVisible(remaining > 0)
        self.load_more_button.setEnabled(remaining > 0)
        self.load_more_button.setText(f"โหลดเพิ่ม ({remaining:,})" if remaining else "โหลดเพิ่ม")
        self.detail_button.setEnabled(False)
        self.reprice_button.setEnabled(False)
        apply_language(self)

    def _selected_ledger_id(self) -> int | None:
        row_no = self.table.currentRow()
        item = self.table.item(row_no, 0) if row_no >= 0 else None
        return int(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def _selection_changed(self) -> None:
        ready = not self.audit_reader.busy and self._selected_ledger_id() is not None
        self.detail_button.setEnabled(ready)
        self.reprice_button.setEnabled(ready)
        self.manual_review_button.setEnabled(ready)

    def _shared_posting(self) -> None:
        from ui.shared_billing import SharedBillingDialog
        dialog = SharedBillingDialog(self)
        dialog.finished.connect(lambda _result: self.refresh())
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.open()

    def _manual_review(self) -> None:
        ledger_id = self._selected_ledger_id()
        if ledger_id is None:
            return
        from ui.billing_manual_review import BillingManualReviewDialog
        dialog = BillingManualReviewDialog(ledger_id, self)
        dialog.finished.connect(lambda _result: self.refresh())
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.open()

    def _reprice_selected(self) -> None:
        ledger_id = self._selected_ledger_id()
        if ledger_id is None:
            return
        from ui.billing_repricing import BillingRepricingDialog
        dialog = BillingRepricingDialog(ledger_id, self)
        dialog.finished.connect(lambda _result: self.refresh())
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.open()

    def _reprice_range(self) -> None:
        from ui.billing_repricing_batch import BatchRepricingDialog
        dialog = BatchRepricingDialog(self)
        dialog.finished.connect(lambda _result: self.refresh())
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.open()

    def _show_detail(self, row_no: int, _column: int = 0) -> None:
        item = self.table.item(row_no, 0)
        if item is None:
            return
        row = get_audit_row(int(item.data(Qt.ItemDataRole.UserRole)))
        if row is not None:
            BillingAuditDetailDialog(row, self).exec()

    def _show_selected_detail(self) -> None:
        row_no = self.table.currentRow()
        if row_no >= 0:
            self._show_detail(row_no)

    def _export_rows_to(self, path: str) -> int:
        rows = list_audit_rows(limit=None, state=self._current_state(), search=self.search.text())
        with open(path, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(self.EXPORT_FIELDS)
            for row in rows:
                writer.writerow([getattr(row, field) for field in self.EXPORT_FIELDS])
        return len(rows)

    def _export(self) -> None:
        suggested = f"komi-billing-audit-{date.today().isoformat()}.csv"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Billing Audit",
            suggested,
            "CSV (*.csv)",
        )
        if not path:
            return
        try:
            count = self._export_rows_to(path)
        except OSError as exc:
            QMessageBox.warning(self, "Export ไม่สำเร็จ", with_diagnostic(str(exc), exc, "Export ไม่สำเร็จ"))
            return
        QMessageBox.information(self, "Export สำเร็จ", f"บันทึก {count:,} รายการแล้ว")
