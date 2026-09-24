"""Legacy UI; owns its widgets and their lifecycle."""
from __future__ import annotations

import json
import logging
import os
import platform
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config import APP_TITLE, APP_VER, DB_PATH, SLOT_NAMES
from database import (
    copy_database_for_first_run,
    get_billing_day,
    get_cfg,
    get_config_log,
    get_db_path,
    get_price,
    get_waste_paper_pct,
    reset_db,
    reset_settings_to_default,
    sanitize_filename,
    set_cfg,
    set_waste_paper_pct,
    verify_settings_password,
)
from i18n import tr
from runtime_config import RUNTIME_SETTINGS, load_runtime_settings, save_runtime_database_path
from services.support_diagnostics import with_diagnostic
from tools.check_parser import load_profiles
from tools.db_recovery import backup_database, inspect_database
from ui.numeric_inputs import NumericDoubleSpinBox as QDoubleSpinBox
from ui.numeric_inputs import NumericSpinBox as QSpinBox
from ui.parser_editor import _parser_editor_windows
from ui.styles import buttons as buttons_styles
from ui.styles import settings as settings_styles
from ui.styles import surfaces as surfaces_styles
from ui.styles import text as text_styles
from ui.styles.tokens import C_ACCENT, C_ORANGE, C_PURPLE, C_TEXT, C_TEXT2, C_TEXT3, F_LG, F_MD, F_SM, F_XS, SLOT_COLORS
from widgets import btn, fnt, hline, make_table, mk_card, sec_title, sub_title, tbl_item

log = logging.getLogger(__name__)


