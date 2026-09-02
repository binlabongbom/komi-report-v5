# ═══════════════════════════════════════════════════════════
# app.py — หน้าต่างหลัก (Main Window) และจุดเริ่มต้นโปรแกรม
#
# โครงสร้างไฟล์และความรับผิดชอบ:
#   config.py   — สีสัน, ฟอนต์, ค่าคงที่  [แก้ที่นี่เพื่อเปลี่ยนหน้าตาโปรแกรม]
#   database.py — ฐานข้อมูล SQLite + แยก/อ่านข้อมูลจากไฟล์ .txt ของเครื่องพิมพ์
#   widgets.py  — คอมโพเนนต์ UI ที่ใช้ซ้ำได้ (StatCard, buttons, ฯลฯ)
#   pages.py    — หน้า Report เดิม (Overview, Import, History, Settings, Manual)
#   live_meter_page.py — อ่าน Counter สดจาก bizhub แบบ read-only
#   app.py      — หน้าต่างหลัก, sidebar, entry point ← ไฟล์นี้
#
# ความสัมพันธ์ระหว่างไฟล์:
#   MainWindow → ช่องเก็บข้อมูล _data → ส่งให้หน้
# 
# 
# าต่างอื่นผ่าน lambda
#   ↓ เมื่อนำเข้าข้อมูลใหม่ → _refresh_all() → อัปเดตทุกหน้า
# ═══════════════════════════════════════════════════════════

import json
import logging
import os
import platform
import sys
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def _disable_tray_context_menu_for_current_macos() -> bool:
    """Avoid the AppKit status-menu crash seen with Qt on macOS 27+.

    The background agent is still available from the status item: a normal
    click restores the main window, where Sync and Exit remain available.
    Older macOS versions retain the compact tray menu.
    """
    if sys.platform != "darwin":
        return False
    try:
        major = int((platform.mac_ver()[0] or "0").split(".", 1)[0])
    except ValueError:
        return False
    return major >= 27

# [V4.5] ขีดจำกัดและ schema สำหรับ Parser JSON
MAX_PARSER_JSON_BYTES = 1_000_000  # 1MB
_ALLOWED_PROFILE_KEYS = {
    "slot", "name", "model", "model_lower", "ncols",
    "types", "column_map", "header_row", "data_row_start",
    "detect_strategy", "label_columns",
    "encoding", "delimiter", "description", "notes", "version",
}


def validate_parser_json(path: str) -> list:
    """[V4.5] โหลดและ validate Parser Profile JSON
    raises ValueError ถ้าไม่ผ่าน schema/ขนาด
    """
    p = Path(path)
    if p.stat().st_size > MAX_PARSER_JSON_BYTES:
        raise ValueError(f"ไฟล์ใหญ่เกินไป (>{MAX_PARSER_JSON_BYTES // 1000}KB)")

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON ไม่ถูกต้อง: {e}") from e
    except UnicodeDecodeError as e:
        raise ValueError(f"ไฟล์ไม่ใช่ UTF-8: {e}") from e

    if isinstance(data, dict) and isinstance(data.get("profiles"), list):
        raw_profiles = data["profiles"]
    elif isinstance(data, dict):
        raw_profiles = [data]
    else:
        raise ValueError("รูปแบบ JSON ไม่ถูกต้อง (ต้องเป็น object หรือ {profiles: [...]})")

    profiles = []
    for i, prof in enumerate(raw_profiles):
        if not isinstance(prof, dict):
            log.warning("skip non-dict profile at index %d", i)
            continue
        name = prof.get("name")
        if not isinstance(name, str) or not name.strip():
            log.warning("skip profile without name at index %d", i)
            continue
        # whitelist keys
        clean = {k: v for k, v in prof.items() if k in _ALLOWED_PROFILE_KEYS}
        # validate column_map ทุก value ต้องเป็น int หรือ list[int]
        cm = clean.get("column_map")
        if cm is not None:
            if not isinstance(cm, dict):
                log.warning("invalid column_map in %r", name)
                continue
            ok = True
            for ck, cv in cm.items():
                if isinstance(cv, int):
                    continue
                if isinstance(cv, list) and all(isinstance(x, int) for x in cv):
                    continue
                if cv is None:
                    continue
                ok = False
                log.warning("invalid column_map[%s]=%r in %r", ck, cv, name)
                break
            if not ok:
                continue
        # validate types
        types = clean.get("types")
        if types is not None and not (isinstance(types, list) and all(isinstance(x, str) for x in types)):
            log.warning("invalid types in %r", name)
            continue
        profiles.append(clean)

    if not profiles:
        raise ValueError("ไม่พบ Profile ที่ใช้งานได้ในไฟล์")
    return profiles

# PyQt6 — ไลบรารี UI หลักของโปรแกรม
#   QApplication   — ต้องสร้างก่อนทุกอย่าง เป็นตัวจัดการ event loop ทั้งหมด
#   QMainWindow    — หน้าต่างหลักของโปรแกรม มี titlebar และ menubar
#   QWidget        — พื้นฐานของทุก UI component (กล่องสี่เหลี่ยมที่วาดได้)
#   QVBoxLayout    — จัด Widget แนวตั้ง (Vertical)
#   QHBoxLayout    — จัด Widget แนวนอน (Horizontal)
#   QLabel         — แสดงข้อความหรือรูปภาพ
#   QPushButton    — ปุ่มกด
#   QFrame         — กล่องที่ใส่ border หรือ background ได้
#   QStackedWidget — ซ้อนหลาย Widget ไว้แต่แสดงทีละอัน (ใช้สลับหน้า)
#   QScrollArea    — ห่อ Widget ให้เลื่อน scroll ได้ถ้าเนื้อหายาวเกิน
from PyQt6.QtCore import Qt, QTimer  # ค่าคงที่ของ Qt เช่น alignment, cursor shape
from PyQt6.QtGui import QAction, QCloseEvent, QFont, QIcon, QPixmap  # QFont = ฟอนต์, QPixmap = รูปภาพ
from PyQt6.QtNetwork import QNetworkInformation
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from config import *  # สี, ฟอนต์, ขนาด, ค่าคงที่ทั้งหมด — ปรับแก้ที่ config.py
from database import (  # ฟังก์ชันฐานข้อมูลที่ใช้ที่นี่
    compute_diff,
    get_billing_day,
    get_cfg,
    get_db_path,
    get_last_two,
    get_latest_read_date,
    get_price,
    get_waste_paper_pct,
    init_db,
    set_cfg,
)
from i18n import ENGLISH, THAI, apply_language, get_language, set_language, tr
from pages import (
    PageImport,
    PageManual,
    PageOverview,
    PageSettings,  # หน้าตั้งค่า + คู่มือ
)
from services.application_identity import (
    configure_qt_application_identity,
    configure_windows_process_identity,
)
from services.autostart import configure_autostart
from services.background_polling import BackgroundPollingCoordinator
from services.desktop_shortcuts import create_desktop_shortcuts
from services.device_config import DeviceConfigRepository
from services.instance_guard import SingleInstanceGuard
from services.offline_license_keys import (
    OfflineLicensePublicKeyConfigurationError,
    load_offline_license_public_keys,
)
from services.v5_2_client import V52ContractClient, V52RuntimeConfig
from services.v5_2_runtime import V52RuntimeCoordinator
from services.web_service import web_service_manager
from ui_consistency import install_button_system
from v5_pages import (
    PageHistoryV5,
    PageImportV5,
    PageSettingsV5,
    SetupWizardV5,
)
from widgets import fnt  # fnt(size, bold) — สร้าง QFont อย่างสั้น

# หน้าที่ผู้ใช้เปิดได้จาก Sidebar ตามลำดับที่แสดงจริง
SIDEBAR_NAV_ITEMS: tuple[tuple[str, str], ...] = (
    ("▸", "ภาพรวม"),
    ("▸", "อุปกรณ์"),
    ("▸", "รายงาน"),
    ("▸", "ตั้งค่า"),
    ("▸", "คู่มือ"),
)

# ══════════════════════════════════════════════════════════
# SPLASH SCREEN — หน้าต่าง Loading ก่อนเปิดโปรแกรม
# แสดงขึ้นมาทันทีที่สั่งรันโปรแกรม เพื่อแจ้งผู้ใช้ว่าโปรแกรมกำลังทำงาน
# ปิดตัวเองอัตโนมัติเมื่อ MainWindow พร้อมแสดงผล
# ══════════════════════════════════════════════════════════
class SplashScreen(QWidget):
    def __init__(self):
        super().__init__()
        # FramelessWindowHint   — ไม่มี titlebar / border
        # WindowStaysOnTopHint  — อยู่บนสุดเสมอ
        # Tool                  — ไม่ปรากฏใน taskbar / dock
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(420, 290)
        self._center()
        self._build()

    def _center(self):
        """จัดหน้าต่างให้อยู่กลางหน้าจอ"""
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width()  - self.width())  // 2,
            (screen.height() - self.height()) // 2,
        )

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Card — พื้นหลังสีเข้มเหมือน sidebar
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {C_SIDEBAR};
                border-radius: 20px;
            }}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(44, 36, 44, 36)
        cl.setSpacing(10)

        # โลโก้
        logo_path = os.path.join(os.path.dirname(__file__), LOGO_FILENAME)
        logo_lbl = QLabel()
        logo_pixmap = QPixmap(logo_path)
        if not logo_pixmap.isNull():
            logo_pixmap = logo_pixmap.scaledToWidth(
                140, Qt.TransformationMode.SmoothTransformation
            )
            logo_lbl.setPixmap(logo_pixmap)
            logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            logo_lbl.setText("KM")
            logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_lbl.setStyleSheet("color: white; font-size: 22pt; font-weight: bold;")
        cl.addWidget(logo_lbl)

        # ชื่อโปรแกรม
        title_lbl = QLabel(APP_TITLE)
        title_lbl.setFont(fnt(F_MD, bold=True))
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setStyleSheet("color: #ffffff;")
        cl.addWidget(title_lbl)

        # เวอร์ชัน
        ver_lbl = QLabel(f"v{APP_VER}")
        ver_lbl.setFont(fnt(F_XS))
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_lbl.setStyleSheet("color: rgba(255,255,255,0.50);")
        cl.addWidget(ver_lbl)

        cl.addSpacing(14)

        # ข้อความสถานะ — อัปเดตได้ผ่าน set_message()
        self._msg_lbl = QLabel("กำลังเริ่มต้นโปรแกรม...")
        self._msg_lbl.setFont(fnt(F_SM))
        self._msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._msg_lbl.setStyleSheet("color: rgba(255,255,255,0.70);")
        cl.addWidget(self._msg_lbl)

        root.addWidget(card)

    def set_message(self, text: str):
        """อัปเดตข้อความสถานะ แล้ว force repaint ทันที"""
        self._msg_lbl.setText(text)
        QApplication.processEvents()


