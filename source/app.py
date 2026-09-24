# ═══════════════════════════════════════════════════════════
# app.py — หน้าต่างหลัก (Main Window) และจุดเริ่มต้นโปรแกรม
#
# โครงสร้างไฟล์และความรับผิดชอบ:
#   config.py   — สีสัน, ฟอนต์, ค่าคงที่  [แก้ที่นี่เพื่อเปลี่ยนหน้าตาโปรแกรม]
#   database.py — ฐานข้อมูล SQLite + แยก/อ่านข้อมูลจากไฟล์ .txt ของเครื่องพิมพ์
#   widgets.py  — คอมโพเนนต์ UI ที่ใช้ซ้ำได้ (StatCard, buttons, ฯลฯ)
#   ui/         — หน้าจอแยกตามหน้าที่ และ component ที่ใช้ร่วมกัน
#   app.py      — หน้าต่างหลัก, sidebar, entry point ← ไฟล์นี้
#
# ความสัมพันธ์ระหว่างไฟล์:
#   MainWindow → ช่องเก็บข้อมูล _data → ส่งให้หน้
# 
# 
# าต่างอื่นผ่าน lambda
#   ↓ เมื่อนำเข้าข้อมูลใหม่ → _refresh_all() → อัปเดตทุกหน้า
# ═══════════════════════════════════════════════════════════

from ui.styles import shell as shell_styles
from ui.styles import text as text_styles
import json
import logging
import os
import platform
import sys
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
from PyQt6.QtCore import QSize, Qt, QTimer  # ค่าคงที่ของ Qt เช่น alignment, cursor shape
from PyQt6.QtGui import QAction, QCloseEvent, QFont, QPixmap  # QFont = ฟอนต์, QPixmap = รูปภาพ
from PyQt6.QtNetwork import QNetworkInformation
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ui.numeric_inputs import configure_numeric_locale
from config import (
    APP_TITLE,
    APP_VER,
    LOGO_FILENAME,
)
from ui.styles.tokens import (
    DEFAULT_FONT_NAME,
    DEFAULT_FONT_SIZE,
    F_LG,
    F_MD,
    F_SM,
    F_XL,
    F_XS,
    LOGO_MARGIN_BOTTOM,
    LOGO_SCALED_WIDTH,
    NAV_BUTTON_HEIGHT,
    SIDEBAR_MARGIN_BOTTOM,
    SIDEBAR_MARGIN_LEFT,
    SIDEBAR_MARGIN_RIGHT,
    SIDEBAR_MARGIN_TOP,
    SIDEBAR_SPACING,
    SIDEBAR_WIDTH,
    STATUS_PADDING,
    WINDOW_DEFAULT_HEIGHT,
    WINDOW_DEFAULT_WIDTH,
    WINDOW_MIN_WIDTH,
)
from ui.styles.application import build_qss
from database import (  # ฟังก์ชันฐานข้อมูลที่ใช้ที่นี่
    compute_diff,
    get_cfg,
    get_db_path,
    get_last_two,
    init_db,
    set_cfg,
)
from i18n import ENGLISH, THAI, apply_language, get_language, set_language, tr
from ui.pages.imports import PageImport
from ui.pages.overview import PageOverview
from ui.settings.legacy import PageSettings
from services.application_identity import (
    configure_qt_application_identity,
    configure_windows_process_identity,
    configure_windows_window_identity,
    load_application_icon,
)
from services.autostart import configure_autostart, refresh_existing_autostart
from services.background_polling import BackgroundPollingCoordinator
from services.background_agent import stop_running_background_agent
from services.desktop_shortcuts import create_desktop_shortcuts
from services.device_config import DeviceConfigRepository
from services.instance_guard import SingleInstanceGuard
from services.offline_license_keys import (
    OfflineLicensePublicKeyConfigurationError,
    load_offline_license_public_keys,
)
from services.build_edition import is_offline_edition
from services.peer_sync_authorization import ensure_pairing_default, PeerSyncAuthorizationError
from services.v5_2_client import V52ContractClient, V52RuntimeConfig
from services.v5_2_runtime import V52RuntimeCoordinator
from services.web_service import web_service_manager
from ui.button_system import install_button_system
from ui.reports.page import PageHistoryV5
from ui.pages.devices import PageImportV5
from ui.settings.page import PageSettingsV5
from ui.setup.wizard import SetupWizardV5
from widgets import fnt  # fnt(size, bold) — สร้าง QFont อย่างสั้น