class PageSettings(QWidget):
    changed = pyqtSignal()   # ส่งสัญญาณเมื่อตั้งค่าเปลี่ยน
    parser_read_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._authenticated = False
        self._build()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_parser_dropdowns()

    @staticmethod
    def _fill_parser_combo(combo, profiles):
        """เติม items ลง parser combo: เฉพาะ user profiles ที่ตั้งค่าแล้ว"""
        has_any = False
        for prof in profiles:
            if not prof.get("column_map"):  # ข้ามถ้ายังไม่ตั้งค่า column_map
                continue
            name = prof.get("name", f"Parser {prof.get('slot', '?')}")
            combo.addItem(name, prof.get("slot", 1))
            has_any = True
        if not has_any:
            combo.addItem("(ยังไม่มี Parser)", None)

    def _refresh_parser_dropdowns(self):
        """โหลด parser profiles ใหม่จากไฟล์ทุกครั้งที่เปิดหน้า Settings"""
        if not hasattr(self, "parser_dropdowns"):
            return
        profiles = load_profiles()
        for slot_idx, combo in self.parser_dropdowns.items():
            combo.blockSignals(True)
            combo.clear()
            self._fill_parser_combo(combo, profiles)
            # ตั้งค่าตาม config ที่บันทึกไว้ (ไม่ใช้ prev_data เพื่อป้องกัน mismatch)
            try:
                saved = get_cfg(f"parser_{slot_idx}", "")
                if saved:
                    idx = combo.findData(int(saved))
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
            except (ValueError, TypeError):
                pass
            combo.blockSignals(False)

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(20)
        lay.addWidget(sec_title("⚙️  ตั้งค่า"))

        # ── 1. ชื่อเครื่องพิมพ์
        c1 = mk_card(); c1.setMaximumWidth(900)
        l1 = QVBoxLayout(c1); l1.setContentsMargins(20,16,20,16); l1.setSpacing(12)
        l1.addWidget(sub_title("🖨  ชื่อเครื่องพิมพ์"))
        self.name_inp = []
        self.parser_dropdowns = {}
        parser_profiles = load_profiles()
        for i in range(3):
            hr = QHBoxLayout(); hr.setSpacing(8)
            dot = QLabel("●"); dot.setFont(fnt(F_LG, True))
            dot.setStyleSheet(text_styles.label(SLOT_COLORS[i]))
            lb = QLabel(f"เครื่อง {i+1} :"); lb.setFont(fnt(F_LG)); lb.setFixedWidth(88)
            inp = QLineEdit(get_cfg(f"machine_name_{i}", SLOT_NAMES[i]))
            inp.setFont(fnt(F_LG)); inp.setFixedWidth(160)
            sep = QLabel("|"); sep.setFont(fnt(F_LG)); sep.setStyleSheet(text_styles.label(C_TEXT3, padding='0 4px'))
            parser_lbl = QLabel("Parser :"); parser_lbl.setFont(fnt(F_MD))
            parser_combo = QComboBox(); parser_combo.setFont(fnt(F_MD)); parser_combo.setFixedWidth(300)
            self._fill_parser_combo(parser_combo, parser_profiles)
            current_parser = get_cfg(f"parser_{i}", "")
            if current_parser:
                try:
                    parser_slot_val = int(current_parser)
                    idx_p = parser_combo.findData(parser_slot_val)
                    if idx_p >= 0:
                        parser_combo.setCurrentIndex(idx_p)
                except (ValueError, TypeError):
                    pass
            parser_combo.currentIndexChanged.connect(self._update_price_label_modes)
            hr.addWidget(dot); hr.addWidget(lb); hr.addWidget(inp)
            hr.addWidget(sep); hr.addWidget(parser_lbl); hr.addWidget(parser_combo)
            l1.addLayout(hr)
            self.name_inp.append(inp)
            self.parser_dropdowns[i] = parser_combo
        btn_row = QHBoxLayout(); btn_row.setSpacing(10); btn_row.setContentsMargins(0,4,0,0)
        b_save = btn("💾  บันทึกชื่อเครื่อง", "primary"); b_save.setFixedWidth(200)
        b_save.setStyleSheet(buttons_styles.dialog_action())
        b_save.clicked.connect(self._save_names)
        b_import_parser = btn("📥  นำเข้า Parser", "outline"); b_import_parser.setFixedWidth(180)
        b_import_parser.setStyleSheet(settings_styles.SETTINGS_B_IMPORT_PARSER)
        b_import_parser.clicked.connect(self._import_parser_profile)
        btn_row.addWidget(b_save)
        btn_row.addWidget(b_import_parser)
        btn_row.addStretch()
        l1.addLayout(btn_row)
        lay.addWidget(c1)
        self._btn_save_names = b_save

        # ── 2. Price List (แยกแต่ละเครื่อง)
        c2 = mk_card(); c2.setMaximumWidth(700)
        l2 = QVBoxLayout(c2); l2.setContentsMargins(20,16,20,16); l2.setSpacing(16)
        l2.addWidget(sub_title("💰  ราคาต่อแผ่น (บาท) — แยกแต่ละเครื่อง"))

        price_specs = [
            ("a4_color", "A4 สี",    C_ACCENT),
            ("a4_bw",    "A4 ขาวดำ", C_TEXT2),
            ("a3_color", "A3 สี",    C_ORANGE),
            ("a3_bw",    "A3 ขาวดำ", C_PURPLE),
        ]

        # สร้าง price_spins dict โครงสร้าง: {slot: {key: spin}}
        self.price_spins = {0: {}, 1: {}, 2: {}}
        self.price_labels = {0: {}, 1: {}, 2: {}}

        # 3 subsections สำหรับแต่ละเครื่อง
        for slot in range(3):
            mname = get_cfg(f"machine_name_{slot}", SLOT_NAMES[slot])
            dot = QLabel("●"); dot.setFont(fnt(F_LG, True))
            dot.setStyleSheet(text_styles.label(SLOT_COLORS[slot]))
            mk_lbl = QLabel(f"เครื่อง {slot+1}: {mname}"); mk_lbl.setFont(fnt(F_MD, True))
            mk_lbl.setStyleSheet(text_styles.label(SLOT_COLORS[slot]))
            mk_row = QHBoxLayout(); mk_row.setSpacing(6)
            mk_row.addWidget(dot); mk_row.addWidget(mk_lbl); mk_row.addStretch()
            l2.addLayout(mk_row)

            pg = QGridLayout(); pg.setSpacing(10)
            for r, (key, label, color) in enumerate(price_specs):
                lbl = QLabel(f"  {label} :"); lbl.setFont(fnt(F_LG))
                lbl.setStyleSheet(text_styles.label(color)); lbl.setFixedWidth(100)
                spin = QDoubleSpinBox()
                spin.setRange(0, 9999); spin.setDecimals(2); spin.setSuffix(" บาท/แผ่น")
                spin.setValue(get_price(key, slot)); spin.setFont(fnt(F_LG)); spin.setFixedWidth(180)
                pg.addWidget(lbl, r//2, (r%2)*2); pg.addWidget(spin, r//2, (r%2)*2+1)
                self.price_spins[slot][key] = spin
                self.price_labels[slot][key] = lbl
            l2.addLayout(pg)
            if slot < 2:
                l2.addWidget(hline())

        b_price = btn("💾  บันทึก Price List", "primary"); b_price.setFixedWidth(200)
        b_price.setStyleSheet(buttons_styles.dialog_action())
        b_price.clicked.connect(self._save_prices)
        l2.addWidget(b_price)
        lay.addWidget(c2)
        self._btn_save_prices = b_price

        self._update_price_label_modes()  # ปรับ label ตาม parser mode ปัจจุบัน

        # ── 2b. % กระดาษเสีย
        c_waste = mk_card(); c_waste.setMaximumWidth(700)
        l_waste = QVBoxLayout(c_waste); l_waste.setContentsMargins(20,16,20,16); l_waste.setSpacing(12)
        l_waste.addWidget(sub_title("📄  % กระดาษเสีย (Waste Paper)"))
        wr = QHBoxLayout()
        lb_waste = QLabel("% กระดาษเสีย :"); lb_waste.setFont(fnt(F_LG)); lb_waste.setFixedWidth(140)
        self.spin_waste = QDoubleSpinBox()
        self.spin_waste.setRange(0, 100); self.spin_waste.setDecimals(1)
        self.spin_waste.setSuffix(" %"); self.spin_waste.setValue(get_waste_paper_pct())
        self.spin_waste.setFont(fnt(F_LG)); self.spin_waste.setFixedWidth(160)
        wr.addWidget(lb_waste); wr.addWidget(self.spin_waste); wr.addStretch()
        l_waste.addLayout(wr)
        waste_hint = QLabel("ใช้สำหรับหักค่าใช้จ่ายกระดาษเสียในรายงานรายเดือน")
        waste_hint.setFont(fnt(F_XS)); waste_hint.setStyleSheet(text_styles.label(C_TEXT3))
        l_waste.addWidget(waste_hint)
        b_waste = btn("💾  บันทึก % กระดาษเสีย", "primary"); b_waste.setFixedWidth(220)
        b_waste.clicked.connect(self._save_waste_pct)
        l_waste.addWidget(b_waste)
        lay.addWidget(c_waste)
        self._btn_save_waste = b_waste

        # ── 3. วันตัดรอบ
        c_day = mk_card(); c_day.setMaximumWidth(700)
        l_day = QVBoxLayout(c_day); l_day.setContentsMargins(20,16,20,16); l_day.setSpacing(12)
        l_day.addWidget(sub_title("📅  วันตัดรอบบิล"))

        dr = QHBoxLayout()
        lb_day = QLabel("วันตัดรอบบิล :"); lb_day.setFont(fnt(F_LG)); lb_day.setFixedWidth(130)
        self.spin_day = QSpinBox()
        self.spin_day.setRange(1, 31); self.spin_day.setValue(get_billing_day())
        self.spin_day.setSuffix(" ของเดือน"); self.spin_day.setFont(fnt(F_LG)); self.spin_day.setFixedWidth(180)
        dr.addWidget(lb_day); dr.addWidget(self.spin_day); dr.addStretch()
        l_day.addLayout(dr)

        day_hint = QLabel("เช่น ถ้าตั้งวัน 25 → ไฟล์ที่อ่านวันที่ 1-25 นับเป็นเดือนนั้น, หลังวันที่ 25 นับเป็นเดือนถัดไป")
        day_hint.setFont(fnt(F_XS)); day_hint.setStyleSheet(text_styles.label(C_TEXT3))
        l_day.addWidget(day_hint)

        b_day = btn("💾  บันทึกวันตัดรอบ", "primary"); b_day.setFixedWidth(200)
        b_day.setStyleSheet(buttons_styles.dialog_action())
        b_day.clicked.connect(self._save_billing_day)
        l_day.addWidget(b_day)
        lay.addWidget(c_day)
        self._btn_save_billing_day = b_day

        # ── 4. Log การเปลี่ยนแปลง Pricelist
        c_log = mk_card(); c_log.setMaximumWidth(700)
        l_log = QVBoxLayout(c_log); l_log.setContentsMargins(20,16,20,16); l_log.setSpacing(12)
        l_log.addWidget(sub_title("📋  ประวัติการเปลี่ยนแปลงการตั้งค่า"))

        self.log_table = make_table(
            ["ลำดับที่", "รายการ", "ค่าเก่า", "ค่าใหม่", "วัน/เวลา"],
            stretch_cols=[1],
            fixed_cols={0:80, 2:100, 3:100, 4:160},
            height=220
        )
        l_log.addWidget(self.log_table)
        lay.addWidget(c_log)

        # ── 5. Database path
        c3 = mk_card(); c3.setMaximumWidth(700)
        l3 = QVBoxLayout(c3); l3.setContentsMargins(20,16,20,16); l3.setSpacing(10)
        l3.addWidget(sub_title("🗄  Database"))
        self.db_lbl = QLabel()
        self.db_lbl.setFont(fnt(F_XS))
        self.db_lbl.setWordWrap(True)
        self.db_lbl.setMinimumWidth(0)
        self.db_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.db_lbl.setStyleSheet(surfaces_styles.muted_note(C_TEXT2))
        b_ch = btn("เปลี่ยน Path", "outline"); b_ch.setFixedWidth(130)
        b_ch.setStyleSheet(buttons_styles.dialog_action(compact=True))
        b_ch.clicked.connect(self._change_db)
        self._btn_change_db_path = b_ch
        l3.addWidget(self.db_lbl)
        l3.addWidget(b_ch, 0, Qt.AlignmentFlag.AlignLeft)
        self._v5_db_migration_note = QLabel(
            "การเปลี่ยน Path หรือนำ Backup กลับมาใช้ จะสร้างสำเนาที่ตรวจสอบแล้ว "
            "และมีผลเมื่อเปิดโปรแกรมครั้งถัดไป ฐานข้อมูลที่กำลังใช้จะไม่ถูกทับ"
        )
        self._v5_db_migration_note.setWordWrap(True)
        self._v5_db_migration_note.setStyleSheet(
            settings_styles.SETTINGS_V5_DB_MIGRATION_NOTE
        )
        self._v5_db_migration_note.hide()
        l3.addWidget(self._v5_db_migration_note)
        db_actions = QHBoxLayout(); db_actions.setSpacing(8)
        self._btn_check_db = btn("ตรวจสอบ Database", "outline")
        self._btn_check_db.clicked.connect(self._inspect_database)
        self._btn_backup_db = btn("สำรอง Database", "outline")
        self._btn_backup_db.clicked.connect(self._backup_database)
        self._btn_restore_db = btn("นำ Backup กลับมาใช้", "outline")
        self._btn_restore_db.clicked.connect(self._stage_database_restore)
        db_actions.addWidget(self._btn_check_db)
        db_actions.addWidget(self._btn_backup_db)
        db_actions.addWidget(self._btn_restore_db)
        db_actions.addStretch()
        l3.addLayout(db_actions)
        self._refresh_db_path_label()

        # ── Imported folder path
        l3.addWidget(QLabel("โฟลเดอร์เก็บไฟล์สำรอง (Imported):", font=fnt(F_SM)))
        default_imported = str(Path(get_cfg("db_path", str(DB_PATH))).parent / "imported")
        self.imported_lbl = QLabel(get_cfg("imported_path", default_imported))
        self.imported_lbl.setFont(fnt(F_XS))
        self.imported_lbl.setWordWrap(True)
        self.imported_lbl.setMinimumWidth(0)
        self.imported_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.imported_lbl.setStyleSheet(surfaces_styles.muted_note(C_TEXT2))
        b_ch2 = btn("เปลี่ยนโฟลเดอร์สำรอง", "outline"); b_ch2.setFixedWidth(180)
        b_ch2.setStyleSheet(buttons_styles.dialog_action(compact=True))
        b_ch2.clicked.connect(self._change_imported_path)
        b_open_imported = btn("📂  เปิดโฟลเดอร์", "outline"); b_open_imported.setMinimumWidth(150)
        b_open_imported.setStyleSheet(settings_styles.SETTINGS_B_OPEN_IMPORTED)
        b_open_imported.clicked.connect(self._open_imported_folder)
        l3.addWidget(self.imported_lbl)
        imported_actions = QHBoxLayout(); imported_actions.setSpacing(8)
        imported_actions.addWidget(b_ch2)
        imported_actions.addWidget(b_open_imported)
        imported_actions.addStretch()
        l3.addLayout(imported_actions)

        lay.addWidget(c3)

        # ── 6. Parser tuning
        c_parser = mk_card(); c_parser.setMaximumWidth(700)
        l_parser = QVBoxLayout(c_parser); l_parser.setContentsMargins(20,16,20,16); l_parser.setSpacing(10)
        l_parser.addWidget(sub_title("🧩  ตรวจสอบ Parser Mapping"))
        p_hint = QLabel(
            "ดูข้อมูล Raw จากเครื่องแต่ละ Slot เทียบกับช่องที่จะบันทึกใน Database "
            "และแก้ Mapping เฉพาะ Serial Number ได้"
        )
        p_hint.setFont(fnt(F_MD)); p_hint.setStyleSheet(text_styles.label(C_TEXT2))
        p_hint.setWordWrap(True)
        l_parser.addWidget(p_hint)
        b_parser = btn("🔎  ตรวจสอบ Parser Mapping", "outline"); b_parser.setFixedWidth(260)
        b_parser.clicked.connect(self._open_parser_settings)
        l_parser.addWidget(b_parser)
        lay.addWidget(c_parser)

        # ── 7. Program behaviour, logs and maintenance
        c_runtime = mk_card(); c_runtime.setMaximumWidth(900)
        l_runtime = QVBoxLayout(c_runtime)
        l_runtime.setContentsMargins(20, 16, 20, 16)
        l_runtime.setSpacing(12)
        l_runtime.addWidget(sub_title("⚙️  โปรแกรม Log และการบำรุงรักษา"))

        self.runtime_info = QLabel()
        self.runtime_info.setWordWrap(True)
        self.runtime_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.runtime_info.setStyleSheet(
            settings_styles.settings_runtime_info()
        )
        l_runtime.addWidget(self.runtime_info)

        self.close_to_tray = QCheckBox(
            "เมื่อกดปิดหน้าต่าง ให้โปรแกรมทำงานต่อใน System Tray"
        )
        self.close_to_tray.setChecked(get_cfg("close_to_tray", "1") != "0")
        self.close_to_tray.setToolTip(
            "ยกเลิกตัวเลือกนี้ หากต้องการให้ปุ่มปิดหน้าต่างหยุดโปรแกรมจริง"
        )
        l_runtime.addWidget(self.close_to_tray)

        preference_row = QHBoxLayout(); preference_row.setSpacing(8)
        retention_label = QLabel("เก็บ Log ย้อนหลัง")
        retention_label.setFont(fnt(F_MD, True))
        self.log_retention_days = QSpinBox()
        self.log_retention_days.setRange(1, 365)
        self.log_retention_days.setSuffix(" วัน")
        try:
            retention_days = int(get_cfg("log_retention_days", "30") or "30")
        except ValueError:
            retention_days = 30
        self.log_retention_days.setValue(max(1, min(365, retention_days)))
        save_program = btn("บันทึกการทำงานของโปรแกรม", "primary")
        save_program.clicked.connect(self._save_program_preferences)
        preference_row.addWidget(retention_label)
        preference_row.addWidget(self.log_retention_days)
        preference_row.addSpacing(10)
        preference_row.addWidget(save_program)
        preference_row.addStretch()
        l_runtime.addLayout(preference_row)

        # Two rows keep the English labels readable at the supported
        # 1024 px desktop width without forcing horizontal scrolling.
        log_actions = QGridLayout(); log_actions.setSpacing(8)
        open_logs = btn("เปิดโฟลเดอร์ Log", "outline")
        open_logs.clicked.connect(self._open_log_folder)
        export_logs = btn("ส่งออก Log สำหรับ Support", "outline")
        export_logs.clicked.connect(self._open_issue_log)
        clear_logs = btn("ล้าง Log เก่า", "outline")
        clear_logs.clicked.connect(self._clear_old_logs)
        clear_cache = btn("ล้างไฟล์ชั่วคราว", "outline")
        clear_cache.clicked.connect(self._clear_runtime_cache)
        log_actions.addWidget(open_logs, 0, 0)
        log_actions.addWidget(export_logs, 0, 1)
        log_actions.addWidget(clear_logs, 1, 0)
        log_actions.addWidget(clear_cache, 1, 1)
        log_actions.setColumnStretch(2, 1)
        l_runtime.addLayout(log_actions)
        lay.addWidget(c_runtime)

        # ── 8. Data and reset actions.  Keep all destructive choices in one
        # clearly-scannable system instead of two similar warning cards.
        c4 = mk_card()
        l4 = QVBoxLayout(c4); l4.setContentsMargins(20,16,20,16); l4.setSpacing(8)
        l4.addWidget(sub_title("⚠️  จัดการข้อมูลและคืนค่าโปรแกรม"))
        warn = QLabel("ระบบสำรอง Database ก่อนเปลี่ยนหรือลบข้อมูลทุกครั้ง กรุณาเลือกตามผลกระทบที่ต้องการ")
        warn.setFont(fnt(F_MD)); warn.setStyleSheet(text_styles.label(C_ORANGE))
        warn.setWordWrap(True)
        l4.addWidget(warn)

        def maintenance_row(title: str, detail: str, action: str, callback, *, danger: bool = False):
            row = QFrame()
            row.setObjectName("maintenance_action_row")
            row.setStyleSheet(
                settings_styles.SETTINGS_MAINTENANCE_ROW
            )
            body = QHBoxLayout(row); body.setContentsMargins(12,9,12,9); body.setSpacing(12)
            copy = QVBoxLayout(); copy.setSpacing(2)
            heading = QLabel(title); heading.setFont(fnt(F_MD, True))
            explanation = QLabel(detail); explanation.setWordWrap(True)
            explanation.setStyleSheet(text_styles.label(C_TEXT2))
            copy.addWidget(heading); copy.addWidget(explanation)
            body.addLayout(copy, 1)
            button = btn(action, "danger" if danger else "outline")
            button.setMinimumWidth(180)
            button.clicked.connect(callback)
            body.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
            l4.addWidget(row)
            return button

        b_rst = maintenance_row(
            "ล้างเฉพาะประวัติการใช้งาน",
            "ลบ Reading, Billing และ Log ใน Database · เก็บเครื่องพิมพ์ ราคา Parser และ Registration",
            "ล้างประวัติ",
            self._reset,
            danger=True,
        )
        b_rst_cfg = maintenance_row(
            "คืนค่าการตั้งค่าทั่วไป",
            "คืนชื่อเครื่อง ราคา และวันตัดรอบเป็นค่าเริ่มต้น · ไม่ลบประวัติการใช้งาน",
            "คืนค่า Settings",
            self._reset_settings,
        )
        maintenance_row(
            "คืนค่า Parser Mapping",
            "สำรองและลบ Parser Profile ที่ปรับแต่งไว้ · ไม่ลบ Database",
            "คืนค่า Parser",
            self._reset_parser,
        )
        maintenance_row(
            "เริ่มติดตั้งและตั้งค่าใหม่ทั้งหมด",
            "ลบเครื่องพิมพ์ ราคา ประวัติ Parser override และสถานะ Registration แล้วกลับไป Setup Wizard",
            "เริ่มตั้งค่าใหม่",
            self._factory_reset,
            danger=True,
        )
        lay.addWidget(c4)
        self._btn_reset_db = b_rst
        self._btn_reset_settings = b_rst_cfg
        lay.addStretch()

        # [V4.5] เปิดใช้ระบบรหัสผ่าน — เนื้อหาถูกซ่อนจนกว่าจะ unlock ผ่าน ensure_unlocked()
        self._protected_widgets = [
            c1, c2, c_waste, c_day, c_log, c3, c_parser, c_runtime, c4
        ]
        # V5 owns devices, PricingRepository, billing day and waste discount in
        # its main Settings page.  Keep the legacy cards for V4 compatibility,
        # but hide every duplicate editor when this page is embedded in V5.
        # Parser tuning remains available through the separate protected card.
        self._v5_duplicate_cards = [c1, c2, c_waste, c_day]
        self._authenticated = False
        self._set_protected_visible(False)

        # โหลด log ครั้งแรก (จะถูก refresh อีกครั้งหลัง unlock)
        self._refresh_log()



    def _set_protected_visible(self, visible: bool):
        """Show/hide protected settings widgets based on authentication"""
        for w in getattr(self, '_protected_widgets', []):
            w.setVisible(visible)

    def set_v5_embed_mode(self) -> None:
        """Prepare legacy support tools for the simplified V5 Settings page."""
        self._v5_embed_mode = True
        duplicates = set(getattr(self, "_v5_duplicate_cards", []))
        self._protected_widgets = [
            widget for widget in getattr(self, "_protected_widgets", [])
            if widget not in duplicates
        ]
        for widget in duplicates:
            widget.setVisible(False)
        if hasattr(self, "_btn_change_db_path"):
            self._btn_change_db_path.setVisible(True)
        if hasattr(self, "_v5_db_migration_note"):
            self._v5_db_migration_note.setVisible(True)
        # V5.1 no longer asks general users for a Settings password.  Risky
        # operations retain their explicit warning and confirmation dialogs.
        self._authenticated = True
        self._set_protected_visible(True)
        for widget in self._protected_widgets:
            widget.setMaximumWidth(16777215)
        title_item = self.layout().itemAt(0) if self.layout() is not None else None
        if title_item is not None and title_item.widget() is not None:
            title_item.widget().hide()
        self._refresh_db_path_label()

    def ensure_unlocked(self) -> bool:
        """เรียกก่อนเข้าแท็บ Settings: ตรวจสอบรหัสผ่านก่อนเข้าหน้า"""
        if getattr(self, "_v5_embed_mode", False):
            self._authenticated = True
            self._set_protected_visible(True)
            return True
        if getattr(self, "_authenticated", False):
            return True
        if self._ask_password():
            self._authenticated = True
            self._set_protected_visible(True)
            self._refresh_ui()
            self._refresh_log()
            return True
        return False

    def _ask_password(self) -> bool:
        """แสดง dialog ขอรหัสผ่าน"""
        from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

        from ui.styles.tokens import (
            F_MD,
            F_SM,
        )
        from widgets import fnt

        dlg = QDialog(self)
        dlg.setWindowTitle("ยืนยันรหัสผ่าน")
        dlg.setFixedWidth(320)
        dlg.setWindowFlags(
            dlg.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(12)

        lbl = QLabel("🔒  ใส่รหัสผ่านเพื่อเข้าหน้า Settings")
        lbl.setFont(fnt(F_SM, bold=True))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(text_styles.label(C_TEXT))
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        pwd_edit = QLineEdit()
        pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        pwd_edit.setPlaceholderText("รหัสผ่าน...")
        pwd_edit.setFont(fnt(F_MD))
        pwd_edit.setFixedHeight(34)
        pwd_edit.setStyleSheet(
            settings_styles.settings_pwd_edit()
        )
        lay.addWidget(pwd_edit)

        err_lbl = QLabel("")
        err_lbl.setFont(fnt(F_SM))
        err_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        err_lbl.setStyleSheet(text_styles.label('#DC2626'))
        lay.addWidget(err_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_cancel = QPushButton("ยกเลิก")
        btn_cancel.setFont(fnt(F_SM))
        btn_cancel.setFixedHeight(32)
        btn_cancel.setStyleSheet(
            settings_styles.settings_btn_cancel()
        )
        btn_cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_cancel)

        btn_ok = QPushButton("ยืนยัน")
        btn_ok.setFont(fnt(F_SM, bold=True))
        btn_ok.setFixedHeight(32)
        btn_ok.setStyleSheet(
            settings_styles.settings_btn_ok()
        )
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

        _result = [False]
        # [V4.5] password lockout — เก็บใน instance attribute
        if not hasattr(self, "_pwd_attempts"):
            self._pwd_attempts = 0
        if not hasattr(self, "_pwd_lock_until"):
            self._pwd_lock_until = None

        from datetime import datetime as _dt
        from datetime import timedelta as _td

        def _check_lock():
            if self._pwd_lock_until and _dt.now() < self._pwd_lock_until:
                remain = int((self._pwd_lock_until - _dt.now()).total_seconds())
                err_lbl.setText(f"ใส่ผิดเกินกำหนด — โปรดรอ {remain} วินาที")
                pwd_edit.setEnabled(False)
                btn_ok.setEnabled(False)
                return True
            pwd_edit.setEnabled(True)
            btn_ok.setEnabled(True)
            return False

        def _confirm():
            if _check_lock():
                return
            if verify_settings_password(pwd_edit.text()):
                _result[0] = True
                self._pwd_attempts = 0
                self._pwd_lock_until = None
                dlg.accept()
            else:
                self._pwd_attempts += 1
                remaining = max(0, 3 - self._pwd_attempts)
                if self._pwd_attempts >= 3:
                    self._pwd_lock_until = _dt.now() + _td(seconds=30)
                    err_lbl.setText("ใส่ผิด 3 ครั้ง — ล็อก 30 วินาที")
                    pwd_edit.setEnabled(False)
                    btn_ok.setEnabled(False)
                    log.warning("settings password locked for 30s after 3 failed attempts")
                else:
                    err_lbl.setText(f"รหัสผ่านไม่ถูกต้อง (เหลืออีก {remaining} ครั้ง)")
                    pwd_edit.clear()
                    pwd_edit.setFocus()

        _check_lock()
        btn_ok.clicked.connect(_confirm)
        pwd_edit.returnPressed.connect(_confirm)

        dlg.exec()
        return _result[0]

    def _import_parser_profile(self):
        """[V4.5] นำเข้า Parser Profile (.json) — validate schema/ขนาด ก่อน save"""
        from tools.check_parser import _empty_profile, load_profiles, save_profiles

        path, _ = QFileDialog.getOpenFileName(
            self, "เลือกไฟล์ Parser Profile (.json)",
            "", "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            from app import validate_parser_json
            new_profiles = validate_parser_json(path)
        except Exception as e:
            QMessageBox.critical(self, "โหลดไฟล์ไม่ได้", with_diagnostic(str(e), e, "โหลดไฟล์ไม่ได้"))
            return

        try:
            existing = load_profiles()
        except Exception:
            existing = []

        # ต่อท้าย profile ใหม่ (ไม่ทับของเดิม)
        next_slot = (max((p.get("slot", 0) for p in existing), default=0)) + 1
        added = 0
        for np_ in new_profiles:
            profile = {**_empty_profile(next_slot), **np_, "slot": next_slot}
            existing.append(profile)
            next_slot += 1
            added += 1

        save_profiles(existing)
        self._refresh_parser_dropdowns()
        QMessageBox.information(
            self, "นำเข้าสำเร็จ",
            f"นำเข้า Parser Profile {added} รายการแล้ว"
        )

    def _save_names(self):
        for i, inp in enumerate(self.name_inp):
            set_cfg(f"machine_name_{i}", inp.text())
        for slot, parser_combo in self.parser_dropdowns.items():
            parser_slot_val = parser_combo.currentData()
            if parser_slot_val:
                set_cfg(f"parser_{slot}", str(parser_slot_val))
        self.changed.emit()
        self._refresh_log()
        QMessageBox.information(self, "บันทึกแล้ว", "บันทึกชื่อเครื่องและ Parser เรียบร้อย")

    def _update_price_label_modes(self, *_):
        """ปรับ label ราคา — Label mode: แสดง Meter สี/ขาวดำ, ซ่อน A3"""
        lbl_renames = {
            "a4_color": ("Meter - สี",    "บาท/เมตร"),
            "a4_bw":    ("Meter - ขาวดำ", "บาท/เมตร"),
        }
        std_names = {
            "a4_color": ("A4 สี",    "บาท/แผ่น"),
            "a4_bw":    ("A4 ขาวดำ", "บาท/แผ่น"),
            "a3_color": ("A3 สี",    "บาท/แผ่น"),
            "a3_bw":    ("A3 ขาวดำ", "บาท/แผ่น"),
        }
        all_profiles = load_profiles()
        profiles_by_slot = {p["slot"]: p for p in all_profiles}
        for slot in range(3):
            combo = self.parser_dropdowns.get(slot)
            is_lbl = False
            if combo is not None:
                profile_slot = combo.currentData()
                prof = profiles_by_slot.get(profile_slot, {})
                is_lbl = "label" in prof.get("types", [])
            for key in ["a4_color", "a4_bw", "a3_color", "a3_bw"]:
                lbl_w = self.price_labels.get(slot, {}).get(key)
                spin  = self.price_spins.get(slot, {}).get(key)
                if not lbl_w or not spin:
                    continue
                if is_lbl:
                    if key in lbl_renames:
                        new_name, new_suffix = lbl_renames[key]
                        lbl_w.setText(f"  {new_name} :")
                        spin.setSuffix(f" {new_suffix}")
                        lbl_w.show(); spin.show()
                    else:  # a3_color, a3_bw — ซ่อน
                        lbl_w.hide(); spin.hide()
                else:
                    n, s = std_names[key]
                    lbl_w.setText(f"  {n} :")
                    spin.setSuffix(f" {s}")
                    lbl_w.show(); spin.show()

    def _save_prices(self):
        for slot in range(3):
            for key, spin in self.price_spins[slot].items():
                set_cfg(f"price_{slot}_{key}", str(spin.value()))
        self.changed.emit()
        self._refresh_log()
        QMessageBox.information(self, "บันทึกแล้ว", "บันทึก Price List เรียบร้อย")

    def _save_waste_pct(self):
        set_waste_paper_pct(self.spin_waste.value())
        self.changed.emit()
        self._refresh_log()
        QMessageBox.information(self, "บันทึกแล้ว",
            f"บันทึก % กระดาษเสีย ({self.spin_waste.value():.1f}%) เรียบร้อย")

    def _save_billing_day(self):
        set_cfg("billing_day", str(self.spin_day.value()))
        self.changed.emit()
        self._refresh_log()
        QMessageBox.information(self, "บันทึกแล้ว",
            f"บันทึกวันตัดรอบบิล (วันที่ {self.spin_day.value()}) เรียบร้อย")

    def _refresh_log(self):
        """โหลดและแสดง Pricelist change log"""
        self.log_table.setRowCount(0)
        logs = get_config_log(50)  # แสดง 50 รายการล่าสุด

        for idx, log in enumerate(logs):
            self.log_table.insertRow(idx)
            # ลำดับที่
            self.log_table.setItem(idx, 0, tbl_item(str(idx + 1), Qt.AlignmentFlag.AlignCenter))

            # รายการ (config_key) — แปลงเป็นชื่อไทยสำหรับอ่านง่าย
            config_key = log["config_key"]
            if config_key.startswith("price_"):
                # แปลง price_0_a4_color → เครื่อง 1 - A4 สี
                parts = config_key.split("_")
                if len(parts) >= 3:
                    slot = int(parts[1])
                    price_type = "_".join(parts[2:])
                    mname = get_cfg(f"machine_name_{slot}", SLOT_NAMES[slot])
                    # แปลง a4_color → A4 สี
                    price_labels = {
                        "a4_color": "A4 สี",
                        "a4_bw": "A4 ขาวดำ",
                        "a3_color": "A3 สี",
                        "a3_bw": "A3 ขาวดำ",
                    }
                    price_label = price_labels.get(price_type, price_type)
                    display_key = f"เครื่อง {slot+1}: {mname} → {price_label}"
                else:
                    display_key = config_key
            elif config_key == "billing_day":
                display_key = "วันตัดรอบบิล"
            else:
                display_key = config_key

            self.log_table.setItem(idx, 1, tbl_item(display_key))

            # ค่าเก่า
            old_val = log["old_value"] or "-"
            self.log_table.setItem(idx, 2, tbl_item(str(old_val)))

            # ค่าใหม่
            new_val = log["new_value"] or "-"
            self.log_table.setItem(idx, 3, tbl_item(str(new_val)))

            # วัน/เวลา
            time_str = log["changed_at"] or "-"
            self.log_table.setItem(idx, 4, tbl_item(str(time_str)))

    @staticmethod
    def _runtime_config_path() -> Path:
        return Path(os.environ.get("KOMI_RUNTIME_CONFIG", RUNTIME_SETTINGS.config_path))

    def _next_start_database_path(self) -> Path:
        config_path = self._runtime_config_path()
        if not config_path.is_file():
            return Path(get_db_path()).expanduser().resolve(strict=False)
        return load_runtime_settings({}, config_path=config_path).db_path.resolve(strict=False)

    @staticmethod
    def _database_filename(path: str | Path) -> Path:
        destination = Path(path).expanduser()
        if destination.suffix.casefold() != ".db":
            destination = destination.with_suffix(".db")
        return destination.resolve(strict=False)

    def _persist_next_database(self, destination: Path) -> None:
        save_runtime_database_path(destination, config_path=self._runtime_config_path())
        self._refresh_db_path_label()

    def _change_db(self):
        active = Path(get_db_path()).expanduser().resolve(strict=False)
        p, _ = QFileDialog.getSaveFileName(
            self,
            "เลือกตำแหน่ง Database ใหม่",
            str(active.with_name(f"{active.stem}-copy.db")),
            "SQLite (*.db)",
        )
        if not p:
            return
        destination = self._database_filename(p)
        try:
            copy_database_for_first_run(destination)
            self._persist_next_database(destination)
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                "เปลี่ยน Path ไม่สำเร็จ",
                with_diagnostic(f"{error}\n\nDatabase ที่กำลังใช้ไม่ถูกแก้ไข", error, "เปลี่ยน Path ไม่สำเร็จ"),
            )
            return
        QMessageBox.information(
            self,
            "เตรียม Database ใหม่แล้ว",
            f"สร้างสำเนาที่ตรวจสอบแล้ว:\n{destination}\n\n"
            "จะเริ่มใช้เมื่อปิดและเปิดโปรแกรมครั้งถัดไป",
        )

    def _inspect_database(self) -> None:
        active = Path(get_db_path())
        try:
            result = inspect_database(active)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Database ไม่ผ่าน", with_diagnostic(str(error), error, "Database ไม่ผ่าน"))
            return
        counts = result.get("critical_counts", {})
        total_rows = sum(int(value) for value in counts.values()) if isinstance(counts, dict) else 0
        QMessageBox.information(
            self,
            "Database พร้อมใช้งาน",
            f"Integrity: OK\nSchema: {result.get('user_version', '—')}\n"
            f"ตรวจพบข้อมูลสำคัญ {total_rows:,} รายการ\n\n{active}",
        )

    def _backup_database(self) -> None:
        active = Path(get_db_path()).expanduser().resolve(strict=False)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default = active.parent / "backups" / f"{active.stem}-{stamp}.db"
        p, _ = QFileDialog.getSaveFileName(
            self,
            "สำรอง Database",
            str(default),
            "SQLite (*.db)",
        )
        if not p:
            return
        destination = self._database_filename(p)
        try:
            result = backup_database(active, destination)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "สำรองไม่สำเร็จ", with_diagnostic(str(error), error, "สำรองไม่สำเร็จ"))
            return
        QMessageBox.information(
            self,
            "สำรอง Database แล้ว",
            f"Integrity: {str(result.get('integrity', '')).upper()}\n{destination}\n"
            f"Archive: {result.get('archive_files', 0):,} ไฟล์\n"
            "เก็บโฟลเดอร์ archives ข้างไฟล์สำรองไว้ด้วยเมื่อต้องย้ายหรือกู้คืน",
        )

    def _stage_database_restore(self) -> None:
        active = Path(get_db_path()).expanduser().resolve(strict=False)
        source, _ = QFileDialog.getOpenFileName(
            self,
            "เลือก Backup Database",
            str(active.parent),
            "SQLite (*.db)",
        )
        if not source:
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default = active.with_name(f"{active.stem}-restored-{stamp}.db")
        target, _ = QFileDialog.getSaveFileName(
            self,
            "บันทึกฐานข้อมูลที่จะใช้ครั้งถัดไป",
            str(default),
            "SQLite (*.db)",
        )
        if not target:
            return
        destination = self._database_filename(target)
        try:
            inspect_database(Path(source))
            backup_database(Path(source), destination)
            self._persist_next_database(destination)
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                "นำ Backup กลับมาใช้ไม่สำเร็จ",
                with_diagnostic(f"{error}\n\nDatabase ที่กำลังใช้ไม่ถูกแก้ไข", error, "นำ Backup กลับมาใช้ไม่สำเร็จ"),
            )
            return
        QMessageBox.information(
            self,
            "เตรียม Backup แล้ว",
            f"ตรวจสอบและสร้างสำเนาแล้ว:\n{destination}\n\n"
            "จะเริ่มใช้เมื่อปิดและเปิดโปรแกรมครั้งถัดไป",
        )

    def _refresh_db_path_label(self):
        """Show the database used now and a different next-start path explicitly."""
        active = Path(get_db_path()).expanduser().resolve(strict=False)
        configured = (
            self._next_start_database_path()
            if getattr(self, "_v5_embed_mode", False)
            else Path(get_cfg("db_path", str(active)) or active)
        )
        if configured == active:
            text = f"กำลังใช้งาน: {active}"
        else:
            text = f"กำลังใช้งาน: {active}\nหลังเปิดโปรแกรมครั้งถัดไป: {configured}"
        self.db_lbl.setText(text)
        self.db_lbl.setToolTip(text)

    def _change_imported_path(self):
        current = get_cfg("imported_path", "")
        start = current if current else str(Path(get_cfg("db_path", str(DB_PATH))).parent)
        p = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์เก็บไฟล์สำรอง", start)
        if p:
            self.imported_lbl.setText(p)
            set_cfg("imported_path", p)
            QMessageBox.information(self, "บันทึกแล้ว",
                f"โฟลเดอร์ Imported:\n{p}\n\nมีผลทันทีกับการ import ครั้งถัดไป")

    def _open_imported_folder(self):
        """เปิดโฟลเดอร์ imported ใน File Manager"""
        custom = get_cfg("imported_path", "")
        default = str(Path(get_cfg("db_path", str(DB_PATH))).parent / "imported")
        folder = Path(custom) if custom else Path(default)
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _open_parser_settings(self):
        """Open the V5.2 Raw → Mapping → Database inspector."""
        from ui.parser_mapping_inspector import ParserMappingInspector

        window = ParserMappingInspector(
            self,
            read_requested=self.parser_read_requested.emit,
        )
        _parser_editor_windows.append(window)
        window.destroyed.connect(
            lambda: _parser_editor_windows.remove(window)
            if window in _parser_editor_windows
            else None
        )
        window.show()
        window.raise_()
        window.activateWindow()

    def _refresh_runtime_info(self) -> None:
        log_dir = RUNTIME_SETTINGS.log_dir.expanduser().resolve(strict=False)
        close_behavior = (
            tr(
                "ปิดหน้าต่างแล้วทำงานต่อใน System Tray",
                "Closing the window keeps the app running in the System Tray",
            )
            if self.close_to_tray.isChecked()
            else tr(
                "ปิดหน้าต่างแล้วหยุดโปรแกรม",
                "Closing the window exits the application",
            )
        )
        self.runtime_info.setText(
            f"Version {APP_VER} · {platform.system()} / {platform.machine()}\n"
            f"{close_behavior}\nLog: {log_dir}"
        )

    def _save_program_preferences(self) -> None:
        set_cfg("close_to_tray", "1" if self.close_to_tray.isChecked() else "0")
        set_cfg("log_retention_days", str(self.log_retention_days.value()))
        self._refresh_runtime_info()
        self.changed.emit()
        QMessageBox.information(
            self,
            "บันทึกแล้ว",
            "บันทึกพฤติกรรมการปิดโปรแกรมและระยะเวลาเก็บ Log แล้ว",
        )

    @staticmethod
    def _active_log_paths() -> set[Path]:
        active: set[Path] = set()
        for handler in logging.getLogger().handlers:
            base_filename = getattr(handler, "baseFilename", None)
            if base_filename:
                active.add(Path(base_filename).resolve(strict=False))
        return active

    def _open_log_folder(self) -> None:
        log_dir = RUNTIME_SETTINGS.log_dir.expanduser().resolve(strict=False)
        log_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))

    def _clear_old_logs(self) -> None:
        days = self.log_retention_days.value()
        if QMessageBox.question(
            self,
            "ล้าง Log เก่า",
            f"ลบเฉพาะไฟล์ Log ที่เก่ากว่า {days} วันหรือไม่?\n\n"
            "ไฟล์ Log ที่โปรแกรมกำลังเขียนจะไม่ถูกลบ",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        root = RUNTIME_SETTINGS.log_dir.expanduser().resolve(strict=False)
        cutoff = datetime.now().timestamp() - (days * 86_400)
        active = self._active_log_paths()
        deleted = 0
        if root.is_dir():
            for candidate in root.iterdir():
                name = candidate.name.casefold()
                if (
                    not candidate.is_file()
                    or candidate.resolve(strict=False) in active
                    or (".log" not in name and ".jsonl" not in name)
                ):
                    continue
                try:
                    if candidate.stat().st_mtime < cutoff:
                        candidate.unlink()
                        deleted += 1
                except OSError:
                    log.warning("could not delete old log %s", candidate)
        QMessageBox.information(self, "ล้าง Log แล้ว", f"ลบ Log เก่า {deleted} ไฟล์")

    def _clear_runtime_cache(self) -> None:
        if QMessageBox.question(
            self,
            "ล้างไฟล์ชั่วคราว",
            "ลบเฉพาะไฟล์ .tmp, .cache และ .part ในโฟลเดอร์ runtime-cache หรือไม่?\n\n"
            "Database, ประวัติ, Billing, Excel และ Log จะไม่ถูกลบ",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        roots = {
            (RUNTIME_SETTINGS.app_home / "runtime-cache").expanduser().resolve(strict=False),
            Path(get_db_path()).expanduser().resolve(strict=False).parent / "runtime-cache",
        }
        deleted = 0
        for root in roots:
            if not root.is_dir():
                continue
            for candidate in root.rglob("*"):
                if not candidate.is_file() or candidate.suffix.casefold() not in {
                    ".tmp", ".cache", ".part"
                }:
                    continue
                try:
                    candidate.unlink()
                    deleted += 1
                except OSError:
                    log.warning("could not delete runtime cache %s", candidate)
        QMessageBox.information(
            self,
            "ล้างไฟล์ชั่วคราวแล้ว",
            f"ลบไฟล์ชั่วคราว {deleted} ไฟล์",
        )

    def _operation_access_granted(self) -> bool:
        """V5 uses explicit confirmations instead of a Settings password."""
        if getattr(self, "_v5_embed_mode", False):
            return True
        return self._ask_password()

    def _confirm_destructive(self, title: str, message: str) -> bool:
        first = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if first != QMessageBox.StandardButton.Yes:
            return False
        if not getattr(self, "_v5_embed_mode", False):
            return True
        second = QMessageBox.question(
            self,
            "ยืนยันครั้งสุดท้าย",
            "ระบบจะสำรองข้อมูลก่อนดำเนินการ\n\nยืนยันว่าต้องการทำรายการนี้จริงหรือไม่?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return second == QMessageBox.StandardButton.Yes

    def _automatic_database_backup(self, action_slug: str) -> Path | None:
        active = Path(get_db_path()).expanduser().resolve(strict=False)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        destination = active.parent / "backups" / f"{active.stem}-before-{action_slug}-{stamp}.db"
        try:
            backup_database(active, destination)
        except Exception as error:
            log.exception("automatic database backup failed before %s", action_slug)
            QMessageBox.warning(
                self,
                "หยุดรายการเพื่อป้องกันข้อมูล",
                with_diagnostic(f"สำรอง Database ไม่สำเร็จ จึงยังไม่ได้เปลี่ยนหรือลบข้อมูล\n\n{error}", error, "หยุดรายการเพื่อป้องกันข้อมูล"),
            )
            return None
        return destination

    def _reset(self):
        if not self._operation_access_granted():
            return
        if not self._confirm_destructive(
            "ยืนยันล้างข้อมูลการใช้งาน",
            "ลบประวัติการใช้งาน รายงาน Billing และ Log การตั้งค่าใน Database "
            "ทั้งหมดถาวร?\n\n"
            "การตั้งค่าเครื่องพิมพ์ ราคา Parser Registration และหน้า Wizard "
            "จะยังคงอยู่",
        ):
            return
        backup_path = self._automatic_database_backup("reset-usage")
        if backup_path is None:
            return
        reset_db()
        self.changed.emit()
        self._refresh_log()
        QMessageBox.information(
            self,
            "ล้างข้อมูลแล้ว",
            "ลบประวัติการใช้งาน รายงาน Billing และ Log การตั้งค่าใน Database "
            "เรียบร้อย\n"
            "การตั้งค่าเครื่องพิมพ์ ราคา Parser Registration และหน้า Wizard "
            "ยังคงอยู่\n\n"
            f"ไฟล์สำรอง: {backup_path}",
        )

    def _factory_reset(self):
        """Clear all V5 state so the next application launch opens Setup Wizard."""
        if not self._operation_access_granted():
            return
        message = (
            "ลบเครื่องพิมพ์ ราคา รอบบิล ประวัติการใช้งาน และ Billing Audit ทั้งหมดถาวร?\n\n"
            "เมื่อเปิดโปรแกรมใหม่ ระบบจะแสดง Setup Wizard อีกครั้ง"
        )
        if not self._confirm_destructive("ยืนยันเริ่มตั้งค่าใหม่", message):
            return
        backup_path = self._automatic_database_backup("factory-reset")
        if backup_path is None:
            return
        from database import factory_reset_v5

        factory_reset_v5()
        self.changed.emit()
        self._refresh_log()
        QMessageBox.information(
            self,
            "เริ่มตั้งค่าใหม่แล้ว",
            "ล้างข้อมูลและการตั้งค่าเรียบร้อย\n"
            "กรุณาปิดแล้วเปิดโปรแกรมใหม่เพื่อเข้าสู่ Setup Wizard\n\n"
            f"ไฟล์สำรอง: {backup_path}",
        )

    def _reset_parser(self):
        """ลบไฟล์ Parser Profile ทั้งหมด — เหมือนเปิดโปรแกรมครั้งแรก"""
        if not self._operation_access_granted():
            return
        if not self._confirm_destructive(
            "ยืนยันรีเซท Parser",
            "ลบ Parser Profile ทั้งหมดหรือไม่?\n\nระบบจะสำรอง Profile เดิมก่อนลบ",
        ):
            return
        from tools.check_parser import PROFILES_DIR
        parser_files = list(PROFILES_DIR.glob("profile_*.json"))
        backup_dir: Path | None = None
        if parser_files:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup_dir = PROFILES_DIR.parent / "backups" / f"parser-{stamp}"
            try:
                backup_dir.mkdir(parents=True, exist_ok=False)
                for parser_file in parser_files:
                    destination = backup_dir / parser_file.name
                    destination.write_bytes(parser_file.read_bytes())
            except OSError as error:
                log.exception("parser profile backup failed")
                QMessageBox.warning(
                    self,
                    "หยุดรายการเพื่อป้องกันข้อมูล",
                    with_diagnostic(f"สำรอง Parser Profile ไม่สำเร็จ จึงยังไม่ได้ลบข้อมูล\n\n{error}", error, "หยุดรายการเพื่อป้องกันข้อมูล"),
                )
                return
        deleted = 0
        for pf in parser_files:
            try:
                pf.unlink()
                deleted += 1
            except OSError:
                pass
        self._refresh_parser_dropdowns()
        QMessageBox.information(
            self, "รีเซทแล้ว",
            f"ลบ Parser Profile {deleted} รายการเรียบร้อย"
            + (f"\n\nไฟล์สำรอง: {backup_dir}" if backup_dir else "")
        )

    def _reset_settings(self):
        """รีเซทการตั้งค่า (ชื่อเครื่อง, ราคา, วันตัดรอบ) เป็นค่าเริ่มต้น"""
        if not self._operation_access_granted():
            return
        if not self._confirm_destructive(
            "ยืนยันรีเซทการตั้งค่า",
            "รีเซทชื่อเครื่อง ราคา และวันตัดรอบเป็นค่าเริ่มต้นหรือไม่?\n\n"
            "ข้อมูลที่บันทึกไว้จะถูกอัปเดตเป็นค่าเริ่มต้น",
        ):
            return
        backup_path = self._automatic_database_backup("reset-settings")
        if backup_path is None:
            return
        reset_settings_to_default()
        self.changed.emit()
        self._refresh_log()
        self._refresh_ui()
        QMessageBox.information(
            self,
            "รีเซทแล้ว",
            f"รีเซทการตั้งค่าเรียบร้อย\n\nไฟล์สำรอง: {backup_path}",
        )

    def _open_issue_log(self):
        """รวบรวม settings + 4 ไฟล์ .txt ล่าสุด + parsers + screenshots ทุกหน้า → ZIP ลง Downloads"""
        import shutil
        import sqlite3
        import sys
        import tempfile
        import zipfile

        from PyQt6.QtWidgets import QApplication

        if QMessageBox.question(
            self, "สร้าง Issue Log",
            "โปรแกรมจะรวบรวมข้อมูลต่อไปนี้เป็นไฟล์ ZIP เก็บใน Downloads:\n\n"
            "• การตั้งค่าและเวอร์ชันโปรแกรม\n"
            "• ไฟล์ .txt 4 ไฟล์ล่าสุดที่นำเข้า\n"
            "• Parser ที่ใช้ทุกตัว\n"
            "• Snapshot ของทุกหน้าจอ\n\n"
            "ดำเนินการต่อ?"
        ) != QMessageBox.StandardButton.Yes:
            return

        main_win = self.window()
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        zip_name = f"Issue log -Komi report v{APP_VER} {ts}.zip"
        downloads = Path.home() / "Downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        zip_path = downloads / zip_name

        try:
            with tempfile.TemporaryDirectory() as tmp_str:
                tmp = Path(tmp_str)

                # 1) info.txt — version + settings (mask password)
                lines = [
                    f"App        : {APP_TITLE}",
                    f"Version    : v{APP_VER}",
                    f"Generated  : {datetime.now().isoformat(timespec='seconds')}",
                    f"Platform   : {sys.platform}",
                    f"Python     : {sys.version.split()[0]}",
                    "",
                    "=== Settings ===",
                ]
                try:
                    with sqlite3.connect(get_db_path()) as conn:
                        rows = conn.execute(
                            "SELECT key, value FROM settings ORDER BY key"
                        ).fetchall()
                    for k, v in rows:
                        if "password" in k.lower():
                            v = "***REDACTED***"
                        lines.append(f"{k} = {v}")
                except Exception as e:
                    lines.append(f"(read settings failed: {e})")
                (tmp / "info.txt").write_text("\n".join(lines), encoding="utf-8")

                # 2) recent_txt/ — 4 ไฟล์ .txt ล่าสุดจาก imported folder
                recent_dir = tmp / "recent_txt"
                recent_dir.mkdir()
                try:
                    from database import get_activity_log
                    acts = get_activity_log(4)
                    custom_base = get_cfg("imported_path", "")
                    base = Path(custom_base) if custom_base else Path(get_db_path()).parent / "imported"
                    for act in acts:
                        slot = act.get("slot", 0)
                        fname = sanitize_filename(Path(act.get("file_name", "")).name)
                        card_name = get_cfg(f"machine_name_{slot}", SLOT_NAMES[slot])
                        src = base / sanitize_filename(card_name) / fname
                        if src.exists():
                            shutil.copy2(src, recent_dir / fname)
                        else:
                            (recent_dir / f"_missing_{fname}.txt").write_text(
                                f"original path: {src}\n(ไฟล์สำรองหาย)", encoding="utf-8"
                            )
                except Exception as e:
                    (recent_dir / "_error.txt").write_text(f"error: {e}", encoding="utf-8")

                # 3) parsers/ — รวมทุก parser profile
                parsers_dir = tmp / "parsers"
                parsers_dir.mkdir()
                try:
                    profiles = load_profiles()
                    (parsers_dir / "all_profiles.json").write_text(
                        json.dumps(profiles, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    from tools.check_parser import PROFILES_DIR as _PROF_DIR
                    if _PROF_DIR.exists():
                        for f in _PROF_DIR.glob("profile_*.json"):
                            shutil.copy2(f, parsers_dir / f.name)
                except Exception as e:
                    (parsers_dir / "_error.txt").write_text(f"error: {e}", encoding="utf-8")

                # 4) screenshots/ — grab ทุกหน้าใน stack (ไม่ต้องเปลี่ยนหน้าที่กำลังแสดง)
                ss_dir = tmp / "screenshots"
                ss_dir.mkdir()
                try:
                    stack = getattr(main_win, "stack", None)
                    page_names = ["overview", "import", "history", "settings", "manual"]
                    if stack is not None and stack.count() > 0:
                        for i in range(stack.count()):
                            w = stack.widget(i)
                            # ถ้าหน้านี้ห่อด้วย QScrollArea → grab widget ข้างใน (เห็นเต็มหน้า)
                            inner = w.widget() if isinstance(w, QScrollArea) else w
                            inner.adjustSize()
                            QApplication.processEvents()
                            pix = inner.grab()
                            name = page_names[i] if i < len(page_names) else f"page_{i}"
                            pix.save(str(ss_dir / f"{i+1}_{name}.png"), "PNG")
                    else:
                        main_win.grab().save(str(ss_dir / "1_main.png"), "PNG")
                except Exception as e:
                    (ss_dir / "_error.txt").write_text(f"error: {e}", encoding="utf-8")

                # 5) zip ทั้งหมด
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for root_dir, _, files in os.walk(tmp):
                        for f in files:
                            full = Path(root_dir) / f
                            zf.write(full, arcname=str(full.relative_to(tmp)))

            QMessageBox.information(
                self, "สร้าง Issue Log สำเร็จ",
                f"บันทึกไว้ที่:\n{zip_path}"
            )
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(downloads)))
        except Exception as e:
            log.exception("issue log failed")
            QMessageBox.critical(
                self, "สร้าง Issue Log ไม่ได้",
                with_diagnostic(f"{type(e).__name__}: {e}", e, "สร้าง Issue Log ไม่ได้")
            )

    def _refresh_ui(self):
        """[V4.5] รีเฟรช UI fields — ลบ dead branches (type_dropdowns/multiplier_spins ว่างเสมอ)"""
        for i, inp in enumerate(self.name_inp):
            inp.setText(get_cfg(f"machine_name_{i}", SLOT_NAMES[i]))

        for slot in range(3):
            if slot in self.parser_dropdowns:
                parser_combo = self.parser_dropdowns[slot]
                current_parser = get_cfg(f"parser_{slot}", "")
                if current_parser:
                    try:
                        idx_p = parser_combo.findData(int(current_parser))
                    except (ValueError, TypeError):
                        idx_p = -1
                    if idx_p >= 0:
                        parser_combo.setCurrentIndex(idx_p)

        # รีเฟรช Price List
        for slot in range(3):
            for key, spin in self.price_spins[slot].items():
                spin.setValue(get_price(key, slot))

        # รีเฟรช วันตัดรอบบิล
        self.spin_day.setValue(get_billing_day())
        # รีเฟรช % กระดาษเสีย
        if hasattr(self, 'spin_waste'):
            self.spin_waste.setValue(get_waste_paper_pct())
        # รีเฟรช imported path
        if hasattr(self, 'imported_lbl'):
            default_imported = str(Path(get_cfg("db_path", str(DB_PATH))).parent / "imported")
            self.imported_lbl.setText(get_cfg("imported_path", default_imported))
        if hasattr(self, 'db_lbl'):
            self._refresh_db_path_label()
        if hasattr(self, 'close_to_tray'):
            self.close_to_tray.setChecked(get_cfg("close_to_tray", "1") != "0")
        if hasattr(self, 'log_retention_days'):
            try:
                days = int(get_cfg("log_retention_days", "30") or "30")
            except ValueError:
                days = 30
            self.log_retention_days.setValue(max(1, min(365, days)))
        if hasattr(self, 'runtime_info'):
            self._refresh_runtime_info()