# ══════════════════════════════════════════════════════════
# NAV BUTTON — ปุ่มนำทางในแถบข้าง (Sidebar)
# ══════════════════════════════════════════════════════════
class NavButton(QPushButton):
    """ปุ่ม navigation สำหรับสลับหน้า UI ต่างๆ ใน sidebar"""
    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        # objectName="nav" ทำให้ QSS ใน config.py ระบุสไตล์ได้เฉพาะปุ่มนี้
        # เช่น QPushButton#nav { ... }  ซึ่งต่างจากปุ่มทั่วไป
        self.setObjectName("nav")
        self.setText(f"  {icon}   {label}")  # เว้นวรรคหน้าเพื่อ indent ให้สวย
        self.setAccessibleName(label)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFont(fnt(F_XL))
        self.setFixedHeight(NAV_BUTTON_HEIGHT)  # ความสูงคงที่ กำหนดใน config.py
        self.setCursor(Qt.CursorShape.PointingHandCursor)  # เปลี่ยน cursor เป็นมือเมื่อ hover

    def set_active(self, active: bool):
        # กำหนด property "active" เพื่อให้ QSS เปลี่ยนสีปุ่มที่กำลังเลือกอยู่
        # unpolish + polish บังคับให้ Qt อ่าน QSS ใหม่ทันที (จำเป็นเมื่อ property เปลี่ยน)
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)



# ══════════════════════════════════════════════════════════
# MAIN WINDOW — หน้าต่างหลักของโปรแกรม
# ══════════════════════════════════════════════════════════
class _DeferredPage(QWidget):
    """Construct an expensive page only when the user first opens it."""

    def __init__(self, factory, parent=None):
        super().__init__(parent)
        self._factory = factory
        self._page = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._placeholder = QLabel(tr("กำลังเตรียมหน้าจอ...", "Preparing page..."))
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._placeholder)

    def load(self) -> QWidget:
        if self._page is not None:
            return self._page
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            page = self._factory()
            self._layout.addWidget(page)
            self._layout.removeWidget(self._placeholder)
            self._placeholder.deleteLater()
            self._page = page
            self._factory = None
            return page
        finally:
            QApplication.restoreOverrideCursor()