# หน้าที่ผู้ใช้เปิดได้จาก Sidebar ตามลำดับที่แสดงจริง
SIDEBAR_NAV_ITEMS: tuple[tuple[str, str], ...] = (
    ("▸", "ภาพรวม"),
    ("▸", "อุปกรณ์"),
    ("▸", "รายงาน"),
    ("▸", "ตั้งค่า"),
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
        card.setStyleSheet(shell_styles.splash_screen_card())
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
            logo_lbl.setStyleSheet(text_styles.label('white', font_size='22pt', font_weight='bold'))
        cl.addWidget(logo_lbl)

        # ชื่อโปรแกรม
        title_lbl = QLabel(APP_TITLE)
        title_lbl.setFont(fnt(F_MD, bold=True))
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setStyleSheet(text_styles.label('#ffffff'))
        cl.addWidget(title_lbl)

        # เวอร์ชัน
        ver_lbl = QLabel(f"v{APP_VER}")
        ver_lbl.setFont(fnt(F_XS))
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_lbl.setStyleSheet(text_styles.label('rgba(255,255,255,0.50)'))
        cl.addWidget(ver_lbl)

        cl.addSpacing(14)

        # ข้อความสถานะ — อัปเดตได้ผ่าน set_message()
        self._msg_lbl = QLabel("กำลังเริ่มต้นโปรแกรม...")
        self._msg_lbl.setFont(fnt(F_SM))
        self._msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._msg_lbl.setStyleSheet(text_styles.label('rgba(255,255,255,0.70)'))
        cl.addWidget(self._msg_lbl)

        self._activity = QProgressBar()
        self._activity.setRange(0, 0)
        self._activity.setTextVisible(False)
        self._activity.setFixedHeight(5)
        self._activity.setAccessibleName("กำลังเตรียมโปรแกรม")
        self._activity.setStyleSheet(
            shell_styles.SPLASH_SCREEN_ACTIVITY
        )
        cl.addWidget(self._activity)

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
        self.setWindowIcon(load_application_icon())
        self.setWindowTitle(f"{APP_TITLE} V{APP_VER}")  # ชื่อโปรแกรมบน titlebar
        configure_windows_window_identity(self)
        self._layout_screen = None
        self._screen_signal_connected = False
        self._compact_sidebar = None
        self._fit_to_available_screen(initial=True)

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
            ) if not is_offline_edition() else None,
            parent=self,
        )
        try:
            self.offline_license_public_keys = load_offline_license_public_keys()
        except OfflineLicensePublicKeyConfigurationError:
            log.exception("Offline License public verification keys are invalid")
            self.offline_license_public_keys = {}

        if splash: splash.set_message("กำลังสร้างหน้าจอ...")
        self._build_ui()  # สร้าง UI ทั้งหมด: sidebar + stack ของหน้าต่างๆ
        self._update_sidebar_layout()
        self._ui_ready = True

        if splash: splash.set_message("กำลังโหลดข้อมูล...")
        self._quitting = False
        self._background_started = False
        self._registration_collection_ready = False
        self._startup_poll_pending = True
        self._startup_poll_timer = QTimer(self)
        self._startup_poll_timer.setSingleShot(True)
        self._startup_poll_timer.timeout.connect(self._run_startup_poll)
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
        self.polling.activity_changed.connect(self._refresh_sidebar_role)
        self.polling.peer_network_runtime.changed.connect(self._refresh_sidebar_role)
        self.polling.peer_history.changed.connect(self._refresh_sidebar_role)
        self.polling.reading_saved.connect(lambda _slot: self._schedule_refresh_all())
        self.polling.reading_saved.connect(self.registration.meter_observed)
        self.polling.shared_settings_applied.connect(self._refresh_all)
        self.polling.shared_settings_applied.connect(self.registration.configuration_changed)
        self.pg_import.sync_requested.connect(self._request_manual_poll)
        self.pg_overview.sync_requested.connect(self._request_manual_poll)
        self._build_tray()
        self.registration.status_changed.connect(self._registration_status_changed)
        self._install_network_recovery_monitor()
        apply_language(self)
        if splash is not None:
            self._prepare_reports_overview(splash)

    def _fit_to_available_screen(self, *, initial: bool = False) -> None:
        """Keep the decorated window inside the current display's work area."""
        screen = self._layout_screen or self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry().size() - self.size()
        # Before the first native show, Qt has not measured the title bar yet.
        if not self.isVisible():
            title_height = self.style().pixelMetric(QStyle.PixelMetric.PM_TitleBarHeight)
            frame.setHeight(max(frame.height(), title_height))
        usable = QSize(
            max(1, available.width() - max(0, frame.width())),
            max(1, available.height() - max(0, frame.height())),
        )
        self.setMinimumSize(min(WINDOW_MIN_WIDTH, usable.width()), min(560, usable.height()))
        if self.isMaximized() or self.isFullScreen():
            return
        requested = QSize(WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT) if initial else self.size()
        self.resize(requested.boundedTo(usable))
        if self.isVisible():
            decorated = self.frameGeometry()
            self.move(
                max(available.left(), min(decorated.left(), available.right() - decorated.width() + 1)),
                max(available.top(), min(decorated.top(), available.bottom() - decorated.height() + 1)),
            )

    def _watch_layout_screen(self, screen) -> None:
        if screen is not self._layout_screen:
            if self._layout_screen is not None:
                try:
                    self._layout_screen.availableGeometryChanged.disconnect(self._screen_workarea_changed)
                except (TypeError, RuntimeError):
                    pass  # The previous screen may already have been disconnected.
            self._layout_screen = screen
            if screen is not None:
                screen.availableGeometryChanged.connect(self._screen_workarea_changed)
        self._fit_to_available_screen()
        if hasattr(self, "sidebar"):
            self._update_sidebar_layout()

    def _screen_workarea_changed(self, _geometry) -> None:
        self._fit_to_available_screen()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not self._screen_signal_connected:
            handle.screenChanged.connect(self._watch_layout_screen)
            self._screen_signal_connected = True
        self._watch_layout_screen(self.screen())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "sidebar"):
            self._update_sidebar_layout()

    def _update_sidebar_layout(self) -> None:
        compact = self.width() <= 1280
        pixel_ratio = self.devicePixelRatioF()
        if compact == self._compact_sidebar and pixel_ratio == getattr(self, "_logo_pixel_ratio", None):
            return
        self._compact_sidebar = compact
        self._logo_pixel_ratio = pixel_ratio
        self.sidebar.setFixedWidth(200 if compact else SIDEBAR_WIDTH)
        icon_width = 44 if compact else LOGO_SCALED_WIDTH
        if not self._sidebar_logo_pixmap.isNull():
            pixels = round(icon_width * pixel_ratio)
            logo = self._sidebar_logo_pixmap.scaled(
                pixels, pixels, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo.setDevicePixelRatio(pixel_ratio)
            self._sidebar_logo_image.setPixmap(logo)
        self._sidebar_logo_image.setFixedSize(icon_width, icon_width)
        self._sidebar_logo_layout.setSpacing(6 if compact else 10)
        self._sidebar_logo_title.setStyleSheet(
            shell_styles.main_window_sidebar_logo_title(F_MD if compact else F_LG)
        )

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
        # Use a compact sidebar on smaller workspaces without shrinking navigation text.
        sidebar = QWidget()
        self.sidebar = sidebar
        sidebar.setObjectName("sidebar")  # QSS ใน config.py ใช้ #sidebar เพื่อกำหนดสีพื้นหลัง
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        sb_lay = QVBoxLayout(sidebar)  # layout แนวตั้งภายใน sidebar
        sb_lay.setContentsMargins(SIDEBAR_MARGIN_LEFT, SIDEBAR_MARGIN_TOP,
                                  SIDEBAR_MARGIN_RIGHT, SIDEBAR_MARGIN_BOTTOM)
        sb_lay.setSpacing(SIDEBAR_SPACING)  # ระยะห่างระหว่างปุ่มแต่ละปุ่ม

        # ─ โลโก้ด้านบน Sidebar ────────────────────────────────
        # หัวแบบ compact: icon เล็กทางซ้าย + ชื่อผลิตภัณฑ์ทางขวา
        logo = QFrame()
        logo.setStyleSheet(shell_styles.MAIN_WINDOW_LOGO)
        ll = QHBoxLayout(logo)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        logo_img = QLabel()
        # หา path ของไฟล์รูปโลโก้ โดยเริ่มจากโฟลเดอร์เดียวกับไฟล์ app.py นี้
        logo_path = os.path.join(os.path.dirname(__file__), LOGO_FILENAME)
        logo_pixmap = QPixmap(logo_path)
        self._sidebar_logo_pixmap = logo_pixmap
        self._sidebar_logo_image = logo_img
        self._sidebar_logo_layout = ll
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
            logo_img.setStyleSheet(text_styles.label('white', font_weight='bold'))

        ll.addWidget(logo_img)
        logo_title = QLabel("KOMI REPORT")
        self._sidebar_logo_title = logo_title
        logo_title.setFont(fnt(F_LG, bold=True))
        logo_title.setStyleSheet(
            shell_styles.MAIN_WINDOW_LOGO_TITLE
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
        language_label.setStyleSheet(text_styles.label('#BFD3E6', padding='2px 8px', background='transparent'))
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
        from ui.reader_members import StatusLinkLabel
        self.status_lbl = StatusLinkLabel("พร้อมใช้งาน")
        self.status_lbl.clicked.connect(self._open_reader_members)
        self.status_lbl.setAccessibleName(tr('ดูสมาชิกคอมพิวเตอร์และสถานะการอ่าน', 'View computer members and reader roles'))
        self.status_lbl.setFont(fnt(F_XS))
        self.status_lbl.setWordWrap(True)  # ตัดบรรทัดถ้าข้อความยาว
        self.status_lbl.setStyleSheet(
            text_styles.label('#CBD5E1', padding=STATUS_PADDING, background='transparent')
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
            shell_styles.main_window_stack()
        )

        # สร้างแต่ละหน้า — ลำดับต้องตรงกับ nav_items ด้านบน
        # ใช้โครง Overview เดิมจาก V4.6 เป็นหน้ารายงานหลักของ V5
        self.pg_overview = PageOverview(lambda: self._data)
        self.pg_import   = PageImportV5(PageImport())
        # Reports prepares Overview during Splash, then stages the other tabs.
        # Settings remains first-navigation only.
        self.pg_history  = _DeferredPage(lambda: PageHistoryV5(staged=True))
        self.pg_settings = _DeferredPage(
            lambda: PageSettingsV5(
                PageSettings(),
                registration_runtime=self.registration,
                offline_license_public_keys=self.offline_license_public_keys,
            )
        )

        pages = [
            self.pg_overview,
            self.pg_import,
            self.pg_history,
            self.pg_settings,
        ]
        self._page_widgets = list(pages)
        self._reports_index = pages.index(self.pg_history)
        self._settings_index = pages.index(self.pg_settings)
        self._deferred_pages = {
            self._reports_index: ("pg_history", self.pg_history),
            self._settings_index: ("pg_settings", self.pg_settings),
        }
        # หน้าที่ใช้ Tab / ตารางภายในจัดการ scroll เอง → ไม่ต้องห่อ QScrollArea
        # Reports and Settings own their internal scrolling.
        no_scroll = {self.pg_history, self.pg_settings}
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
            page.fleet_content.network_activity.bind_runtime(self.polling)
            page.reader_members.bind_runtime(self.polling)
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

    def _prepare_reports_overview(self, splash=None) -> None:
        """Prepare the report shell and start its asynchronous Overview read."""
        if splash is not None:
            if getattr(self, "_startup_refresh_pending", False):
                splash.set_message("กำลังโหลดข้อมูลภาพรวม...")
                self._refresh_all()
                self._startup_refresh_pending = False
            splash.set_message("กำลังเตรียม Reports Overview...")
        page = self._load_deferred_page(self._reports_index)
        prepare = getattr(page, "prepare_overview", None)
        if callable(prepare):
            prepare()

    def _schedule_reports_prewarm(self) -> None:
        """Yield to the shown window before preparing each remaining tab."""
        if getattr(self, "_reports_prewarm_scheduled", False):
            return
        self._reports_prewarm_scheduled = True
        self._reports_prewarm_timers = []
        for delay, index in ((750, 1), (1500, 2)):
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda tab=index: self._prewarm_reports_tab(tab))
            self._reports_prewarm_timers.append(timer)
            timer.start(delay)

    def _prewarm_reports_tab(self, index: int) -> None:
        if getattr(self, "_quitting", False):
            return
        page = getattr(self, "pg_history", None)
        if isinstance(page, _DeferredPage):
            page = self._load_deferred_page(self._reports_index)
        prewarm = getattr(page, "prewarm_tab", None)
        if callable(prewarm):
            prewarm(index)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.windowIcon())
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

    def _open_web_report(self) -> None:
        from ui.web_report_launcher import WebReportLauncher

        if not hasattr(self, "_web_report_launcher"):
            self._web_report_launcher = WebReportLauncher(self.web_service, self)
            self._web_report_launcher.failed.connect(self._web_report_open_failed)
        set_cfg("web_service_enabled", "1")
        self._web_report_launcher.open()

    def _web_report_open_failed(self, detail: str) -> None:
        self._show_from_tray()
        QMessageBox.warning(self, "เปิด KOMI Report Web ไม่สำเร็จ", detail)

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
            try:
                ensure_pairing_default(get_cfg("installation_id", ""),
                                       continuous=True)
            except PeerSyncAuthorizationError:
                log.warning("Peer Sync authorization requires local administrator review")
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
        from datetime import datetime
        slots = [d.slot for d in self.polling.repository.list(enabled_only=True) if slot is None or d.slot == slot]
        self._manual_read_feedback = (set(slots), datetime.now().astimezone())
        self.polling.poll_now(slot)
        self._refresh_manual_read_feedback()

    def _open_reader_members(self):
        page = self._load_deferred_page(self._settings_index)
        self._nav(self.nav_btns[self._settings_index])
        page.show_reader_members()

    def _refresh_manual_read_feedback(self):
        feedback = getattr(self, '_manual_read_feedback', None)
        if feedback is None:
            return
        from datetime import datetime
        from services.runtime_snapshots import runtime_snapshots
        from services.reader_status import newest_time
        slots, started = feedback
        active = slots.intersection(self.polling.active_slots())
        if active:
            text = tr('กำลังอ่านข้อมูล… ', 'Reading… ') + ', '.join(f'Slot {s + 1}' for s in sorted(active))
        else:
            complete, failed = 0, []
            for device in self.polling.repository.list(enabled_only=True):
                if device.slot not in slots:
                    continue
                snapshot = runtime_snapshots.get(device.slot)
                stamp = newest_time((device.last_success_at, snapshot.collected_at if snapshot and (not device.serial or snapshot.serial == device.serial) else ''))
                if stamp and datetime.fromisoformat(stamp).astimezone() >= started:
                    complete += 1
                elif device.last_error:
                    failed.append(f'Slot {device.slot + 1}')
            text = tr('อ่านข้อมูลใหม่สำเร็จ {count}/{total} เครื่อง', 'New readings saved: {count}/{total} printers').format(count=complete, total=len(slots))
            if failed:
                text += tr(' · ควรตรวจสอบ ', ' · Check ') + ', '.join(failed)
            elif complete < len(slots):
                text += tr(' · ที่เหลือไม่มีข้อมูลใหม่', ' · No new data from the remaining printers')
            text += ' · ' + datetime.now().strftime('%H:%M:%S')
            self._manual_read_feedback = None
        self.pg_overview.read_feedback.setText(text)
        self.pg_overview.read_feedback.show()
        self.statusBar().showMessage(text)

    def _schedule_startup_poll(self) -> None:
        """Queue one full read after the configured app passes its fresh status gate."""
        if (
            self._background_started
            and self._startup_poll_pending
            and not self._quitting
            and not self._startup_poll_timer.isActive()
        ):
            self._startup_poll_timer.start(0)

    def _run_startup_poll(self) -> None:
        if not self._startup_poll_pending or not self._background_started or self._quitting:
            return
        eligible, _reason = self._registration_usage_eligibility()
        if not eligible:
            # Status can change between queueing and dispatch; retain the
            # one-shot until eligibility returns instead of reading while paused.
            self._apply_registration_collection_gate()
            return
        self._startup_poll_pending = False
        log.info("startup_sync_requested", extra={"event": "startup_sync_requested"})
        try:
            # The coordinator submits work to its executor and skips slots
            # already being read by a manual or scheduled poll.
            self.polling.poll_now()
        except Exception:
            log.exception("startup_sync_request_failed")

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
        if getattr(self, "_quitting", False):
            return
        """Keep local history open while fail-closing every new device read."""
        eligible, reason = self._registration_usage_eligibility()
        if eligible:
            self.polling.resume()
            self._set_collection_actions_enabled(
                not bool(getattr(self.polling, "active", ()))
            )
            MainWindow._refresh_sidebar_role(self)
            if getattr(self, "_startup_poll_pending", False):
                self._schedule_startup_poll()
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

    def _refresh_sidebar_role(self) -> None:
        if getattr(self, '_quitting', False):
            return
        if not getattr(self, '_background_started', False):
            self.status_lbl.setText(tr('สถานะ\nกำลังตรวจสอบบทบาท', 'Status\nChecking role'))
            return
        eligible, reason = self._registration_usage_eligibility()
        if not eligible:
            self.status_lbl.setText(tr('สถานะ\nกำลังตรวจสอบสิทธิ์การอ่าน', 'Status\nChecking read access')
                if reason == 'status_check_pending' else
                tr('สถานะ\nหยุดอ่านข้อมูล · ดูประวัติได้', 'Status\nReading paused · History available'))
            self.status_lbl.setToolTip(f'Registration: {reason}')
            return
        from services.sidebar_reader_role import reader_role_text
        label, detail = reader_role_text(self.polling)
        from services.reader_status import latest_local_data, display_time
        latest = display_time(latest_local_data(self.polling))
        self.status_lbl.setText(label + tr('\nข้อมูลล่าสุด ', '\nLatest data ') + latest)
        self.status_lbl.setToolTip(detail)
        MainWindow._refresh_manual_read_feedback(self)

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
            self.polling.network_recovered()

    def _device_updated(self, _slot: int):
        if self._quitting:
            return
        # Device and reading signals often arrive together (and once per
        # device). Coalesce that burst so the UI thread redraws only once.
        self._schedule_refresh_all()
        if not self.polling.active:
            self.pg_import.sync_completed()
        if self.polling.is_paused:
            self._set_collection_actions_enabled(False)
            return
        MainWindow._refresh_sidebar_role(self)

    def _show_main_window(self):
        """Show the desktop workspace at the maximum usable screen size."""
        self.showMaximized()
        self.raise_()
        self.activateWindow()
        schedule = getattr(self, "_schedule_reports_prewarm", None)
        if callable(schedule):
            schedule()

    def _show_from_tray(self):
        pending = getattr(self, "_agent_handoff", None)
        if pending is not None and not pending.committed:
            pending.cancel()
            self._agent_handoff = None
            pending.deleteLater()
        self._show_main_window()

    def _language_changed(self, _index: int) -> None:
        language = str(self.language_combo.currentData() or THAI)
        set_language(language)
        set_cfg("ui_language", language)
        apply_language(self)
        # Rebuild charts and status strings that are painted outside ordinary
        # Qt text widgets (for example the Overview Y-axis title).
        self._refresh_visible_page()
        MainWindow._refresh_sidebar_role(self)

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

    def _confirm_discard_settings_on_exit(self, *, discard: bool = True) -> bool:
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
        discard_action = getattr(page, "discard_unsaved_changes", None)
        if discard and callable(discard_action):
            discard_action()
        return True

    def _stop_ui_work(self):
        if getattr(self, "_ui_work_stopped", False):
            return
        self._ui_work_stopped = True
        for name in ("_refresh_timer", "_startup_poll_timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.stop()
        shutdown_reports = getattr(getattr(self, "pg_history", None), "shutdown_report_loading", None)
        if callable(shutdown_reports):
            shutdown_reports()
        from ui.background_read import LatestRead
        for reader in self.findChildren(LatestRead):
            reader.shutdown()

    def _exit_application(self):
        if self._quitting:
            return
        pending = getattr(self, "_agent_handoff", None)
        if pending is not None and not pending.committed:
            pending.cancel()
            self._agent_handoff = None
            pending.deleteLater()
        reply = QMessageBox.question(
            self,
            tr("หยุดโปรแกรมทั้งหมด", "Stop the application"),
            tr(
                "การอ่านมิเตอร์และรายงานผ่านเว็บบนคอมพิวเตอร์เครื่องนี้จะหยุดจนกว่าจะเปิดโปรแกรมอีกครั้ง ต้องการหยุดทั้งหมดหรือไม่?",
                "Meter collection and web reports on this computer will stop until the application is opened again. Stop everything?",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not self._confirm_discard_settings_on_exit():
            return
        self._quitting = True
        self._stop_ui_work()
        hide_tray = getattr(self.tray, "hide", None)
        if callable(hide_tray):
            hide_tray()
        self.polling.stop()
        self.registration.stop()
        self.web_service.stop()
        QApplication.instance().quit()

    def _begin_agent_handoff(self):
        if getattr(self, "_agent_handoff", None) is not None:
            return
        from services.agent_handoff import AgentHandoff
        handoff = AgentHandoff(self)
        self._agent_handoff = handoff

        def failed(_reason):
            self._agent_handoff = None
            handoff.deleteLater()
            QMessageBox.warning(self, "KOMI Report V5", tr(
                "Agent ยังไม่พร้อม หน้าต่างและการอ่านข้อมูลเดิมยังทำงานอยู่ กรุณาลองปิดอีกครั้ง",
                "The agent is not ready. This window and its collection services are still running. Please try closing again.",
            ))

        def ready():
            if self._quitting or not self._confirm_discard_settings_on_exit(discard=False):
                handoff.cancel()
                self._agent_handoff = None
                handoff.deleteLater()
                return
            if not handoff.commit():
                failed("commit_failed")
                return
            self._quitting = True
            self.close()
            QApplication.instance().quit()

        handoff.failed.connect(failed)
        handoff.ready.connect(ready)
        handoff.start()

    def closeEvent(self, event: QCloseEvent):
        close_to_tray = get_cfg("close_to_tray", "1") != "0"
        if self._quitting or not close_to_tray or not QSystemTrayIcon.isSystemTrayAvailable():
            if not self._quitting and not self._confirm_discard_settings_on_exit():
                event.ignore()
                return
            self._quitting = True
            self._stop_ui_work()
            hide_tray = getattr(self.tray, "hide", None)
            if callable(hide_tray):
                hide_tray()
            self.polling.stop()
            self.registration.stop()
            self.web_service.stop()
            event.accept()
            return
        # Keep packaged routing unchanged until packaging verification.
        if self._background_started and not getattr(sys, "frozen", False):
            self._begin_agent_handoff()
            event.ignore()
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
        if idx == self._reports_index:
            opened = getattr(self.pg_history, "on_reports_opened", None)
            if callable(opened):
                opened()

    def _finish_deferred_navigation(self, index: int) -> None:
        self._load_deferred_page(index)
        if self.stack.currentIndex() == index and self._ui_ready:
            self._refresh_visible_page()
            if index == self._reports_index:
                opened = getattr(self.pg_history, "on_reports_opened", None)
                if callable(opened):
                    opened()

    def _schedule_refresh_all(self) -> None:
        """Debounce bursts of polling signals before querying and redrawing."""
        if self._quitting:
            return
        self._refresh_timer.start()

    def _refresh_visible_page(self) -> None:
        """Refresh a stale page only when it is actually visible."""
        if getattr(self, "_quitting", False):
            return
        index = self.stack.currentIndex()
        if index not in self._dirty_pages:
            return
        page = self._page_widgets[index]
        refresh_visible = (
            getattr(page, "refresh_visible_cached", None)
            or getattr(page, "refresh_visible", None)
        )
        if callable(refresh_visible):
            apply_language(page)
            self._dirty_pages.discard(index)
            QTimer.singleShot(0, lambda: refresh_visible() if not self._quitting else None)
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
        if self._quitting:
            return
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
        invalidate = getattr(getattr(self, "pg_history", None), "invalidate_data", None)
        if callable(invalidate):
            invalidate()
        self._refresh_visible_page()
        MainWindow._refresh_sidebar_role(self)
        if self._background_started:
            eligible, _reason = self._registration_usage_eligibility()
            if not eligible:
                self._apply_registration_collection_gate()


# First-run setup uses the current V5 wizard.
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
    configure_numeric_locale()
    app = QApplication(sys.argv)
    configure_qt_application_identity(app, version=APP_VER)
    app.setWindowIcon(load_application_icon())
    install_button_system(app)
    try:
        refresh_existing_autostart()
    except OSError:
        log.exception("cannot refresh existing background-agent registration")
    instance_guard = SingleInstanceGuard(Path(get_db_path()).with_suffix(".instance.lock"))
    if not instance_guard.acquire(command="open-web" if "--open-web" in sys.argv else "activate"):
        log.warning("another KOMI Report V5 instance is already running")
        sys.exit(0)
    # Hold desktop ownership before stopping the agent, and never start a second
    # set of collectors while its current transactions are still completing.
    if not stop_running_background_agent(Path(get_db_path())):
        QMessageBox.information(
            None,
            "KOMI Report V5",
            tr("Agent กำลังบันทึกข้อมูล กรุณาเปิดโปรแกรมอีกครั้งเมื่อเสร็จ",
               "The agent is finishing its current work. Please reopen the application shortly."),
        )
        instance_guard.release()
        sys.exit(1)
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
    instance_guard.web_open_requested.connect(win._open_web_report)

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
        if "--background" in sys.argv or "--open-web" in sys.argv:
            win.hide()
        else:
            win._show_main_window()

        def finish_startup() -> None:
            if getattr(win, "_startup_refresh_pending", False):
                win._startup_refresh_pending = False
                win._refresh_all()
            win.start_background_services()
            if "--open-web" in sys.argv:
                win._open_web_report()

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
        # Keep desktop ownership while worker transactions finish. Otherwise a
        # new agent/desktop can collect concurrently during Python shutdown.
        win.polling.stop(wait=True)
        win.registration.stop(wait=True)
        instance_guard.release()
    sys.exit(exit_code)