class MainWindow(QMainWindow):
    def __init__(self, splash: "SplashScreen | None" = None):
        super().__init__()
        install_button_system(QApplication.instance())
        self.setWindowTitle(f"{APP_TITLE} V{APP_VER}")  # ชื่อโปรแกรมบน titlebar
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)  # ขนาดเล็กสุดที่ resize ได้
        self.resize(WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT)   # ขนาดเริ่มต้นเมื่อเปิด

        # โหลด QSS (คือ CSS สำหรับ Qt) เพื่อกำหนดหน้าตาทุก widget ในโปรแกรม
        # ถ้าต้องการเปลี่ยนสี/ฟอนต์/ขอบ → แก้ที่ config.py ฟังก์ชัน build_qss()
        self.setStyleSheet(build_qss())

        # _data เก็บข้อมูลของเครื่องพิมพ์ 3 เครื่อง (slot 0, 1, 2)
        # แต่ละ slot เก็บ tuple: (curr_record, prev_record, diff)
        #   curr_record — ข้อมูลล่าสุดที่ import เข้ามา (dict จาก database)
        #   prev_record — ข้อมูลก่อนหน้า (สำหรับคำนวณส่วนต่าง)
        #   diff        — dict ผลต่างที่คำนวณแล้ว เช่น จำนวนที่พิมพ์เพิ่มขึ้น
        # หน้าต่างอื่นรับ _data ผ่าน lambda: self._data (ดูที่ PageOverview)
        self._data = [None, None, None]
        self._dirty_pages: set[int] = set()
        self._ui_ready = False

        # ตรวจสอบก่อนว่า DB มีอยู่แล้วหรือยัง (เพื่อตรวจจับการติดตั้งครั้งแรก)
        self._is_fresh_db = not get_db_path().exists()

        if splash: splash.set_message("กำลังเตรียมฐานข้อมูล...")
        init_db()         # สร้างตาราง SQLite ถ้ายังไม่มี (ทำครั้งแรกครั้งเดียว)
        set_language(get_cfg("ui_language", THAI))
        # V5.2 Registration uses per-installation Ed25519 proof and receives a
        # short-lived installation token from the Host. No shared Desktop API
        # key or customer credential is embedded here.
        self.registration = V52RuntimeCoordinator(
            V52ContractClient(
                V52RuntimeConfig(
                    base_url="https://www.dmskm.com",
                    environment="production",
                )
            ),
            parent=self,
        )
        try:
            self.offline_license_public_keys = load_offline_license_public_keys()
        except OfflineLicensePublicKeyConfigurationError:
            log.exception("Offline License public verification keys are invalid")
            self.offline_license_public_keys = {}

        if splash: splash.set_message("กำลังสร้างหน้าจอ...")
        self._build_ui()  # สร้าง UI ทั้งหมด: sidebar + stack ของหน้าต่างๆ
        self._ui_ready = True

        if splash: splash.set_message("กำลังโหลดข้อมูล...")
        self._quitting = False
        self._background_started = False
        self._registration_collection_ready = False
        # V5.2.6 performance: do not block first paint on database aggregation.
        # The same refresh still runs immediately after the event loop gets a
        # chance to present the workspace, preserving data and UI semantics.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self._refresh_all)
        self._startup_refresh_pending = True
        self.polling = BackgroundPollingCoordinator(parent=self)
        self.web_service = web_service_manager()
        self.polling.device_updated.connect(self._device_updated)
        self.polling.reading_saved.connect(lambda _slot: self._schedule_refresh_all())
        self.polling.reading_saved.connect(self.registration.meter_observed)
        self.pg_import.sync_requested.connect(self._request_manual_poll)
        self.pg_overview.sync_requested.connect(self._request_manual_poll)
        self._build_tray()
        self.registration.status_changed.connect(self._registration_status_changed)
        self._install_network_recovery_monitor()
        apply_language(self)

    # ──────────────────────────────────────────────────────
    # BUILD UI — สร้างโครงสร้างหน้าตาทั้งหมด
    # โครงสร้างหน้าต่าง:
    #   QMainWindow
    #   └─ central (QWidget)
    #      └─ main_lay (QHBoxLayout) — แนวนอน ซ้าย-ขวา
    #         ├─ sidebar (QWidget)        — แถบซ้าย: โลโก้ + ปุ่มนำทาง + status
    #         └─ stack (QStackedWidget)  — พื้นที่หลัก: ซ้อน 5 หน้าไว้แสดงทีละหน้า
    # ──────────────────────────────────────────────────────
    def _build_ui(self):
        # central widget คือจุดกึ่งกลางที่ QMainWindow กำหนดให้เป็น content หลัก
        central = QWidget()
        self.setCentralWidget(central)
        # layout แนวนอน: sidebar อยู่ซ้าย, stack อยู่ขวา
        main_lay = QHBoxLayout(central)
        main_lay.setContentsMargins(0, 0, 0, 0)  # ไม่มีระยะขอบรอบนอก
        main_lay.setSpacing(0)                    # ไม่มีช่องว่างระหว่าง sidebar กับ content

        # ─ SIDEBAR ────────────────────────────────────────
        # Widget แถบซ้าย มีความกว้างคงที่ (SIDEBAR_WIDTH จาก config.py)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")  # QSS ใน config.py ใช้ #sidebar เพื่อกำหนดสีพื้นหลัง
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        sb_lay = QVBoxLayout(sidebar)  # layout แนวตั้งภายใน sidebar
        sb_lay.setContentsMargins(SIDEBAR_MARGIN_LEFT, SIDEBAR_MARGIN_TOP,
                                  SIDEBAR_MARGIN_RIGHT, SIDEBAR_MARGIN_BOTTOM)
        sb_lay.setSpacing(SIDEBAR_SPACING)  # ระยะห่างระหว่างปุ่มแต่ละปุ่ม

        # ─ โลโก้ด้านบน Sidebar ────────────────────────────────
        # หัวแบบ compact: icon เล็กทางซ้าย + ชื่อผลิตภัณฑ์ทางขวา
        logo = QFrame()
        logo.setStyleSheet("background: transparent; border: none;")
        ll = QHBoxLayout(logo)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        logo_img = QLabel()
        # หา path ของไฟล์รูปโลโก้ โดยเริ่มจากโฟลเดอร์เดียวกับไฟล์ app.py นี้
        logo_path = os.path.join(os.path.dirname(__file__), LOGO_FILENAME)
        logo_pixmap = QPixmap(logo_path)
        if not logo_pixmap.isNull():  # โหลดรูปสำเร็จ
            logo_pixmap = logo_pixmap.scaledToWidth(
                LOGO_SCALED_WIDTH, Qt.TransformationMode.SmoothTransformation
            )  # ย่อขนาดรูปให้พอดี sidebar โดยไม่แตก
            logo_img.setPixmap(logo_pixmap)
            logo_img.setFixedSize(LOGO_SCALED_WIDTH, LOGO_SCALED_WIDTH)
            logo_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:  # ไม่พบไฟล์รูป — แสดงข้อความแทน
            logo_img.setText("Logo")
            logo_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_img.setStyleSheet("color: white; font-weight: bold;")

        ll.addWidget(logo_img)
        logo_title = QLabel("KOMI REPORT")
        logo_title.setFont(fnt(F_LG, bold=True))
        logo_title.setStyleSheet(
            "color:#FFFFFF;background:transparent;border:none;letter-spacing:0.4px;"
        )
        logo_title.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        ll.addWidget(logo_title, 1)
        sb_lay.addWidget(logo)
        sb_lay.addSpacing(LOGO_MARGIN_BOTTOM)  # เว้นช่องว่างหลังโลโก้ก่อนปุ่ม nav

        # ─ ปุ่ม Navigation ──────────────────────────────────
        # ลำดับปุ่มต้องตรงกับลำดับที่เพิ่มหน้าใน stack ด้านล่าง
        self.nav_btns = []  # เก็บปุ่มทุกตัวไว้เพื่อใช้ใน _nav() และ set_active()
        for icon, label in SIDEBAR_NAV_ITEMS:
            b = NavButton(icon, label)
            # lambda ต้องมี btn_ref=b เพื่อ capture ค่า b ณ ขณะวนลูป
            # ถ้าไม่ทำแบบนี้ทุกปุ่มจะส่ง b ตัวสุดท้ายเหมือนกันหมด (Python closure)
            b.clicked.connect(lambda _, btn_ref=b: self._nav(btn_ref))
            sb_lay.addWidget(b)
            self.nav_btns.append(b)

        sb_lay.addStretch()  # ดัน status label ให้อยู่ล่างสุดของ sidebar

        language_label = QLabel("ภาษา / Language")
        language_label.setStyleSheet("color:#BFD3E6;padding:2px 8px;background:transparent;")
        sb_lay.addWidget(language_label)
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("language_selector")
        self.language_combo.addItem("ไทย", THAI)
        self.language_combo.addItem("English", ENGLISH)
        self.language_combo.setCurrentIndex(1 if get_language() == ENGLISH else 0)
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        sb_lay.addWidget(self.language_combo)

        # ─ Status Label ───────────────────────────────────────
        # แสดงเวลาล่าสุดที่ refresh ข้อมูล อยู่ล่างสุดของ sidebar
        self.status_lbl = QLabel("พร้อมใช้งาน")
        self.status_lbl.setFont(fnt(F_XS))
        self.status_lbl.setWordWrap(True)  # ตัดบรรทัดถ้าข้อความยาว
        self.status_lbl.setStyleSheet(
            f"color:#CBD5E1; padding:{STATUS_PADDING}; background:transparent;"
        )
        sb_lay.addWidget(self.status_lbl)

        main_lay.addWidget(sidebar)

        # ─ CONTENT AREA (QStackedWidget) ──────────────────────
        # QStackedWidget ซ้อน widget หลายตัวไว้ แสดงทีละตัวตาม index
        # การสลับหน้า = setCurrentIndex(idx) ใน _nav()
        self.stack = QStackedWidget()
        # Scope the background to the stack itself.  An unqualified local
        # declaration cascades to every descendant in Qt and previously
        # replaced primary-button backgrounds while leaving their white text.
        self.stack.setObjectName("main_content_stack")
        self.stack.setStyleSheet(
            f"QStackedWidget#main_content_stack {{ background: {C_BG}; }}"
        )

        # สร้างแต่ละหน้า — ลำดับต้องตรงกับ nav_items ด้านบน
        # ใช้โครง Overview เดิมจาก V4.6 เป็นหน้ารายงานหลักของ V5
        self.pg_overview = PageOverview(lambda: self._data)
        self.pg_import   = PageImportV5(PageImport())
        # These hidden pages dominate window construction. Build them only
        # when the user first navigates to them.
        self.pg_history  = _DeferredPage(PageHistoryV5)
        self.pg_settings = _DeferredPage(
            lambda: PageSettingsV5(
                PageSettings(),
                registration_runtime=self.registration,
                offline_license_public_keys=self.offline_license_public_keys,
            )
        )
        self.pg_manual   = _DeferredPage(PageManual)

        pages = [
            self.pg_overview,
            self.pg_import,
            self.pg_history,
            self.pg_settings,
            self.pg_manual,
        ]
        self._page_widgets = list(pages)
        self._reports_index = pages.index(self.pg_history)
        self._settings_index = pages.index(self.pg_settings)
        self._manual_index = pages.index(self.pg_manual)
        self._deferred_pages = {
            self._reports_index: ("pg_history", self.pg_history),
            self._settings_index: ("pg_settings", self.pg_settings),
            self._manual_index: ("pg_manual", self.pg_manual),
        }
        # หน้าที่ใช้ Tab / ตารางภายในจัดการ scroll เอง → ไม่ต้องห่อ QScrollArea
        # Reports, Settings and Manual own their internal scrolling.  Keeping
        # Manual out of this wrapper lets its right-side table of contents stay
        # fixed while the guide itself scrolls as one continuous document.
        no_scroll = {self.pg_history, self.pg_settings, self.pg_manual}
        for pg in pages:
            if pg in no_scroll:
                # ใส่ตรงๆ ใน stack — เนื้อหาภายในจัดการ scroll เอง
                self.stack.addWidget(pg)
            else:
                # ห่อด้วย QScrollArea เพื่อให้เลื่อน scroll ได้
                sc = QScrollArea()
                sc.setWidget(pg)
                sc.setWidgetResizable(True)
                sc.setFrameShape(QFrame.Shape.NoFrame)
                sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                self.stack.addWidget(sc)

        # เมื่อผู้ใช้ import ไฟล์ใหม่ หรือเปลี่ยน settings → ให้ refresh ข้อมูลทุกหน้า
        # changed เป็น signal ที่ PageImport และ PageSettings emit เมื่อมีการเปลี่ยนแปลง
        self.pg_import.changed.connect(self._refresh_all)
        self.pg_import.settings_requested.connect(self._open_device_settings)
        self.pg_import.sync_log_requested.connect(self._open_sync_log)
        self.pg_overview.reports_requested.connect(self._open_reports)
        self.pg_overview.sync_log_requested.connect(self._open_sync_log)
        main_lay.addWidget(self.stack, 1)  # stretch=1 ให้ stack ขยายเต็มพื้นที่ที่เหลือ

        self._nav(self.nav_btns[0])  # เปิดหน้า Overview เป็นหน้าแรกเมื่อเริ่มโปรแกรม

    def _open_device_settings(self, _slot: int) -> None:
        settings = self._load_deferred_page(self._settings_index)
        settings.show_main()
        self._nav(self.nav_btns[self._settings_index])

    def _open_sync_log(self) -> None:
        settings = self._load_deferred_page(self._settings_index)
        settings.show_activity()
        self._nav(self.nav_btns[self._settings_index])

    def _open_schedule_settings(self) -> None:
        settings = self._load_deferred_page(self._settings_index)
        settings.show_main()
        self._nav(self.nav_btns[self._settings_index])

    def _open_reports(self) -> None:
        self._dirty_pages.add(self._reports_index)
        self._nav(self.nav_btns[self._reports_index])

    def _load_deferred_page(self, index: int) -> QWidget:
        deferred = self._deferred_pages.pop(index, None)
        if deferred is None:
            return self._page_widgets[index]
        attribute, host = deferred
        page = host.load()
        setattr(self, attribute, page)
        self._page_widgets[index] = page
        if index == self._settings_index:
            page.changed.connect(self._refresh_all)
            page.changed.connect(self.polling.reload_policy)
            page.changed.connect(self.registration.configuration_changed)
            page.sync_requested.connect(self._request_manual_poll)
            page.parser_read_requested.connect(self._request_manual_poll)
        elif index == self._reports_index:
            page.reading_status_requested.connect(self._open_sync_log)
        apply_language(page)
        if self._background_started:
            self._apply_registration_collection_gate()
        return page

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self)
        icon_path = os.path.join(os.path.dirname(__file__), LOGO_FILENAME)
        self.tray.setIcon(QIcon(icon_path))
        if _disable_tray_context_menu_for_current_macos():
            # macOS 27 can abort inside AppKit while presenting a Qt status
            # menu (NSStatusItem -> NSCalendarDate).  Do not create a QMenu
            # on that platform: normal click safely restores the application.
            self.tray.setToolTip("KOMI Report V5 — คลิกเพื่อเปิดหน้าต่างหลัก")
            self._tray_menu = None
            log.warning("tray context menu disabled on macOS 27+; click opens main window")
        else:
            self.tray.setToolTip("KOMI Report V5 — Background Meter")
            self._tray_menu = QMenu(self)
            open_action = QAction("เปิด KOMI Report", self)
            open_action.triggered.connect(self._show_from_tray)
            self._tray_menu.addAction(open_action)
            read_action = QAction("อ่านค่าทุกเครื่องทันที", self)
            read_action.triggered.connect(self._request_manual_poll)
            self._tray_read_action = read_action
            self._tray_menu.addAction(read_action)
            self._tray_menu.addSeparator()
            exit_action = QAction("Exit", self)
            exit_action.triggered.connect(self._exit_application)
            self._tray_menu.addAction(exit_action)
            self.tray.setContextMenu(self._tray_menu)
        self.tray.activated.connect(self._handle_tray_activation)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def _handle_tray_activation(self, reason) -> None:
        """Restore the app on click when a safe tray menu is unavailable."""
        open_reasons = {QSystemTrayIcon.ActivationReason.DoubleClick}
        if _disable_tray_context_menu_for_current_macos():
            open_reasons.add(QSystemTrayIcon.ActivationReason.Trigger)
        if reason in open_reasons:
            self._show_from_tray()

    def start_background_services(self):
        if self._background_started:
            return
        self._background_started = True
        # A persisted ``registered`` state may be stale after the Host was
        # deactivated while the app was closed. Keep all device reads paused
        # until the startup status probe finishes.
        self._registration_collection_ready = False
        self._apply_registration_collection_gate()
        self.registration.start()
        self.registration.configuration_changed()
        self.polling.start()
        if get_cfg("web_service_enabled", "1") != "0":
            status = self.web_service.start()
            log.info("web service start requested: %s (%s)", status.state, status.detail)

    def _registration_status_changed(self, _status: str) -> None:
        if self._background_started:
            self._registration_collection_ready = True
            self._apply_registration_collection_gate()

    def _registration_usage_eligibility(self) -> tuple[bool, str]:
        if self._background_started and not self._registration_collection_ready:
            return False, "status_check_pending"
        try:
            return self.registration.usage_eligibility()
        except Exception:
            log.exception("cannot verify registration eligibility for polling")
            return False, "registration_unavailable"

    def _request_manual_poll(self, slot: int | None = None) -> None:
        # QAction.triggered carries a ``checked`` bool; it is not a device slot.
        if isinstance(slot, bool):
            slot = None
        eligible, _reason = self._registration_usage_eligibility()
        if not eligible:
            self._apply_registration_collection_gate()
            return
        self.polling.poll_now(slot)

    def _set_collection_actions_enabled(self, enabled: bool) -> None:
        targets = [
            getattr(self, "_tray_read_action", None),
            getattr(getattr(self, "pg_import", None), "sync_button", None),
            getattr(getattr(self, "pg_overview", None), "btn_sync_now", None),
            getattr(
                getattr(getattr(self, "pg_settings", None), "activity", None),
                "sync_button",
                None,
            ),
        ]
        for target in targets:
            if target is not None:
                target.setEnabled(enabled)

    def _apply_registration_collection_gate(self) -> None:
        """Keep local history open while fail-closing every new device read."""
        eligible, reason = self._registration_usage_eligibility()
        if eligible:
            self.polling.resume()
            self._set_collection_actions_enabled(
                not bool(getattr(self.polling, "active", ()))
            )
            self.status_lbl.setText("เปิดใช้งาน · ดูประวัติและอ่านข้อมูลใหม่ได้")
            self.status_lbl.setToolTip(f"Registration: {reason}")
            return
        self.polling.pause(reason)
        self._set_collection_actions_enabled(False)
        status = (
            "กำลังตรวจสอบสถานะ · ดูประวัติได้\nยังไม่ดึงข้อมูลใหม่จากเครื่อง"
            if reason == "status_check_pending"
            else "ปิดใช้งาน · ดูประวัติได้\nหยุดดึงข้อมูลใหม่จากเครื่อง"
        )
        self.status_lbl.setText(status)
        self.status_lbl.setToolTip(f"Registration: {reason}")

    def _install_network_recovery_monitor(self) -> None:
        """Wake V5.2 only on an OS-observed connectivity recovery transition."""

        self._network_information = None
        self._last_network_reachability = QNetworkInformation.Reachability.Unknown
        try:
            QNetworkInformation.loadDefaultBackend()
            information = QNetworkInformation.instance()
            if information is None:
                return
            self._network_information = information
            self._last_network_reachability = information.reachability()
            information.reachabilityChanged.connect(self._network_reachability_changed)
        except (RuntimeError, TypeError):
            log.info("OS network recovery monitor is unavailable")

    def _network_reachability_changed(self, reachability) -> None:
        previous = self._last_network_reachability
        self._last_network_reachability = reachability
        connected = {
            QNetworkInformation.Reachability.Local,
            QNetworkInformation.Reachability.Site,
            QNetworkInformation.Reachability.Online,
        }
        if reachability in connected and previous not in connected:
            self.registration.network_recovered()

    def _device_updated(self, _slot: int):
        # Device and reading signals often arrive together (and once per
        # device). Coalesce that burst so the UI thread redraws only once.
        self._schedule_refresh_all()
        if not self.polling.active:
            self.pg_import.sync_completed()
        if self.polling.is_paused:
            self._set_collection_actions_enabled(False)
            return
        devices = DeviceConfigRepository().list(enabled_only=True)
        online = sum(device.connection_status == "online" for device in devices)
        self.status_lbl.setText(f"Background active\nOnline {online}/{len(devices)}")

    def _show_main_window(self):
        """Show the desktop workspace at the maximum usable screen size."""
        self.showMaximized()
        self.raise_()
        self.activateWindow()

    def _show_from_tray(self):
        self._show_main_window()

    def _language_changed(self, _index: int) -> None:
        language = str(self.language_combo.currentData() or THAI)
        set_language(language)
        set_cfg("ui_language", language)
        apply_language(self)
        # Rebuild charts and status strings that are painted outside ordinary
        # Qt text widgets (for example the Overview Y-axis title).
        self._refresh_visible_page()
        self.status_lbl.setToolTip(
            tr("ภาษาที่เลือกจะถูกใช้เมื่อเปิดโปรแกรมครั้งถัดไปด้วย", "The selected language will also be used at the next launch")
        )

    def _settings_page_with_draft(self):
        page = self._page_widgets[self._settings_index]
        checker = getattr(page, "has_unsaved_changes", None)
        return page if callable(checker) and checker() else None

    def _confirm_leave_settings(self) -> bool:
        if self._settings_page_with_draft() is None:
            return True
        reply = QMessageBox.question(
            self,
            tr("ยังไม่ได้บันทึก", "Unsaved changes"),
            tr(
                "ส่วนที่กำลังแก้ยังไม่ได้บันทึก ระบบจะเก็บ draft ไว้ในหน้า Settings หากไปหน้าอื่นตอนนี้ ต้องการไปต่อหรือไม่?",
                "The section you are editing has not been saved. Its draft will remain in Settings. Leave this page now?",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _confirm_discard_settings_on_exit(self) -> bool:
        page = self._settings_page_with_draft()
        if page is None:
            return True
        reply = QMessageBox.question(
            self,
            tr("มีการแก้ไขที่ยังไม่ได้บันทึก", "There are unsaved changes"),
            tr(
                "หากออกจากโปรแกรมตอนนี้ การแก้ไขใน Settings จะหายไป ต้องการละทิ้งและออกจากโปรแกรมหรือไม่?",
                "If you exit now, the Settings draft will be lost. Discard it and exit?",
            ),
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Discard:
            return False
        discard = getattr(page, "discard_unsaved_changes", None)
        if callable(discard):
            discard()
        return True

    def _exit_application(self):
        if not self._confirm_discard_settings_on_exit():
            return
        self._quitting = True
        hide_tray = getattr(self.tray, "hide", None)
        if callable(hide_tray):
            hide_tray()
        self.polling.stop()
        self.registration.stop()
        self.web_service.stop()
        QApplication.instance().quit()

    def closeEvent(self, event: QCloseEvent):
        close_to_tray = get_cfg("close_to_tray", "1") != "0"
        if self._quitting or not close_to_tray or not QSystemTrayIcon.isSystemTrayAvailable():
            if not self._quitting and not self._confirm_discard_settings_on_exit():
                event.ignore()
                return
            self._quitting = True
            hide_tray = getattr(self.tray, "hide", None)
            if callable(hide_tray):
                hide_tray()
            self.polling.stop()
            self.registration.stop()
            self.web_service.stop()
            event.accept()
            return
        self.hide()
        self.tray.showMessage(
            "KOMI Report V5",
            "โปรแกรมยังอ่าน Meter อยู่ใน System Tray",
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )
        event.ignore()

    # ──────────────────────────────────────────────────────
    # NAVIGATION — สลับหน้าที่แสดงใน QStackedWidget
    # ──────────────────────────────────────────────────────
    def _nav(self, clicked_btn: NavButton):
        # หา index ของปุ่มที่กด — ต้องตรงกับ index ของหน้าใน stack
        # (nav_btns[0] = Overview = stack index 0, และต่อไป)
        idx = self.nav_btns.index(clicked_btn)

        if (
            self.stack.currentIndex() == self._settings_index
            and idx != self._settings_index
            and not self._confirm_leave_settings()
        ):
            return

        is_deferred = idx in self._deferred_pages

        # Switch to the existing lightweight host first so Qt can paint the
        # navigation response immediately. Expensive page construction then
        # happens on the next event-loop turn instead of freezing the old tab.
        for b in self.nav_btns:
            b.set_active(False)
        clicked_btn.set_active(True)
        self.stack.setCurrentIndex(idx)
        if is_deferred:
            QTimer.singleShot(0, lambda index=idx: self._finish_deferred_navigation(index))
            return
        if self._ui_ready:
            self._refresh_visible_page()

    def _finish_deferred_navigation(self, index: int) -> None:
        self._load_deferred_page(index)
        if self.stack.currentIndex() == index and self._ui_ready:
            self._refresh_visible_page()

    def _schedule_refresh_all(self) -> None:
        """Debounce bursts of polling signals before querying and redrawing."""
        self._refresh_timer.start()

    def _refresh_visible_page(self) -> None:
        """Refresh a stale page only when it is actually visible."""
        index = self.stack.currentIndex()
        if index not in self._dirty_pages:
            return
        page = self._page_widgets[index]
        refresh_visible = getattr(page, "refresh_visible", None)
        if callable(refresh_visible):
            apply_language(page)
            self._dirty_pages.discard(index)
            QTimer.singleShot(0, refresh_visible)
            return
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()
        apply_language(page)
        self._dirty_pages.discard(index)

    # ──────────────────────────────────────────────────────
    # REFRESH ALL — โหลดข้อมูลใหม่จาก DB แล้วอัปเดตทุกหน้า
    # เรียกเมื่อ: (1) เปิดโปรแกรม  (2) import ไฟล์ใหม่  (3) เปลี่ยน settings
    # ──────────────────────────────────────────────────────
    def _refresh_all(self):
        # วนทั้ง 3 slot (เครื่องพิมพ์ 3 เครื่อง)
        for i in range(3):
            # get_last_two(slot) — ดึงข้อมูล 2 record ล่าสุดจาก DB
            # curr = record ล่าสุด, prev = record ก่อนหน้า
            curr, prev = get_last_two(i)
            # compute_diff คำนวณส่วนต่าง (เช่น พิมพ์เพิ่มขึ้นกี่แผ่นในรอบนี้)
            # ถ้าไม่มีข้อมูลเลย (curr = None) → diff = None
            diff = compute_diff(prev, curr) if curr else None
            self._data[i] = (curr, prev, diff)

        # แจ้งแต่ละหน้าให้ดึง _data ใหม่และวาด UI ใหม่
        # หมายเหตุ: pg_settings ไม่ต้อง refresh เพราะแสดงข้อมูล config ไม่ใช่ readings
        # Hidden reports are expensive to rebuild and do not need immediate
        # painting. Mark data-driven pages stale, then update only the page the
        # user can currently see. Navigation refreshes the others on demand.
        self._dirty_pages.update(range(len(self._page_widgets)))
        self._refresh_visible_page()
        # อัปเดตข้อความด้านล่าง sidebar ให้แสดงวันที่ล่าสุดของข้อมูลในฐานข้อมูล
        _latest = get_latest_read_date()
        if _latest:
            try:
                _dt = datetime.strptime(_latest, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    _dt = datetime.strptime(_latest, "%Y-%m-%d")
                except ValueError:
                    _dt = None
            if _dt:
                _thai_months = {1:"ม.ค.",2:"ก.พ.",3:"มี.ค.",4:"เม.ย.",5:"พ.ค.",6:"มิ.ย.",
                                7:"ก.ค.",8:"ส.ค.",9:"ก.ย.",10:"ต.ค.",11:"พ.ย.",12:"ธ.ค."}
                _date_str = (
                    f"{_dt.day} {_thai_months[_dt.month]} {_dt.year + 543} "
                    f"{_dt:%H:%M} น."
                )
                self.status_lbl.setText(f"{tr('อ่านล่าสุด', 'Last read')}\n{_date_str}")
            else:
                self.status_lbl.setText(f"{tr('อ่านล่าสุด', 'Last read')}\n{_latest}")
        else:
            self.status_lbl.setText(
                tr("ยังไม่มีประวัติการอ่าน", "No reading history yet")
            )
        if self._background_started:
            eligible, _reason = self._registration_usage_eligibility()
            if not eligible:
                self._apply_registration_collection_gate()


# ══════════════════════════════════════════════════════════
# PARSER DROP ZONE — Drag & Drop zone สำหรับนำเข้า Parser
# ══════════════════════════════════════════════════════════
from PyQt6.QtCore import pyqtSignal as _pyqtSignal
from PyQt6.QtGui import QDragEnterEvent as _DragEnterEvent
from PyQt6.QtGui import QDropEvent as _DropEvent


class _ParserDropZone(QFrame):
    """Drag & Drop zone สำหรับนำเข้า Parser Profile (.json) — รูปสี่เหลี่ยมจตุรัส"""
    file_dropped = _pyqtSignal(str)

    _STYLE_IDLE = (
        "QFrame#parser_drop_zone {"
        " background: #F8FAFC;"
        " border: 2px dashed #94A3B8;"
        " border-radius: 14px;"
        "}"
    )
    _STYLE_HOVER = (
        "QFrame#parser_drop_zone {"
        " background: #EFF6FF;"
        " border: 2px dashed #2563EB;"
        " border-radius: 14px;"
        "}"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("parser_drop_zone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._STYLE_IDLE)
        self.setFixedHeight(180)

        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(10)

        self._icon_lbl = QLabel("📥")
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setStyleSheet("font-size:44px; background:transparent; border:none;")
        lay.addWidget(self._icon_lbl)

        self._line1 = QLabel("คลิกหรือลากไฟล์ .json มาวาง")
        self._line1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._line1.setFont(fnt(F_MD, bold=True))
        self._line1.setStyleSheet(f"color:{C_TEXT}; background:transparent; border:none;")
        lay.addWidget(self._line1)

        self._line2 = QLabel("Parser Profile")
        self._line2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._line2.setStyleSheet(f"color:{C_TEXT2}; font-size:{F_SM}pt; background:transparent; border:none;")
        lay.addWidget(self._line2)

    def dragEnterEvent(self, e: _DragEnterEvent):
        if e.mimeData().hasUrls():
            if any(u.toLocalFile().lower().endswith(".json") for u in e.mimeData().urls()):
                e.acceptProposedAction()
                self.setStyleSheet(self._STYLE_HOVER)
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        self.setStyleSheet(self._STYLE_IDLE)

    def dropEvent(self, e: _DropEvent):
        self.setStyleSheet(self._STYLE_IDLE)
        for url in e.mimeData().urls():
            fp = url.toLocalFile()
            if fp.lower().endswith(".json"):
                self.file_dropped.emit(fp)
                return
        e.ignore()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            from pathlib import Path as _P
            path, _ = QFileDialog.getOpenFileName(
                self, "นำเข้า Parser Profile (.json)",
                str(_P.home()), "JSON Files (*.json);;All Files (*)"
            )
            if path:
                self.file_dropped.emit(path)
        super().mousePressEvent(e)

    def set_success(self, text: str):
        """อัปเดต UI เมื่อนำเข้าสำเร็จ"""
        self._icon_lbl.setText("✅")
        self._line1.setText(text)
        self._line1.setStyleSheet("color:#16A34A; font-weight:600; background:transparent; border:none;")
        self._line2.setText("คลิกหรือลากไฟล์ใหม่เพื่อเปลี่ยน")


# ══════════════════════════════════════════════════════════
# SETUP WIZARD — ตั้งค่าเริ่มต้นแบบ 3 ขั้นตอน
# แสดงเมื่อยังไม่มีฐานข้อมูลหรือยังไม่มี Parser Profile
# ══════════════════════════════════════════════════════════
class SetupWizard(QDialog):
    """
    Wizard 3 ขั้นตอนสำหรับการตั้งค่าครั้งแรก:
      Step 1: นำเข้า Parser + เลือก Parser + ชื่อเครื่อง
      Step 2: ตั้งค่าราคาพิมพ์ต่อแผ่น (หรือต่อเมตรสำหรับ Label)
      Step 3: % กระดาษเสีย + วันตัดรอบบิล
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ตั้งค่าเริ่มต้น")
        self.setFixedWidth(560)
        self.setMinimumHeight(480)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setStyleSheet(build_qss())

        self._step = 0
        self._imported_profiles: list = []
        self._parser_combos: list = []
        self._name_edits: list = []
        self._price_spins: dict = {0: {}, 1: {}, 2: {}}
        self._spin_waste = None
        self._spin_day = None
        self._step2_content = None

        self._build()

    # ── ตัวบ่งชี้ขั้นตอนที่ด้านบน ──────────────────────────
    def _build_step_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(76)
        bar.setStyleSheet(f"background:{C_SIDEBAR}; border:none;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 10, 0, 10)
        lay.setSpacing(0)

        self._step_dots = []
        self._step_lbls = []
        steps = ["1  นำเข้า Parser", "2  ตั้งค่าราคา", "3  ตั้งค่าอื่นๆ"]

        lay.addStretch(1)
        for i, text in enumerate(steps):
            if i > 0:
                sep = QLabel("━━━")
                sep.setStyleSheet("color:rgba(255,255,255,0.25); background:transparent; padding:0 4px;")
                sep.setFont(fnt(F_XS))
                lay.addWidget(sep)

            col = QWidget()
            col.setStyleSheet("background:transparent;")
            vb = QVBoxLayout(col)
            vb.setContentsMargins(0, 0, 0, 0)
            vb.setSpacing(3)

            dot = QLabel(str(i + 1))
            dot.setFixedSize(28, 28)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setFont(fnt(F_SM, bold=True))

            lbl = QLabel(text)
            lbl.setFont(fnt(7))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            self._step_dots.append(dot)
            self._step_lbls.append(lbl)
            vb.addWidget(dot, 0, Qt.AlignmentFlag.AlignHCenter)
            vb.addWidget(lbl)
            lay.addWidget(col)

        lay.addStretch(1)
        self._refresh_step_bar()
        return bar

    def _refresh_step_bar(self):
        for i, (dot, lbl) in enumerate(zip(self._step_dots, self._step_lbls)):
            if i == self._step:
                dot.setStyleSheet(
                    "background:#2563EB; color:white; border-radius:14px; font-weight:700;"
                )
                lbl.setStyleSheet("color:white; background:transparent;")
            elif i < self._step:
                dot.setStyleSheet(
                    "background:#16A34A; color:white; border-radius:14px;"
                )
                lbl.setStyleSheet("color:rgba(255,255,255,0.65); background:transparent;")
            else:
                dot.setStyleSheet(
                    "background:rgba(255,255,255,0.12); color:rgba(255,255,255,0.35); border-radius:14px;"
                )
                lbl.setStyleSheet("color:rgba(255,255,255,0.30); background:transparent;")

    # ── โครงสร้างหลัก ──────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_step_bar())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_page1())
        self.stack.addWidget(self._build_page2_container())
        self.stack.addWidget(self._build_page3())
        root.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        nav.setContentsMargins(24, 10, 24, 18)
        nav.setSpacing(10)

        self.btn_back = QPushButton("← ย้อนกลับ")
        self.btn_back.setFont(fnt(F_MD))
        self.btn_back.setFixedHeight(38)
        self.btn_back.setVisible(False)
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.setStyleSheet(
            f"QPushButton {{background:{C_BORDER}; color:{C_TEXT2}; border:none;"
            f" border-radius:8px; padding:6px 20px;}}"
            f"QPushButton:hover {{background:#d0d0d0;}}"
        )
        self.btn_back.clicked.connect(self._go_back)

        self.btn_next = QPushButton("ถัดไป  →")
        self.btn_next.setFont(fnt(F_MD, bold=True))
        self.btn_next.setFixedHeight(38)
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next.setStyleSheet(
            f"QPushButton {{background:{C_ACCENT}; color:white; border:none;"
            f" border-radius:8px; padding:6px 24px;}}"
            f"QPushButton:hover {{background:#1E3A8A;}}"
        )
        self.btn_next.clicked.connect(self._go_next)

        nav.addWidget(self.btn_back)
        nav.addStretch()
        nav.addWidget(self.btn_next)
        root.addLayout(nav)

    # ── Step 1: นำเข้า Parser + ชื่อเครื่อง ────────────────
    def _build_page1(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 18, 28, 10)
        lay.setSpacing(10)

        title = QLabel("นำเข้า Parser และตั้งชื่อเครื่องพิมพ์")
        title.setFont(fnt(F_LG, bold=True))
        title.setStyleSheet(f"color:{C_TEXT};")
        lay.addWidget(title)

        sub = QLabel("นำเข้าไฟล์ Parser (.json) เพื่อเพิ่ม/อัปเดตตัวเลือก แล้วเลือกกำหนดให้แต่ละเครื่อง")
        sub.setFont(fnt(F_SM))
        sub.setStyleSheet(f"color:{C_TEXT2};")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        self._drop_zone = _ParserDropZone()
        self._drop_zone.setFixedHeight(130)
        self._drop_zone.file_dropped.connect(self._load_parser_file)
        lay.addWidget(self._drop_zone)

        self._parser_combos = []
        self._name_edits = []
        combo_style = (
            f"QComboBox {{background:white; border:1px solid {C_BORDER};"
            f" border-radius:6px; padding:3px 6px; color:{C_TEXT}; font-size:{F_SM}pt;}}"
            "QComboBox::drop-down {border:none;}"
        )
        for i in range(3):
            row = QFrame()
            row.setStyleSheet(
                f"QFrame {{background:{SLOT_LIGHT[i]}; border-radius:8px;"
                f" border:1px solid {SLOT_COLORS[i]}33;}}"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 7, 10, 7)
            rl.setSpacing(6)

            dot = QLabel("●")
            dot.setStyleSheet(f"color:{SLOT_COLORS[i]}; background:transparent; border:none; font-size:10px;")
            dot.setFixedWidth(12)
            rl.addWidget(dot)

            num_lbl = QLabel(f"เครื่อง {i+1}")
            num_lbl.setFont(fnt(F_SM, bold=True))
            num_lbl.setStyleSheet(f"color:{C_TEXT}; background:transparent; border:none;")
            num_lbl.setFixedWidth(52)
            rl.addWidget(num_lbl)

            name_edit = QLineEdit(get_cfg(f"machine_name_{i}", SLOT_NAMES[i]))
            name_edit.setFont(fnt(F_SM))
            name_edit.setFixedWidth(120)
            name_edit.setPlaceholderText("ชื่อเครื่อง")
            rl.addWidget(name_edit)
            self._name_edits.append(name_edit)

            p_lbl = QLabel("Parser:")
            p_lbl.setFont(fnt(F_SM))
            p_lbl.setStyleSheet(f"color:{C_TEXT2}; background:transparent; border:none;")
            rl.addWidget(p_lbl)

            combo = QComboBox()
            combo.setFont(fnt(F_SM))
            combo.addItem("(ไม่กำหนด)", None)
            # ไม่ pre-populate จาก disk — แสดงเฉพาะ profiles ที่ import ในช่วง wizard นี้
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            combo.setStyleSheet(combo_style)
            rl.addWidget(combo, 1)
            self._parser_combos.append(combo)

            lay.addWidget(row)

        lay.addStretch()
        return w

    # ── Step 2: ราคาพิมพ์ (container + scroll) ─────────────
    def _build_page2_container(self) -> QWidget:
        w = QWidget()
        vb = QVBoxLayout(w)
        vb.setContentsMargins(20, 14, 20, 8)
        vb.setSpacing(8)

        title = QLabel("ตั้งค่าราคาพิมพ์ต่อแผ่น (บาท)")
        title.setFont(fnt(F_MD, bold=True))
        title.setStyleSheet(f"color:{C_TEXT};")
        vb.addWidget(title)

        sub = QLabel("A4/A3 สี/ขาวดำ — หรือราคาต่อเมตรสำหรับเครื่อง Label")
        sub.setFont(fnt(F_XS))
        sub.setStyleSheet(f"color:{C_TEXT2};")
        vb.addWidget(sub)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        vb.addWidget(self._scroll_area, 1)

        self._page2_vb = vb
        return w

    def _rebuild_page2_content(self):
        """สร้างเนื้อหา Step 2 ใหม่ตาม parser ที่เลือกไว้ใน Step 1"""
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(2, 4, 2, 4)
        cl.setSpacing(10)

        self._price_spins = {0: {}, 1: {}, 2: {}}

        # spin style ร่วม
        spin_style = (
            f"QDoubleSpinBox {{background:white; border:1px solid {C_BORDER};"
            f" border-radius:5px; padding:2px 6px; font-size:{F_SM}pt;}}"
        )

        for slot in range(3):
            is_label = self._is_label_parser(slot)
            mname = (self._name_edits[slot].text().strip()
                     if self._name_edits else SLOT_NAMES[slot]) or f"เครื่อง {slot+1}"

            sec = QFrame()
            sec.setStyleSheet(
                f"QFrame {{background:{SLOT_LIGHT[slot]}; border-radius:8px;"
                f" border:1px solid {SLOT_COLORS[slot]}33;}}"
            )
            sl = QVBoxLayout(sec)
            sl.setContentsMargins(12, 8, 12, 10)
            sl.setSpacing(6)

            # ── หัวข้อ ───────────────────────────────────────
            hrow = QHBoxLayout()
            hrow.setSpacing(6)
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{SLOT_COLORS[slot]}; background:transparent; border:none; font-size:9px;")
            dot.setFixedWidth(12)
            name_lbl = QLabel(mname)
            name_lbl.setFont(fnt(F_SM, bold=True))
            name_lbl.setStyleSheet(f"color:{SLOT_COLORS[slot]}; background:transparent; border:none;")
            hrow.addWidget(dot)
            hrow.addWidget(name_lbl)
            hrow.addStretch()
            if is_label:
                badge = QLabel("Label")
                badge.setFont(fnt(6, bold=True))
                badge.setStyleSheet("background:#8B5CF6; color:white; border-radius:4px; padding:1px 5px; border:none;")
                hrow.addWidget(badge)
            sl.addLayout(hrow)

            # ── ตาราง 2 คอลัมน์ (label + spin) × 2 แถว ────
            # ขนาด: lbl=80px + spin=148px = 228px/col × 2 + gap(8) = 464px < 500px ✓
            specs = ([
                ("color_meter", "สี (บาท/เมตร)", C_ACCENT),
                ("bw_meter",    "ขาวดำ (บาท/เมตร)", C_TEXT2),
            ] if is_label else [
                ("a4_color", "A4 สี",    C_ACCENT),
                ("a4_bw",    "A4 ขาวดำ", C_TEXT2),
                ("a3_color", "A3 สี",    C_ORANGE),
                ("a3_bw",    "A3 ขาวดำ", C_PURPLE),
            ])

            grid = QGridLayout()
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(5)
            cols = 2 if len(specs) == 4 else 1
            suffix = " บาท/เมตร" if is_label else " บาท/แผ่น"
            for r, (key, label, color) in enumerate(specs):
                lbl = QLabel(f"{label} :")
                lbl.setFont(fnt(F_SM))
                lbl.setStyleSheet(f"color:{color}; background:transparent; border:none;")
                lbl.setFixedWidth(80)

                spin = QDoubleSpinBox()
                spin.setRange(0, 9999)
                spin.setDecimals(2)
                spin.setSuffix(suffix)
                spin.setValue(get_price(key, slot))
                spin.setFont(fnt(F_SM))
                spin.setFixedWidth(148)
                spin.setFixedHeight(28)
                spin.setStyleSheet(spin_style)

                row_i, col_i = divmod(r, cols)
                grid.addWidget(lbl, row_i, col_i * 2)
                grid.addWidget(spin, row_i, col_i * 2 + 1)
                self._price_spins[slot][key] = spin

            sl.addLayout(grid)
            cl.addWidget(sec)

        cl.addStretch()
        self._scroll_area.setWidget(content)

    def _is_label_parser(self, slot: int) -> bool:
        if not self._parser_combos:
            return False
        data = self._parser_combos[slot].currentData()
        if data is None:
            return False
        if isinstance(data, dict):
            return "label" in data.get("types", [])
        try:
            from tools.check_parser import load_profiles as _lp
            prof = next((p for p in _lp() if p.get("slot") == int(data)), None)
            return bool(prof and "label" in prof.get("types", []))
        except Exception:
            return False

    # ── Step 3: กระดาษเสีย + วันตัดรอบ ──────────────────────
    def _build_page3(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 18, 28, 10)
        lay.setSpacing(16)

        title = QLabel("ตั้งค่าเพิ่มเติม")
        title.setFont(fnt(F_LG, bold=True))
        title.setStyleSheet(f"color:{C_TEXT};")
        lay.addWidget(title)

        # ── % กระดาษเสีย ──────────────────────────────────
        c_waste = QFrame()
        c_waste.setStyleSheet(
            f"QFrame {{background:#F8FAFC; border-radius:10px; border:1px solid {C_BORDER};}}"
        )
        wl = QVBoxLayout(c_waste)
        wl.setContentsMargins(16, 14, 16, 14)
        wl.setSpacing(10)

        wh = QLabel("📄  % กระดาษเสีย (Waste Paper)")
        wh.setFont(fnt(F_MD, bold=True))
        wh.setStyleSheet(f"color:{C_TEXT}; background:transparent; border:none;")
        wl.addWidget(wh)

        wr = QHBoxLayout()
        lb_w = QLabel("% กระดาษเสีย :")
        lb_w.setFont(fnt(F_LG))
        lb_w.setFixedWidth(140)
        self._spin_waste = QDoubleSpinBox()
        self._spin_waste.setRange(0, 100)
        self._spin_waste.setDecimals(1)
        self._spin_waste.setSuffix(" %")
        self._spin_waste.setValue(get_waste_paper_pct())
        self._spin_waste.setFont(fnt(F_LG))
        self._spin_waste.setFixedWidth(160)
        wr.addWidget(lb_w)
        wr.addWidget(self._spin_waste)
        wr.addStretch()
        wl.addLayout(wr)

        hint_w = QLabel("ใช้หักค่าใช้จ่ายกระดาษเสียในรายงานรายเดือน")
        hint_w.setFont(fnt(F_XS))
        hint_w.setStyleSheet(f"color:{C_TEXT3}; background:transparent; border:none;")
        wl.addWidget(hint_w)
        lay.addWidget(c_waste)

        # ── วันตัดรอบบิล ───────────────────────────────────
        c_day = QFrame()
        c_day.setStyleSheet(
            f"QFrame {{background:#F8FAFC; border-radius:10px; border:1px solid {C_BORDER};}}"
        )
        dl = QVBoxLayout(c_day)
        dl.setContentsMargins(16, 14, 16, 14)
        dl.setSpacing(10)

        dh = QLabel("📅  วันตัดรอบบิล")
        dh.setFont(fnt(F_MD, bold=True))
        dh.setStyleSheet(f"color:{C_TEXT}; background:transparent; border:none;")
        dl.addWidget(dh)

        dr = QHBoxLayout()
        lb_d = QLabel("วันตัดรอบ :")
        lb_d.setFont(fnt(F_LG))
        lb_d.setFixedWidth(130)
        self._spin_day = QSpinBox()
        self._spin_day.setRange(1, 31)
        self._spin_day.setValue(get_billing_day())
        self._spin_day.setSuffix(" ของเดือน")
        self._spin_day.setFont(fnt(F_LG))
        self._spin_day.setFixedWidth(180)
        dr.addWidget(lb_d)
        dr.addWidget(self._spin_day)
        dr.addStretch()
        dl.addLayout(dr)

        hint_d = QLabel("เช่น ตั้งวัน 25 → ไฟล์ที่อ่านวันที่ 1-25 นับเป็นเดือนนั้น, หลัง 25 นับเป็นเดือนถัดไป")
        hint_d.setFont(fnt(F_XS))
        hint_d.setWordWrap(True)
        hint_d.setStyleSheet(f"color:{C_TEXT3}; background:transparent; border:none;")
        dl.addWidget(hint_d)
        lay.addWidget(c_day)

        lay.addStretch()
        return w

    # ── โหลด Parser จากไฟล์ ────────────────────────────────
    def _load_parser_file(self, path: str):
        from pathlib import Path as _P
        try:
            profiles = validate_parser_json(path)
        except Exception as exc:
            QMessageBox.critical(self, "โหลดไฟล์ไม่ได้", str(exc))
            return

        # เพิ่มเฉพาะ profiles ใหม่ที่ยังไม่มีในรายการ (ตรวจสอบจากชื่อ)
        added_first_combo = 0
        for ci, combo in enumerate(self._parser_combos):
            combo.blockSignals(True)
            existing_names = {combo.itemText(j) for j in range(combo.count())}
            for p in profiles:
                name = p.get("name", "Parser")
                if name not in existing_names:
                    combo.addItem(name, p)
                    existing_names.add(name)
                    if ci == 0:
                        added_first_combo += 1
            combo.blockSignals(False)

        fname = _P(path).name
        self._drop_zone.set_success(
            f"{fname}  —  พบ {len(profiles)} profiles"
            + (f"  (เพิ่มใหม่ {added_first_combo})" if added_first_combo else "  (ไม่มีใหม่)")
        )

    # ── Navigation ─────────────────────────────────────────
    def _validate_step(self) -> bool:
        """[V4.5] validate ก่อน next แต่ละ step"""
        if self._step == 0:
            # ต้องเลือก parser อย่างน้อย 1 slot
            assigned = sum(1 for c in self._parser_combos if c.currentData() is not None)
            if assigned == 0:
                QMessageBox.warning(self, "ยังไม่ได้ตั้ง Parser",
                                    "กรุณานำเข้าและกำหนด Parser ให้อย่างน้อย 1 เครื่องก่อน")
                return False
            # ชื่อเครื่องห้ามว่างถ้ามีกำหนด parser
            for i, combo in enumerate(self._parser_combos):
                if combo.currentData() is not None:
                    if not self._name_edits[i].text().strip():
                        QMessageBox.warning(self, "ชื่อเครื่องว่าง",
                                            f"กรุณาตั้งชื่อเครื่อง {i+1}")
                        return False
        return True

    def _go_next(self):
        if not self._validate_step():
            return
        if self._step == 0:
            self._rebuild_page2_content()
            self._step = 1
            self.stack.setCurrentIndex(1)
            self.btn_back.setVisible(True)
            self.btn_next.setText("ถัดไป  →")
        elif self._step == 1:
            self._step = 2
            self.stack.setCurrentIndex(2)
            self.btn_next.setText("💾  บันทึก")
        elif self._step == 2:
            self._do_save()
        self._refresh_step_bar()

    def _go_back(self):
        if self._step > 0:
            self._step -= 1
            self.stack.setCurrentIndex(self._step)
            if self._step == 0:
                self.btn_back.setVisible(False)
            self.btn_next.setText("ถัดไป  →" if self._step < 2 else "💾  บันทึก")
        self._refresh_step_bar()

    # ── บันทึกค่าทั้งหมด ──────────────────────────────────
    def _do_save(self):
        from tools.check_parser import _empty_profile, load_profiles, save_profiles

        try:
            existing = load_profiles()
        except Exception:
            existing = [_empty_profile(i + 1) for i in range(3)]
        profiles_by_slot = {p.get("slot", i + 1): p for i, p in enumerate(existing)}

        # บันทึกชื่อเครื่อง
        for i, edit in enumerate(self._name_edits):
            name = edit.text().strip()
            if name:
                set_cfg(f"machine_name_{i}", name)

        # บันทึก parser assignment + profiles
        # ถ้าผู้ใช้เลือก parser เดียวกันให้หลายเครื่อง — บันทึก parser ครั้งเดียวแล้วชี้ทุกเครื่องไปที่ slot เดียว
        next_slot = max(profiles_by_slot.keys(), default=0) + 1
        dict_to_slot: dict = {}  # id(dict) → slot ที่บันทึกแล้ว
        for i, combo in enumerate(self._parser_combos):
            profile_data = combo.currentData()
            if profile_data is None:
                continue
            if isinstance(profile_data, dict):
                key = id(profile_data)
                if key in dict_to_slot:
                    slot_num = dict_to_slot[key]
                else:
                    slot_num = next_slot
                    next_slot += 1
                    profile = {**_empty_profile(slot_num), **profile_data, "slot": slot_num}
                    profiles_by_slot[slot_num] = profile
                    dict_to_slot[key] = slot_num
                set_cfg(f"parser_{i}", str(slot_num))
            else:
                set_cfg(f"parser_{i}", str(profile_data))

        try:
            save_profiles([profiles_by_slot[s] for s in sorted(profiles_by_slot)])
        except Exception as exc:
            QMessageBox.warning(self, "บันทึก Parser ไม่ได้", str(exc))

        # บันทึกราคา
        for slot, spin_dict in self._price_spins.items():
            for key, spin in spin_dict.items():
                set_cfg(f"price_{slot}_{key}", str(round(spin.value(), 2)))

        # บันทึก % กระดาษเสีย + วันตัดรอบ
        if self._spin_waste:
            set_cfg("waste_paper_pct", str(round(self._spin_waste.value(), 1)))
        if self._spin_day:
            set_cfg("billing_day", str(self._spin_day.value()))

        self.accept()


def _check_parser_setup(parent_win, splash=None):
    """
    [V4.5] ตรวจสอบและบังคับให้ผ่าน setup wizard ก่อนใช้งานได้
    - DB ถูกสร้างใหม่ในรอบนี้ (fresh install)  OR
    - ยังไม่มี Parser Profile ที่ตั้งค่าแล้ว
    คืน True ถ้าพร้อมใช้งาน, False ถ้าผู้ใช้ปิด wizard โดยไม่ตั้งค่า
    """
    from tools.check_parser import load_profiles
    profiles = load_profiles()
    has_parser = any(p.get("column_map") for p in profiles)
    fresh_db = getattr(parent_win, "_is_fresh_db", False)

    if fresh_db or not has_parser:
        # ปิด splash ก่อนเปิด wizard — splash ตั้ง WindowStaysOnTopHint ไว้ จะบัง wizard ถ้ายังเปิดอยู่
        if splash is not None:
            splash.close()
        dlg = SetupWizard(parent_win)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        result = dlg.exec()
        # หลัง wizard ปิด ตรวจอีกครั้งว่ามี parser หรือยัง
        profiles = load_profiles()
        has_parser = any(p.get("column_map") for p in profiles)
        if not has_parser:
            QMessageBox.warning(
                parent_win,
                "ยังไม่ได้ตั้งค่า Parser",
                "โปรแกรมจะใช้งาน import ไฟล์ไม่ได้จนกว่าจะมีการตั้งค่า Parser\n"
                "ท่านสามารถตั้งค่าได้ที่หน้า Settings ภายหลัง"
            )
            return False
    return True


_active_v5_setup_dialog: SetupWizardV5 | None = None


def _v5_setup_is_complete(
    repository: DeviceConfigRepository | None = None,
    registration_runtime=None,
) -> bool:
    repository = repository or DeviceConfigRepository()
    local_setup_complete = repository.setup_complete() and bool(
        (get_cfg("company_name", "") or "").strip()
    )
    # Registration eligibility controls new device reads, not whether a
    # configured installation may open its local Report/User/Usage history.
    # In particular, a Host deactivation must never restart first-run setup.
    del registration_runtime
    return local_setup_complete


def _finish_v5_first_setup(
    repository: DeviceConfigRepository | None = None,
    registration_runtime=None,
) -> bool:
    """Validate persisted setup and apply one-time post-setup integration."""
    repository = repository or DeviceConfigRepository()
    complete = _v5_setup_is_complete(repository, registration_runtime)
    if not complete:
        return False
    # First setup is an explicit user action. Register the default background
    # startup here once; normal launches must remain read-only.
    enabled = get_cfg("autostart_enabled", "1") != "0"
    try:
        configure_autostart(enabled, apply=True)
    except OSError:
        log.exception("cannot register background autostart after first setup")
    # Web is on by default only after the user completes first setup.
    set_cfg("web_service_enabled", "1")
    try:
        result = create_desktop_shortcuts()
        log.info("created first-setup shortcuts: %s", result.created_paths)
    except Exception:
        log.exception("cannot create Desktop shortcuts after first setup")
    return True


def _open_v5_setup(
    parent_win,
    *,
    splash=None,
    on_complete,
    on_cancel,
) -> SetupWizardV5:
    """Open first-run setup without a nested QDialog event loop."""
    global _active_v5_setup_dialog
    repository = DeviceConfigRepository()
    if splash is not None:
        splash.close()
    # A parented QDialog.open() becomes a macOS sheet.  Because MainWindow is
    # maximized, that made first-run setup look like a smaller page floating
    # inside a second full-screen window.  First-run setup is its own window;
    # retain it globally and keep it application-modal instead.
    dialog = SetupWizardV5(
        None,
        registration_runtime=getattr(parent_win, "registration", None),
        offline_license_public_keys=getattr(
            parent_win, "offline_license_public_keys", None
        ),
    )
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    _active_v5_setup_dialog = dialog

    def setup_finished(result: int) -> None:
        if (
            result == int(QDialog.DialogCode.Accepted)
            and _finish_v5_first_setup(
                repository,
                getattr(parent_win, "registration", None),
            )
        ):
            on_complete()
            return
        on_cancel()

    dialog.finished.connect(setup_finished)
    dialog.open()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


def _check_v5_setup(parent_win=None, splash=None) -> bool:
    """Read-only setup gate retained for existing installations and tests."""
    del splash
    return _v5_setup_is_complete(
        registration_runtime=getattr(parent_win, "registration", None),
    )


def _setup_logging():
    """ตั้งค่า structured logging ที่ runtime log directory."""
    from observability import configure_logging
    try:
        configure_logging()
    except Exception as e:
        print(f"warning: cannot setup logging: {e}", file=sys.stderr)


def _install_excepthook():
    """[V4.5] จับ unhandled exception → log + แสดง dialog"""
    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.critical("UNHANDLED EXCEPTION",
                     exc_info=(exc_type, exc_value, exc_tb))
        try:
            QMessageBox.critical(
                None,
                "เกิดข้อผิดพลาด",
                f"{exc_type.__name__}: {exc_value}\n\n"
                f"บันทึกรายละเอียดไว้ที่ ~/KOMI Report V5/logs/"
            )
        except Exception:
            pass
    sys.excepthook = _hook


# ══════════════════════════════════════════════════════════
# ENTRY POINT — จุดเริ่มต้นของโปรแกรม
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    # [V4.5] setup logging + crash handler ก่อนทุกอย่าง
    _setup_logging()
    log.info("=" * 60)
    log.info("KOMI Report V%s starting", APP_VER)

    # Windows requires the process AppUserModelID before any UI is presented.
    # Otherwise source/runtime launches are branded as the pythonw.exe host.
    configure_windows_process_identity()

    # QApplication ต้องสร้างก่อนสิ่งอื่นใดทั้งหมด
    app = QApplication(sys.argv)
    configure_qt_application_identity(app, version=APP_VER)
    install_button_system(app)
    instance_guard = SingleInstanceGuard(Path(get_db_path()).with_suffix(".instance.lock"))
    if not instance_guard.acquire():
        log.warning("another KOMI Report V5 instance is already running")
        sys.exit(0)
    _install_excepthook()

    # กำหนดฟอนต์ default ให้ทุก widget ที่ไม่ได้ set font เอง
    app.setFont(QFont(DEFAULT_FONT_NAME, DEFAULT_FONT_SIZE))

    # เปิดใช้ High DPI icon ถ้า Qt version นั้นรองรับ
    try:
        app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)
    except AttributeError:
        pass

    # แสดง Splash Screen ทันที ก่อนโหลด DB / UI
    splash = SplashScreen()
    splash.show()
    app.processEvents()  # บังคับให้หน้าต่าง splash วาดตัวเองขึ้นมาก่อน

    win = MainWindow(splash=splash)
    instance_guard.activation_requested.connect(win._show_from_tray)

    # Packaging smoke test: construct the complete startup shell against an
    # isolated KOMI_DB_PATH, then exit before setup dialogs or network services.
    if "--smoke-test" in sys.argv:
        splash.close()
        win._quitting = True
        win.close()
        instance_guard.release()
        sys.exit(0)

    def show_configured_application() -> None:
        # V5.2.6 performance: first paint wins. Keep the exact same startup
        # services and data refresh, but let Qt present the workspace before
        # synchronous local refresh and service orchestration compete for the
        # UI thread. Background launches remain hidden as before.
        splash.close()
        if "--background" in sys.argv:
            win.hide()
        else:
            win._show_main_window()

        def finish_startup() -> None:
            if getattr(win, "_startup_refresh_pending", False):
                win._startup_refresh_pending = False
                win._refresh_all()
            win.start_background_services()

        QTimer.singleShot(0, finish_startup)

    def cancel_first_setup() -> None:
        splash.close()
        win._quitting = True
        win.close()
        app.quit()

    # Open first-run setup on QApplication's main event loop. QDialog.exec()
    # creates a nested loop and has repeatedly crashed inside macOS 27
    # Accessibility hit-testing; QDialog.open() avoids that re-entrancy.
    splash.set_message("ตรวจสอบการตั้งค่า...")
    if _check_v5_setup(win):
        show_configured_application()
    else:
        _open_v5_setup(
            win,
            splash=splash,
            on_complete=show_configured_application,
            on_cancel=cancel_first_setup,
        )

    # app.exec() เริ่ม event loop — โปรแกรมจะอยู่ที่บรรทัดนี้จนกว่าหน้าต่างจะปิด
    log.info("entering main event loop")
    try:
        exit_code = app.exec()
    finally:
        instance_guard.release()
    sys.exit(exit_code)
