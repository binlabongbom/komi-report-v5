#!/usr/bin/env python3
"""
check_parser.py  —  เครื่องมือปรับแต่ง Parser Profile (v3 — ออกแบบใหม่)

โครงสร้าง UI:
  Sidebar  : อัพโหลดไฟล์ตัวอย่าง | รายการ Profile 1-10 | ปุ่มบันทึก/เคลียร์
  Center   : ชื่อ Parser | รุ่นที่ Detect | ตารางคอลัมน์ + Mapping

การใช้งาน:
  python tools/check_parser.py
"""

import sys
import json
from pathlib import Path


from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QLineEdit, QComboBox, QFileDialog, QMessageBox,
    QFrame, QScrollArea, QHeaderView, QAbstractItemView,
    QSizePolicy, QCheckBox, QStackedWidget,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QDragEnterEvent, QDropEvent

# ── เพิ่ม path โปรแกรมหลัก ──────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from services.support_diagnostics import with_diagnostic

import config as cfg

# ════════════════════════════════════════════════════════════
# CONSTANTS
# ════════════════════════════════════════════════════════════

NUM_PROFILES = 10

# storage path
PROFILES_DIR  = Path.home() / "KOMI Report V5" / "Parser profiles"
PROFILES_JSON = PROFILES_DIR / "konica_parser_user_profiles.json"  # legacy (migration only)

# DB field options for dropdown mapping
DB_FIELDS = [
    ("(ไม่ Mapping)",       ""),
    ("Grand Total",          "grand_total"),
    ("Full Color Total",     "full_color_total"),
    ("B&W Total",            "bw_total"),
    ("A4 - Full Color",      "a4_color"),
    ("A4 - B&W",             "a4_bw"),
    ("A3 - Full Color",      "a3_color"),
    ("A3 - B&W",             "a3_bw"),
    ("User / Account Name",  "user"),
    ("Meter - Full Color",   "color_meter"),
    ("Meter - B&W",          "bw_meter"),
]

# map db_key → Thai label for display
DB_KEY_LABEL = {key: label for label, key in DB_FIELDS if key}

# ════════════════════════════════════════════════════════════
# PROFILE STORAGE HELPERS
# ════════════════════════════════════════════════════════════

# ประเภทไฟล์ที่ Parser นี้รองรับ
PARSER_TYPES = [
    ("summary",    "Summary",    "#16A34A"),   # label, display, color
    ("user",       "User",       "#2563EB"),
    ("production", "Production", "#D97706"),
    ("label",      "Label",      "#8B5CF6"),
]

def _empty_profile(slot: int) -> dict:
    return {
        "slot":       slot,
        "name":       f"Parser Profile {slot}",
        "models":     "",
        "types":      [],   # list of enabled type keys
        "column_map": {},   # {db_field_key: col_index}
        "column_multipliers": {},  # {col_index: multiplier_value} for each column
    }


def load_profiles() -> list:
    """
    โหลด profiles จากไฟล์แยกแต่ละ profile  (profile_01.json, profile_02.json, ...)

    Priority:
    1. โหลดจากไฟล์ profile_*.json แยกในโฟลเดอร์ PROFILES_DIR
    2. Migrate จากไฟล์รวม konica_parser_user_profiles.json เดิม (ถ้ามี)
    3. ถ้าไม่มี → copy จาก tools/default_profiles.json
    4. ถ้าไม่มี → ใช้ empty profile 1 รายการ
    """
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    # 1. โหลดจากไฟล์แยก
    profile_files = sorted(PROFILES_DIR.glob("profile_*.json"))
    if profile_files:
        profiles = []
        for pf in profile_files:
            try:
                p = json.loads(pf.read_text(encoding="utf-8"))
                profiles.append(p)
            except Exception:
                pass
        if profiles:
            for i, p in enumerate(profiles):
                profiles[i] = {**_empty_profile(i + 1), **p, "slot": i + 1}
            return profiles

    # 2. Migrate จากไฟล์รวมเดิม
    if PROFILES_JSON.exists():
        try:
            data = json.loads(PROFILES_JSON.read_text(encoding="utf-8"))
            loaded = data.get("profiles", [])
            if loaded:
                profiles = []
                for i, p in enumerate(loaded):
                    profiles.append({**_empty_profile(i + 1), **p, "slot": i + 1})
                save_profiles(profiles)   # บันทึกเป็นไฟล์แยก
                PROFILES_JSON.unlink()    # ลบไฟล์เดิม
                return profiles
        except Exception:
            pass

    return [_empty_profile(1)]


def save_profiles(profiles: list) -> None:
    """บันทึก profiles แยกเป็นไฟล์ต่อ profile  (profile_01.json, profile_02.json, ...)"""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    current_slots: set[int] = set()
    for p in profiles:
        slot = p.get("slot", 1)
        current_slots.add(slot)
        fname = PROFILES_DIR / f"profile_{slot:02d}.json"
        fname.write_text(
            json.dumps(p, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    # ลบไฟล์ของ slot ที่ถูกลบออกไปแล้ว
    for pf in PROFILES_DIR.glob("profile_*.json"):
        try:
            if int(pf.stem.replace("profile_", "")) not in current_slots:
                pf.unlink()
        except (ValueError, OSError):
            pass


def apply_column_map(data_row: list, column_map: dict) -> dict:
    """
    ใช้ column_map กับแถวข้อมูลจริง → คืน {db_field_key: int}

    รองรับรูปแบบ:
      column_map = {"grand_total": [0],         # 1 column
                    "a4_bw":       [12, 15, 20]} # หลาย column → บวกกัน

    ถ้า column ใดอ่านไม่ได้ (ไม่ใช่ตัวเลข) จะถือเป็น 0
    """
    def _safe_int(row: list, idx: int) -> int:
        try:
            return int(str(row[idx]).strip()) if idx < len(row) else 0
        except (ValueError, TypeError):
            return 0

    result = {}
    for db_key, cols in column_map.items():
        if isinstance(cols, list):
            result[db_key] = sum(_safe_int(data_row, c) for c in cols)
        elif isinstance(cols, int) and cols >= 0:
            result[db_key] = _safe_int(data_row, cols)   # backward compat
    return result


# ════════════════════════════════════════════════════════════
# FILE READER
# ════════════════════════════════════════════════════════════

def read_meter_file(filepath: str):
    """
    อ่านไฟล์ .txt มิเตอร์ Konica Minolta
    รองรับ: C750i (tab-delimited) + Label 230 (hierarchical)
    คืน: (headers, headers2, headers3, first_data_row, all_data_rows, machine_name, serial, date_str)
    """
    path = Path(filepath)
    content = None
    for enc in ["utf-16", "utf-8-sig", "utf-8", "cp874", "latin-1"]:
        try:
            content = path.read_text(encoding=enc)
            if "\x00" not in content[:50]:
                break
            else:
                content = None
        except Exception:
            content = None

    if content is None:
        raw = path.read_bytes()
        if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
            content = raw.decode("utf-16", errors="replace")
        else:
            content = raw.decode("utf-8", errors="replace")

    lines_raw = content.splitlines()
    lines = [line.split("\t") for line in lines_raw]

    def _clean(s: str) -> str:
        return s.replace("\x00", "").strip()

    def _get_meta(row, fallback: str = "") -> str:
        cleaned = [_clean(c) for c in row]
        for c in cleaned[4::-1]:
            if c:
                return c
        return fallback

    # metadata
    machine_name = _get_meta(lines[0], "Unknown") if len(lines) > 0 else "Unknown"
    serial       = _get_meta(lines[1], "")         if len(lines) > 1 else ""
    date_str     = _get_meta(lines[2], "")         if len(lines) > 2 else ""

    # ตรวจจับ format: ถ้า machine name มี "Label" ใช้ parse แบบ Label
    if "Label" in machine_name:
        return _parse_label(lines, machine_name, serial, date_str)
    else:
        return _parse_standard(lines, machine_name, serial, date_str)


def _parse_label(lines, machine_name, serial, date_str):
    """Parser สำหรับ Label 230 (hierarchical format)"""
    def _clean(s: str) -> str:
        return s.replace("\x00", "").strip()

    # Headers สำหรับ Label format
    headers = ["Category", "Type", "Sub-Type"]
    headers2 = ["", "", ""]
    headers3 = ["", "", ""]

    # แยก categories จากไฟล์
    all_data_rows = []
    current_category = ""
    
    for i in range(3, len(lines)):
        row = [_clean(c) for c in lines[i]]
        if not row or not any(row):
            continue
        
        col0 = row[0] if len(row) > 0 else ""
        col1 = row[1] if len(row) > 1 else ""
        col2 = row[2] if len(row) > 2 else ""
        col3 = row[3] if len(row) > 3 else ""
        col4 = row[4] if len(row) > 4 else ""
        
        # ตรวจหากำลังเป็นหมวดหมู่หลัก (เช่น Copy, Printer, Color)
        if col0 and not col1 and not col2 and col4 and col4.lstrip("-").isdigit():
            # แถวค่ารวมทั้งหมด: Total Counter 86138
            all_data_rows.append([col0, "", value := col4])
        elif col0 and col1 and col4 and col4.lstrip("-").isdigit():
            # หมวดหมู่หลัก: Copy Total 735
            current_category = col0
            type_name = col1
            value = col4
            all_data_rows.append([current_category, type_name, value])
        elif col0 and not col1 and col2 and col4 and col4.lstrip("-").isdigit():
            # Sub-category: (indent) Full Color 719
            type_name = col2
            value = col4
            all_data_rows.append([current_category, type_name, value])
        elif not col0 and not col1 and col2 and col4 and col4.lstrip("-").isdigit():
            # Deep indent: (indent) Full Color 719
            type_name = col2
            value = col4
            all_data_rows.append([current_category, type_name, value])
    
    # Use first data row as default
    data_row = all_data_rows[0] if all_data_rows else ["", "", ""]
    
    # Pad to 3 columns
    max_len = 3
    headers = (headers + [""] * max_len)[:max_len]
    headers2 = (headers2 + [""] * max_len)[:max_len]
    headers3 = (headers3 + [""] * max_len)[:max_len]
    data_row = (data_row + [""] * max_len)[:max_len]
    
    return headers, headers2, headers3, data_row, all_data_rows, machine_name, serial, date_str


def _parse_standard(lines, machine_name, serial, date_str):
    """Parser มาตรฐาน สำหรับ C750i และไฟล์ tab-delimited"""
    def _clean(s: str) -> str:
        return s.replace("\x00", "").strip()

    # หา header rows (3 แถว)
    header_row_idx = -1
    h1, h2, h3 = [], [], []
    for i in range(3, min(10, len(lines))):
        row = [_clean(c) for c in lines[i]]
        named = [c for c in row if c and not c.isdigit()]
        if len(named) >= 2:
            h1 = row
            header_row_idx = i
            # ดึง sub-header rows ถัดไป
            for offset, target in ((1, h2), (2, h3)):
                if header_row_idx + offset < len(lines):
                    r = [_clean(c) for c in lines[header_row_idx + offset]]
                    if not (r and r[0].lstrip("-").isdigit()):
                        target.extend(r)
            break

    # Collect ALL data rows
    all_data_rows = []
    for i in range(header_row_idx + 1 if header_row_idx >= 0 else 4, len(lines)):
        row = [_clean(c) for c in lines[i]]
        if not row:
            continue
        if row[0].lstrip("-").isdigit() and len(row) >= 2:
            all_data_rows.append(row)
        elif row[0] and not row[0].isdigit() and len(row) >= 4:
            nums = [c for c in row[1:5] if c.isdigit()]
            if len(nums) >= 2:
                all_data_rows.append(row)

    # Use first data row as default
    data_row = all_data_rows[0] if all_data_rows else []

    # pad lengths
    max_len = max(len(h1), len(h2), len(h3), len(data_row), 1)
    h1       = list(h1)       + [""] * (max_len - len(h1))
    h2       = list(h2)       + [""] * (max_len - len(h2))
    h3       = list(h3)       + [""] * (max_len - len(h3))
    data_row = list(data_row) + [""] * (max_len - len(data_row))

    return h1, h2, h3, data_row, all_data_rows, machine_name, serial, date_str


# ════════════════════════════════════════════════════════════
# DRAG & DROP ZONE WIDGET
# ════════════════════════════════════════════════════════════

class DropZone(QFrame):
    """ช่องสี่เหลี่ยม Drag & Drop ไฟล์ .txt — ยังรองรับ click เปิด dialog"""
    file_dropped = pyqtSignal(str)   # ส่ง path ออกมา

    _STYLE_IDLE = (
        "QFrame { background:rgba(255,255,255,0.10);"
        " border:2px dashed rgba(255,255,255,0.35);"
        " border-radius:10px; }"
    )
    _STYLE_HOVER = (
        "QFrame { background:rgba(255,255,255,0.22);"
        " border:2px dashed rgba(255,255,255,0.80);"
        " border-radius:10px; }"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(88)
        self.setStyleSheet(self._STYLE_IDLE)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._icon = QLabel("📂")
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet("font-size:26px; background:transparent; border:none;")
        lay.addWidget(self._icon)

        self._line1 = QLabel("วางไฟล์ที่นี่")
        self._line1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._line1.setStyleSheet(
            f"color:white; font-weight:600; font-size:{cfg.F_MD}pt;"
            " background:transparent; border:none;"
        )
        lay.addWidget(self._line1)

        self._line2 = QLabel("หรือคลิกเพื่อเลือกไฟล์")
        self._line2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._line2.setStyleSheet(
            "color:rgba(255,255,255,0.55); font-size:8pt;"
            " background:transparent; border:none;"
        )
        lay.addWidget(self._line2)

    # ── drag events ──────────────────────────────────────
    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            urls = e.mimeData().urls()
            if any(u.toLocalFile().lower().endswith(".txt") for u in urls):
                e.acceptProposedAction()
                self.setStyleSheet(self._STYLE_HOVER)
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        self.setStyleSheet(self._STYLE_IDLE)

    def dropEvent(self, e: QDropEvent):
        self.setStyleSheet(self._STYLE_IDLE)
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".txt"):
                self.file_dropped.emit(path)
                return

    # ── click → open dialog ──────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            path, _ = QFileDialog.getOpenFileName(
                self, "เลือกไฟล์ตัวอย่าง (.txt)",
                "", "Konica Minolta (*.txt);;All Files (*)"
            )
            if path:
                self.file_dropped.emit(path)
        super().mousePressEvent(e)

    def set_filename(self, name: str):
        """อัพเดต label เมื่ออ่านไฟล์สำเร็จ"""
        self._icon.setText("✅")
        self._line1.setText(name)
        self._line1.setStyleSheet(
            f"color:#86EFAC; font-weight:600; font-size:{cfg.F_XS}pt;"
            " background:transparent; border:none;"
        )
        self._line2.setText("คลิกเพื่อเปลี่ยนไฟล์")


# ════════════════════════════════════════════════════════════
# JSON IMPORT DROP PANEL (empty-state)
# ════════════════════════════════════════════════════════════

class _JsonDropPanel(QFrame):
    """Panel empty-state — Drag & Drop ไฟล์ .json เพื่อนำเข้า Parser Profile"""
    json_dropped = pyqtSignal(str)

    _STYLE_IDLE = (
        "QFrame#json_drop_zone {"
        " background: rgba(37,99,235,0.05);"
        " border: 2px dashed rgba(37,99,235,0.28);"
        " border-radius: 16px;"
        "}"
    )
    _STYLE_HOVER = (
        "QFrame#json_drop_zone {"
        " background: rgba(37,99,235,0.13);"
        " border: 2px dashed rgba(37,99,235,0.85);"
        " border-radius: 16px;"
        "}"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("json_drop_zone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._STYLE_IDLE)

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setSpacing(0)

        inner = QWidget()
        inner.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(inner)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(16)

        icon_lbl = QLabel("🧩")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size:56px; background:transparent; border:none;")
        lay.addWidget(icon_lbl)

        t1 = QLabel("ยังไม่มี Parser Profile")
        t1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f1 = QFont(cfg.UI_FONT_FAMILY, cfg.F_2XL)
        f1.setBold(True)
        t1.setFont(f1)
        t1.setStyleSheet(f"color:{cfg.C_TEXT}; background:transparent; border:none;")
        lay.addWidget(t1)

        t2 = QLabel(
            "ลาก & วาง ไฟล์ .json ที่นี่\n"
            "หรือคลิกที่นี่เพื่อเลือกไฟล์ Parser Profile"
        )
        t2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t2.setStyleSheet(
            f"color:{cfg.C_TEXT2}; font-size:{cfg.F_LG}pt;"
            " background:transparent; border:none;"
        )
        lay.addWidget(t2)

        lay.addSpacing(20)

        hint = QLabel("รองรับไฟล์ .json ที่ส่งออกจาก Parser Config")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(
            f"color:{cfg.C_TEXT3}; font-size:{cfg.F_SM}pt;"
            " background:transparent; border:none;"
        )
        lay.addWidget(hint)

        outer.addWidget(inner)

    # ── drag events ──────────────────────────────────────
    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            if any(u.toLocalFile().lower().endswith(".json")
                   for u in e.mimeData().urls()):
                e.acceptProposedAction()
                self.setStyleSheet(self._STYLE_HOVER)
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        self.setStyleSheet(self._STYLE_IDLE)

    def dropEvent(self, e: QDropEvent):
        self.setStyleSheet(self._STYLE_IDLE)
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".json"):
                self.json_dropped.emit(path)
                return

    # ── click → file dialog ──────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            path, _ = QFileDialog.getOpenFileName(
                self, "นำเข้า Parser Profiles (.json)",
                str(Path.home()), "JSON Files (*.json);;All Files (*)"
            )
            if path:
                self.json_dropped.emit(path)
        super().mousePressEvent(e)


# ════════════════════════════════════════════════════════════
# STYLE HELPERS
# ════════════════════════════════════════════════════════════

def _fnt(size=None, bold=False):
    size = size or cfg.F_MD
    f = QFont(cfg.UI_FONT_FAMILY, size)
    f.setBold(bold)
    return f


def _mk_label(text, bold=False, size=None, color=None):
    lbl = QLabel(text)
    lbl.setFont(_fnt(size, bold))
    if color:
        lbl.setStyleSheet(f"color:{color};")
    return lbl


def _mk_btn(text, primary=False, danger=False, width=None):
    b = QPushButton(text)
    b.setFont(_fnt(cfg.F_MD, bold=True))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if width:
        b.setFixedWidth(width)
    if primary:
        b.setStyleSheet(
            f"QPushButton {{ background:{cfg.C_ACCENT}; color:white; border:none;"
            f" border-radius:7px; padding:8px 18px; font-weight:600; }}"
            f"QPushButton:hover {{ background:#1E3A8A; }}"
            f"QPushButton:pressed {{ background:#1E3A8A; }}"
        )
    elif danger:
        b.setStyleSheet(
            f"QPushButton {{ background:{cfg.C_RED}; color:white; border:none;"
            f" border-radius:7px; padding:8px 18px; font-weight:600; }}"
            f"QPushButton:hover {{ background:#B91C1C; }}"
        )
    else:
        b.setStyleSheet(
            f"QPushButton {{ background:#F8FAFC; color:{cfg.C_TEXT}; border:1.5px solid {cfg.C_BORDER};"
            f" border-radius:7px; padding:8px 18px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{cfg.C_ACCENT}; color:white; border-color:{cfg.C_ACCENT}; }}"
        )
    return b


def _hline():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{cfg.C_BORDER};")
    return f


# ════════════════════════════════════════════════════════════
# MAIN WINDOW
# ════════════════════════════════════════════════════════════

class ParserEditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🧩  ตั้งค่า Parser Profile — Konica Minolta Meter")
        self.setMinimumSize(1100, 680)
        self.resize(1280, 780)

        self._profiles    = load_profiles()
        self._current_idx = 0          # 0-based index
        self._headers  = []  # header row 1 (ชื่อหลัก)
        self._headers2 = []  # header row 2 (sub-header)
        self._headers3 = []  # header row 3 (sub-sub-header)
        self._values   = []  # data values from uploaded file
        
        # All data rows from file - user can select which row to use as values
        self._all_file_rows = []  # List of all data rows found in file
        
        # Reading mode: which row to read values from
        # Mode 0 = Read from first data row (normal)
        # Mode 1 = Read from header row (transposed)
        self._reading_mode = 0  # 0=data_row, 1=header_row
        self._available_rows = []  # All available rows from file
        self._selected_row_idx = 0  # Which row is currently selected
        self._file_is_label = False  # True เมื่อไฟล์ที่โหลดเป็น Label format จริงๆ

        self._build()
        self._select_profile(0)
        self._update_center_page()

    # ─────────────────────────────────────────────────────
    # BUILD UI
    # ─────────────────────────────────────────────────────
    def _build(self):
        self.setStyleSheet(self._qss())
        self.setAcceptDrops(True)   # รองรับ drag & drop ไฟล์ .json ทั่วทั้งหน้าต่าง

        root = QWidget()
        root_lay = QHBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)
        self.setCentralWidget(root)

        # ── Sidebar ──────────────────────────────────────
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)
        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(14, 18, 14, 14)
        sb_lay.setSpacing(8)

        # Logo
        logo = _mk_label("🧩  Parser Config", bold=True, size=cfg.F_LG)
        logo.setStyleSheet("color:white; background:transparent;")
        sb_lay.addWidget(logo)

        sub = _mk_label("Konica Minolta Meter Reader", size=cfg.F_XS)
        sub.setStyleSheet("color:rgba(255,255,255,0.55); background:transparent;")
        sb_lay.addWidget(sub)

        sb_lay.addSpacing(12)

        # Drag & Drop zone
        self.drop_zone = DropZone()
        self.drop_zone.file_dropped.connect(self._upload_file)
        sb_lay.addWidget(self.drop_zone)

        # ── Reading Mode selector (Column vs Row)
        sb_lay.addWidget(self._sidebar_hline())
        sb_lay.addSpacing(8)
        sb_lay.addWidget(_mk_label("Reading Mode", bold=True, size=cfg.F_SM,
                                    color="rgba(255,255,255,0.6)"))
        sb_lay.addSpacing(6)

        # Reading mode dropdown
        self.cmb_reading_mode = QComboBox()
        self.cmb_reading_mode.setFont(_fnt(cfg.F_SM))
        self.cmb_reading_mode.setFixedHeight(32)
        self.cmb_reading_mode.addItems([
            "📊 Read from Data Row (Normal)",
            "🔄 Read from Header Row"
        ])
        self.cmb_reading_mode.setStyleSheet(
            f"QComboBox {{ background:rgba(255,255,255,0.08); color:white;"
            f" border:1px solid rgba(255,255,255,0.15); border-radius:6px;"
            f" padding:6px 10px; font-size:{cfg.F_SM}pt; }}"
            "QComboBox::drop-down { border:none; }"
            "QComboBox::down-arrow { color:rgba(255,255,255,0.5); }"
        )
        self.cmb_reading_mode.currentIndexChanged.connect(self._on_reading_mode_changed)
        sb_lay.addWidget(self.cmb_reading_mode)

        # Row selector (shown only in Header Row mode)
        sb_lay.addSpacing(8)
        self.lbl_row_selector = _mk_label("Select Header Row:", size=cfg.F_SM,
                                          color="rgba(255,255,255,0.6)")
        sb_lay.addWidget(self.lbl_row_selector)

        self.cmb_header_row = QComboBox()
        self.cmb_header_row.setFont(_fnt(cfg.F_SM))
        self.cmb_header_row.setFixedHeight(28)
        self.cmb_header_row.setStyleSheet(
            f"QComboBox {{ background:rgba(255,255,255,0.08); color:white;"
            f" border:1px solid rgba(255,255,255,0.15); border-radius:5px;"
            f" padding:4px 8px; font-size:{cfg.F_SM}pt; }}"
            "QComboBox::drop-down { border:none; }"
            "QComboBox::down-arrow { color:rgba(255,255,255,0.5); }"
        )
        self.cmb_header_row.currentIndexChanged.connect(self._on_header_row_selected)
        sb_lay.addWidget(self.cmb_header_row)
        
        # Initially hidden - shown when header row mode is active
        self.lbl_row_selector.hide()
        self.cmb_header_row.hide()

        sb_lay.addWidget(self._sidebar_hline())
        sb_lay.addSpacing(2)
        sb_lay.addWidget(_mk_label("Parser Profiles", bold=True, size=cfg.F_SM,
                                    color="rgba(255,255,255,0.6)"))
        sb_lay.addSpacing(4)

        # Profile list
        self.profile_list = QListWidget()
        self.profile_list.setObjectName("profile_list")
        self.profile_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.profile_list.setStyleSheet(
            "QListWidget { background:transparent; border:none; outline:none; }"
            f"QListWidget::item {{ color:white; padding:6px 10px; border-radius:6px;"
            f" font-size:{cfg.F_MD}pt; }}"
            "QListWidget::item:selected { background:rgba(255,255,255,0.18); font-weight:bold; }"
            "QListWidget::item:hover:!selected { background:rgba(255,255,255,0.09); }"
        )
        for p in self._profiles:
            self._add_profile_item(p)
        self.profile_list.setCurrentRow(0)
        self.profile_list.currentRowChanged.connect(self._select_profile)
        sb_lay.addWidget(self.profile_list)

        # ── Add / Remove parser buttons ───────────────────
        _sb_btn_style = (
            "QPushButton { background:rgba(255,255,255,0.08); color:white;"
            " border:1px solid rgba(255,255,255,0.15); border-radius:6px;"
            " padding:5px 8px; font-weight:600; }"
            "QPushButton:hover { background:rgba(255,255,255,0.22); }"
        )
        add_rem_row = QHBoxLayout()
        add_rem_row.setSpacing(6)
        self.btn_add_parser = QPushButton("➕  เพิ่ม Parser")
        self.btn_add_parser.setFont(_fnt(cfg.F_SM, bold=True))
        self.btn_add_parser.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_parser.setFixedHeight(30)
        self.btn_add_parser.setStyleSheet(_sb_btn_style)
        self.btn_add_parser.clicked.connect(self._add_parser)
        add_rem_row.addWidget(self.btn_add_parser)
        self.btn_remove_parser = QPushButton("🗑  ลบ")
        self.btn_remove_parser.setFont(_fnt(cfg.F_SM, bold=True))
        self.btn_remove_parser.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remove_parser.setFixedHeight(30)
        self.btn_remove_parser.setStyleSheet(
            "QPushButton { background:rgba(220,38,38,0.15); color:#FCA5A5;"
            " border:1px solid rgba(220,38,38,0.25); border-radius:6px;"
            " padding:5px 8px; font-weight:600; }"
            "QPushButton:hover { background:rgba(220,38,38,0.35); color:white; }"
        )
        self.btn_remove_parser.clicked.connect(self._remove_parser)
        add_rem_row.addWidget(self.btn_remove_parser)
        sb_lay.addLayout(add_rem_row)

        sb_lay.addStretch()
        sb_lay.addWidget(self._sidebar_hline())
        sb_lay.addSpacing(4)

        # ── Import / Export buttons ───────────────────────
        imp_exp_row = QHBoxLayout()
        imp_exp_row.setSpacing(6)
        self.btn_import = QPushButton("📥  นำเข้า")
        self.btn_import.setFont(_fnt(cfg.F_SM, bold=True))
        self.btn_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import.setFixedHeight(32)
        self.btn_import.setToolTip("นำเข้า Parser Profiles จากไฟล์ JSON")
        self.btn_import.setStyleSheet(_sb_btn_style)
        self.btn_import.clicked.connect(self._import_parsers)
        imp_exp_row.addWidget(self.btn_import)
        self.btn_export = QPushButton("📤  ส่งออก")
        self.btn_export.setFont(_fnt(cfg.F_SM, bold=True))
        self.btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export.setFixedHeight(32)
        self.btn_export.setToolTip("ส่งออก Parser Profiles ทั้งหมดเป็นไฟล์ JSON")
        self.btn_export.setStyleSheet(_sb_btn_style)
        self.btn_export.clicked.connect(self._export_parsers)
        imp_exp_row.addWidget(self.btn_export)
        sb_lay.addLayout(imp_exp_row)
        sb_lay.addSpacing(6)

        # Save / Clear buttons
        self.btn_save = QPushButton("💾  บันทึก")
        self.btn_save.setFont(_fnt(cfg.F_MD, bold=True))
        self.btn_save.setFixedHeight(38)
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.setStyleSheet(
            f"QPushButton {{ background:{cfg.C_ACCENT}; color:white; border:none;"
            f" border-radius:7px; padding:8px 18px; font-weight:600; }}"
            "QPushButton:hover { background:#1E3A8A; }"
        )
        self.btn_save.clicked.connect(self._save_current)
        sb_lay.addWidget(self.btn_save)

        self.btn_clear = QPushButton("🗑  เคลียร์ Profile นี้")
        self.btn_clear.setFont(_fnt(cfg.F_MD, bold=True))
        self.btn_clear.setFixedHeight(34)
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.setStyleSheet(
            "QPushButton { background:rgba(220,38,38,0.15); color:#FCA5A5;"
            " border:1px solid rgba(220,38,38,0.30);"
            " border-radius:7px; padding:6px 12px; font-weight:600; }"
            "QPushButton:hover { background:rgba(220,38,38,0.35); color:white; }"
        )
        self.btn_clear.clicked.connect(self._clear_current)
        sb_lay.addWidget(self.btn_clear)

        root_lay.addWidget(sidebar)

        # ── Center Panel ─────────────────────────────────
        center = QWidget()
        center.setObjectName("center")
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(28, 24, 28, 20)
        center_lay.setSpacing(14)

        # Title row
        title_row = QHBoxLayout()
        self.lbl_profile_title = _mk_label("Parser Profile 1", bold=True, size=cfg.F_2XL)
        self.lbl_profile_title.setStyleSheet(f"color:{cfg.C_TEXT};")
        title_row.addWidget(self.lbl_profile_title)
        title_row.addStretch()
        self.lbl_status = _mk_label("", size=cfg.F_SM, color=cfg.C_GREEN)
        title_row.addWidget(self.lbl_status)
        center_lay.addLayout(title_row)

        # ── Form card: Name + Models
        form_card = self._mk_card()
        form_lay = QVBoxLayout(form_card)
        form_lay.setContentsMargins(22, 18, 22, 18)
        form_lay.setSpacing(14)

        # Parser name
        n_row = QHBoxLayout()
        n_lbl = _mk_label("ชื่อ Parser :", bold=True, size=cfg.F_LG)
        n_lbl.setFixedWidth(160)
        self.inp_name = QLineEdit()
        self.inp_name.setFont(_fnt(cfg.F_LG))
        self.inp_name.setPlaceholderText("เช่น C450i Summary")
        self.inp_name.setFixedHeight(36)
        self.inp_name.setStyleSheet(self._inp_style())
        n_row.addWidget(n_lbl)
        n_row.addWidget(self.inp_name, 1)
        form_lay.addLayout(n_row)

        # Models
        m_row = QHBoxLayout()
        m_lbl = _mk_label("รุ่นที่ Detect :", bold=True, size=cfg.F_LG)
        m_lbl.setFixedWidth(160)
        self.inp_models = QLineEdit()
        self.inp_models.setFont(_fnt(cfg.F_LG))
        self.inp_models.setPlaceholderText('เช่น  c450i, 450i, c550i  (คั่นด้วย ",")')
        self.inp_models.setFixedHeight(36)
        self.inp_models.setStyleSheet(self._inp_style())
        m_row.addWidget(m_lbl)
        m_row.addWidget(self.inp_models, 1)
        form_lay.addLayout(m_row)

        model_hint = _mk_label(
            "ระบุชื่อรุ่น (substring) ที่จะ Match กับชื่อเครื่องในไฟล์ — คั่นด้วยเครื่องหมาย , "
            "หากตรงกัน โปรแกรมจะเลือก Parser นี้นำเข้าอัตโนมัติ",
            size=cfg.F_XS, color=cfg.C_TEXT2,
        )
        model_hint.setWordWrap(True)
        form_lay.addWidget(model_hint)

        # ── ประเภทไฟล์ที่รองรับ ──────────────────────────────────
        form_lay.addWidget(_hline())
        t_row = QHBoxLayout()
        t_row.setSpacing(0)
        t_lbl = _mk_label("ประเภทไฟล์ :", bold=True, size=cfg.F_LG)
        t_lbl.setFixedWidth(160)
        t_row.addWidget(t_lbl)

        self._type_checks = {}   # {key: QCheckBox}
        for key, display, color in PARSER_TYPES:
            cb = QCheckBox(display)
            cb.setFont(_fnt(cfg.F_MD, bold=True))
            cb.setStyleSheet(
                f"QCheckBox {{ color:{color}; spacing:6px; }}"
                f"QCheckBox::indicator {{ width:16px; height:16px; border:2px solid {color};"
                f" border-radius:4px; background:white; }}"
                f"QCheckBox::indicator:checked {{ background:{color}; border-color:{color}; }}"
                f"QCheckBox::indicator:checked::after {{ content:'✓'; }}"
            )
            self._type_checks[key] = cb
            # Connect label checkbox to refresh table
            if key == "label":
                cb.stateChanged.connect(self._on_label_type_changed)
            t_row.addWidget(cb)
            t_row.addSpacing(20)
        t_row.addStretch()
        form_lay.addLayout(t_row)

        type_hint = _mk_label(
            "ระบุประเภทไฟล์ที่ Parser นี้รองรับ — จะแสดงเป็น Badge ในแอพหลัก",
            size=cfg.F_XS, color=cfg.C_TEXT2,
        )
        form_lay.addWidget(type_hint)

        center_lay.addWidget(form_card)

        # ── Table card: Columns + Mapping
        tbl_card = self._mk_card()
        tbl_lay = QVBoxLayout(tbl_card)
        tbl_lay.setContentsMargins(22, 16, 22, 16)
        tbl_lay.setSpacing(10)

        tbl_header_row = QHBoxLayout()
        tbl_header_row.addWidget(_mk_label("คอลัมน์จากไฟล์ & การ Mapping", bold=True, size=cfg.F_LG))
        tbl_header_row.addStretch()
        self.lbl_col_count = _mk_label("", size=cfg.F_XS, color=cfg.C_TEXT2)
        tbl_header_row.addWidget(self.lbl_col_count)
        tbl_lay.addLayout(tbl_header_row)

        tbl_hint = _mk_label(
            "อัพโหลดไฟล์ตัวอย่างก่อน → ตารางจะแสดงทุกคอลัมน์ที่อ่านได้ → เลือก DB Field สำหรับคอลัมน์ที่ต้องการ Mapping  "
            "🔢  หลาย Column เลือก DB Field เดียวกันได้ — ค่าจะถูก บวกรวมกัน อัตโนมัติ",
            size=cfg.F_XS, color=cfg.C_TEXT2,
        )
        tbl_hint.setWordWrap(True)
        tbl_lay.addWidget(tbl_hint)

        self.tbl_cols = QTableWidget()
        self.tbl_cols.setColumnCount(7)
        self.tbl_cols.setHorizontalHeaderLabels([
            "Index", "Header 1", "Header 2", "Header 3", "ค่าตัวอย่าง", "ตัวคูณ", "DB Field (Mapping)"
        ])
        self.tbl_cols.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_cols.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_cols.setAlternatingRowColors(True)
        self.tbl_cols.verticalHeader().setVisible(False)
        self.tbl_cols.setStyleSheet(
            f"QTableWidget {{ border:1px solid {cfg.C_BORDER}; border-radius:6px;"
            f" background:{cfg.C_BG}; gridline-color:{cfg.C_BORDER}; font-size:{cfg.F_MD}pt; }}"
            f"QTableWidget::item {{ padding:4px 8px; }}"
            f"QTableWidget::item:selected {{ background:{cfg.C_ACCENT}18; color:{cfg.C_TEXT}; }}"
            "QTableWidget::item:alternate { background:#F8FAFC; }"
            f"QHeaderView::section {{ background:{cfg.C_CARD}; border:none;"
            f" border-bottom:2px solid {cfg.C_BORDER}; padding:7px 8px;"
            f" font-weight:bold; color:{cfg.C_TEXT2}; font-size:{cfg.F_MD}pt; }}"
        )
        hh = self.tbl_cols.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)    # Index
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)   # Header1
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)   # Header2
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)   # Header3
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)     # Value
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)     # Multiplier
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)     # Mapping
        self.tbl_cols.setColumnWidth(0, 50)
        self.tbl_cols.setColumnWidth(4, 100)
        self.tbl_cols.setColumnWidth(5, 70)
        self.tbl_cols.setColumnWidth(6, 230)
        self.tbl_cols.setMinimumHeight(260)

        tbl_lay.addWidget(self.tbl_cols, 1)
        center_lay.addWidget(tbl_card, 1)

        # Scroll wrapper for normal editor
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(center)

        # Center stack: สลับระหว่าง empty-state (index 0) และ normal editor (index 1)
        self._center_stack = QStackedWidget()
        self._json_drop_panel = _JsonDropPanel()
        self._json_drop_panel.json_dropped.connect(self._do_import_from_path)
        self._center_stack.addWidget(self._json_drop_panel)   # index 0
        self._center_stack.addWidget(scroll)                  # index 1
        root_lay.addWidget(self._center_stack, 1)

    # ─────────────────────────────────────────────────────
    # EMPTY STATE / CENTER STACK
    # ─────────────────────────────────────────────────────
    def _is_empty_state(self) -> bool:
        """True ถ้าทุก profile ยังไม่มีข้อมูล (models ว่าง และ column_map ว่าง)"""
        return all(
            not p.get("models", "").strip() and not p.get("column_map")
            for p in self._profiles
        )

    def _update_center_page(self):
        """สลับ center panel ระหว่าง empty-state (0) และ normal editor (1)"""
        if not hasattr(self, "_center_stack"):
            return
        self._center_stack.setCurrentIndex(0 if self._is_empty_state() else 1)

    # drag & drop ไฟล์ .json ทั่วทั้งหน้าต่าง (นอกจาก _JsonDropPanel เอง)
    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            if any(u.toLocalFile().lower().endswith(".json")
                   for u in e.mimeData().urls()):
                e.acceptProposedAction()
                return
        e.ignore()

    def dropEvent(self, e: QDropEvent):
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".json"):
                self._do_import_from_path(path)
                return

    # ─────────────────────────────────────────────────────
    # STYLE HELPERS
    # ─────────────────────────────────────────────────────
    def _inp_style(self):
        return (
            f"QLineEdit {{ border:1.5px solid {cfg.C_BORDER}; border-radius:6px;"
            f" padding:4px 10px; color:{cfg.C_TEXT}; background:{cfg.C_BG}; }}"
            f"QLineEdit:focus {{ border-color:{cfg.C_ACCENT}; }}"
        )

    def _mk_card(self):
        f = QFrame()
        f.setObjectName("card")
        f.setStyleSheet(
            f"QFrame#card {{ background:{cfg.C_CARD}; border:1px solid {cfg.C_BORDER};"
            f" border-radius:10px; }}"
        )
        return f

    def _sidebar_hline(self):
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet("color:rgba(255,255,255,0.15); margin:2px 0px;")
        return f

    def _qss(self):
        return (
            f"QMainWindow, QWidget {{ background:{cfg.C_BG}; color:{cfg.C_TEXT};"
            f" font-family:'{cfg.QSS_FONT_FAMILY}'; font-size:{cfg.F_MD}pt; }}"
            f"QFrame#sidebar {{ background:{cfg.C_SIDEBAR}; }}"
            f"QWidget#center {{ background:{cfg.C_BG}; }}"
            f"QScrollArea {{ background:{cfg.C_BG}; border:none; }}"
        )

    # ─────────────────────────────────────────────────────
    # PROFILE LIST
    # ─────────────────────────────────────────────────────
    @staticmethod
    def _type_badge_text(p):
        """สร้าง text badge สำหรับ types ใน sidebar"""
        TYPE_ICON = {"summary": "📋", "user": "👤", "production": "🏭"}
        active = p.get("types", [])
        return "  " + "".join(TYPE_ICON[k] for k in ("summary", "user", "production") if k in active)

    def _add_profile_item(self, p):
        name = p.get("name", f"Profile {p['slot']}")
        badges = self._type_badge_text(p)
        item = QListWidgetItem(f"  {p['slot']:2d}.  {name}{badges}")
        item.setSizeHint(QSize(0, 34))
        self.profile_list.addItem(item)

    def _refresh_list_item(self, idx):
        p = self._profiles[idx]
        name = p.get("name", f"Profile {p['slot']}")
        badges = self._type_badge_text(p)
        item = self.profile_list.item(idx)
        if item:
            item.setText(f"  {p['slot']:2d}.  {name}{badges}")

    # ─────────────────────────────────────────────────────
    # PROFILE SELECT / POPULATE
    # ─────────────────────────────────────────────────────
    def _select_profile(self, idx):
        if not (0 <= idx < len(self._profiles)):
            return
        self._current_idx = idx
        p = self._profiles[idx]

        self.lbl_profile_title.setText(f"Parser Profile {p['slot']}")
        self.inp_name.setText(p.get("name", ""))
        self.inp_models.setText(p.get("models", ""))

        # restore type checkboxes
        active_types = p.get("types", [])
        for key, cb in self._type_checks.items():
            cb.setChecked(key in active_types)

        col_map = p.get("column_map", {})
        # รองรับทั้งรูปแบบเก่า {key: int} และใหม่ {key: [int, ...]}
        col_to_key = {}
        for db_key, val in col_map.items():
            if isinstance(val, list):
                for c in val:
                    if isinstance(c, int) and c >= 0:
                        col_to_key[c] = db_key
            elif isinstance(val, int) and val >= 0:
                col_to_key[val] = db_key   # backward compat

        headers = self._headers
        headers2 = self._headers2
        headers3 = self._headers3
        values   = self._values
        # Label: นับ rows; Standard: นับ columns
        n = len(self._all_file_rows) if (self._file_is_label and self._all_file_rows) \
            else max(len(headers), len(values), 0)

        if n == 0 and col_map:
            all_cols = []
            for val in col_map.values():
                if isinstance(val, list):
                    all_cols.extend(c for c in val if isinstance(c, int) and c >= 0)
                elif isinstance(val, int) and val >= 0:
                    all_cols.append(val)
            max_col = max(all_cols, default=-1)
            n = max_col + 1 if max_col >= 0 else 0

        self._setup_table_columns()
        self._populate_table(n, headers, headers2, headers3, values, col_to_key)
        self.lbl_status.setText("")

    def _setup_table_columns(self):
        """ปรับ table columns ตามรูปแบบของไฟล์ที่โหลดจริง (ไม่ใช่ checkbox)"""
        label_enabled = self._file_is_label

        if label_enabled:
            # Label format: 6 columns
            self.tbl_cols.setColumnCount(6)
            self.tbl_cols.setHorizontalHeaderLabels([
                "Index", "Category", "Type", "ค่าตัวอย่าง", "ตัวคูณ", "DB Field (Mapping)"
            ])
            hh = self.tbl_cols.horizontalHeader()
            hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)     # Index
            hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)   # Category
            hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)   # Type
            hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)     # Value
            hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)     # Multiplier
            hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)     # Mapping
            self.tbl_cols.setColumnWidth(0, 50)
            self.tbl_cols.setColumnWidth(3, 100)
            self.tbl_cols.setColumnWidth(4, 70)
            self.tbl_cols.setColumnWidth(5, 230)
        else:
            # Standard format: 7 columns
            self.tbl_cols.setColumnCount(7)
            self.tbl_cols.setHorizontalHeaderLabels([
                "Index", "Header 1", "Header 2", "Header 3", "ค่าตัวอย่าง", "ตัวคูณ", "DB Field (Mapping)"
            ])
            hh = self.tbl_cols.horizontalHeader()
            hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)    # Index
            hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)   # Header1
            hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)   # Header2
            hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)   # Header3
            hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)     # Value
            hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)     # Multiplier
            hh.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)     # Mapping
            self.tbl_cols.setColumnWidth(0, 50)
            self.tbl_cols.setColumnWidth(4, 100)
            self.tbl_cols.setColumnWidth(5, 70)
            self.tbl_cols.setColumnWidth(6, 230)

    def _populate_table(self, n_cols, headers, headers2, headers3, values, col_to_key, col_multipliers=None):
        """สร้างตาราง — ปรับ columns ตามว่า Label enabled หรือเปล่า"""
        if col_multipliers is None:
            col_multipliers = {}
        self.tbl_cols.setRowCount(0)
        self.lbl_col_count.setText(f"{n_cols} คอลัมน์" if n_cols else "")

        # รูปแบบตารางตามไฟล์ที่โหลดจริง — Label checkbox ไม่เกี่ยวกับ layout ตาราง
        label_enabled = self._file_is_label

        for i in range(n_cols):
            self.tbl_cols.insertRow(i)
            self.tbl_cols.setRowHeight(i, 30)

            existing_key = col_to_key.get(i, "")
            bg = QColor(f"{cfg.C_ACCENT}18") if existing_key else None

            def _cell(text, color=None, bold=False, center=False, col_idx=None):
                it = QTableWidgetItem(text)
                it.setForeground(QColor(color or cfg.C_TEXT))
                if bold:
                    it.setFont(_fnt(cfg.F_MD, bold=True))
                if center:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if bg:
                    it.setBackground(bg)
                return it

            if label_enabled:
                # Label format: Extract from all_file_rows[i]
                row_data = self._all_file_rows[i] if i < len(self._all_file_rows) else ["", "", ""]
                
                # Col 0: Index
                self.tbl_cols.setItem(i, 0, _cell(str(i), cfg.C_TEXT2, center=True))
                # Col 1: Category (row_data[0])
                self.tbl_cols.setItem(i, 1, _cell(row_data[0] if len(row_data) > 0 else ""))
                # Col 2: Type (row_data[1])
                self.tbl_cols.setItem(i, 2, _cell(row_data[1] if len(row_data) > 1 else "", cfg.C_TEXT2))
                # Col 3: Value (row_data[2])
                self.tbl_cols.setItem(i, 3, _cell(
                    row_data[2] if len(row_data) > 2 else "",
                    color=cfg.C_ACCENT, bold=True, center=True,
                ))
                # Col 4: Multiplier
                mult_cmb = QComboBox()
                mult_cmb.setFont(_fnt(cfg.F_MD))
                mult_cmb.setStyleSheet(
                    f"QComboBox {{ border:1px solid {cfg.C_BORDER}; border-radius:4px;"
                    f" padding:2px 6px; background:{cfg.C_BG}; color:{cfg.C_TEXT}; }}"
                    "QComboBox::drop-down { border:none; width:18px; }"
                    f"QComboBox QAbstractItemView {{ border:1px solid {cfg.C_BORDER};"
                    f" selection-background-color:{cfg.C_ACCENT}; selection-color:white; }}"
                )
                mult_options = ["1", "0.5", "2", "5", "10", "0.1"]
                for m_opt in mult_options:
                    mult_cmb.addItem(m_opt, m_opt)
                saved_mult = col_multipliers.get(i, 1.0)
                mult_cmb.setCurrentIndex(0)
                for j in range(mult_cmb.count()):
                    if float(mult_cmb.itemData(j)) == float(saved_mult):
                        mult_cmb.setCurrentIndex(j)
                        break
                self.tbl_cols.setCellWidget(i, 4, mult_cmb)

                # Col 5: Mapping dropdown
                cmb = QComboBox()
                cmb.setFont(_fnt(cfg.F_MD))
                cmb.setStyleSheet(
                    f"QComboBox {{ border:1px solid {cfg.C_BORDER}; border-radius:4px;"
                    f" padding:2px 6px; background:{cfg.C_BG}; color:{cfg.C_TEXT}; }}"
                    "QComboBox::drop-down { border:none; width:18px; }"
                    f"QComboBox QAbstractItemView {{ border:1px solid {cfg.C_BORDER};"
                    f" selection-background-color:{cfg.C_ACCENT}; selection-color:white; }}"
                )
                for lbl, key in DB_FIELDS:
                    cmb.addItem(lbl, key)
                for j in range(cmb.count()):
                    if cmb.itemData(j) == existing_key:
                        cmb.setCurrentIndex(j)
                        break
                cmb.currentIndexChanged.connect(lambda idx, r=i: self._on_db_field_changed(r, mult_cmb))
                self.tbl_cols.setCellWidget(i, 5, cmb)

            else:
                # Standard format: 7 columns
                # Col 0: Index
                self.tbl_cols.setItem(i, 0, _cell(str(i), cfg.C_TEXT2, center=True))
                # Col 1: Header1
                self.tbl_cols.setItem(i, 1, _cell(headers[i] if i < len(headers) else ""))
                # Col 2: Header2
                self.tbl_cols.setItem(i, 2, _cell(headers2[i] if i < len(headers2) else "", cfg.C_TEXT2))
                # Col 3: Header3
                self.tbl_cols.setItem(i, 3, _cell(headers3[i] if i < len(headers3) else "", cfg.C_TEXT2))
                # Col 4: Value
                self.tbl_cols.setItem(i, 4, _cell(
                    values[i] if i < len(values) else "",
                    color=cfg.C_ACCENT, bold=True, center=True,
                ))

                # Col 5: Multiplier dropdown
                mult_cmb = QComboBox()
                mult_cmb.setFont(_fnt(cfg.F_MD))
                mult_cmb.setStyleSheet(
                    f"QComboBox {{ border:1px solid {cfg.C_BORDER}; border-radius:4px;"
                    f" padding:2px 6px; background:{cfg.C_BG}; color:{cfg.C_TEXT}; }}"
                    "QComboBox::drop-down { border:none; width:18px; }"
                    f"QComboBox QAbstractItemView {{ border:1px solid {cfg.C_BORDER};"
                    f" selection-background-color:{cfg.C_ACCENT}; selection-color:white; }}"
                )
                mult_options = ["1", "0.5", "2", "5", "10", "0.1"]
                for m_opt in mult_options:
                    mult_cmb.addItem(m_opt, m_opt)
                saved_mult = col_multipliers.get(i, 1.0)
                mult_cmb.setCurrentIndex(0)
                for j in range(mult_cmb.count()):
                    if float(mult_cmb.itemData(j)) == float(saved_mult):
                        mult_cmb.setCurrentIndex(j)
                        break
                self.tbl_cols.setCellWidget(i, 5, mult_cmb)

                # Col 6: Mapping dropdown
                cmb = QComboBox()
                cmb.setFont(_fnt(cfg.F_MD))
                cmb.setStyleSheet(
                    f"QComboBox {{ border:1px solid {cfg.C_BORDER}; border-radius:4px;"
                    f" padding:2px 6px; background:{cfg.C_BG}; color:{cfg.C_TEXT}; }}"
                    "QComboBox::drop-down { border:none; width:18px; }"
                    f"QComboBox QAbstractItemView {{ border:1px solid {cfg.C_BORDER};"
                    f" selection-background-color:{cfg.C_ACCENT}; selection-color:white; }}"
                )
                for lbl, key in DB_FIELDS:
                    cmb.addItem(lbl, key)
                for j in range(cmb.count()):
                    if cmb.itemData(j) == existing_key:
                        cmb.setCurrentIndex(j)
                        break
                cmb.currentIndexChanged.connect(lambda idx, r=i: self._on_db_field_changed(r, mult_cmb))
                self.tbl_cols.setCellWidget(i, 6, cmb)

    def _on_db_field_changed(self, row: int, mult_cmb):
        """Handle DB field changes - auto-populate Color-meter and BW-meter for label type"""
        label_enabled = self._file_is_label
        map_col = 5 if label_enabled else 6
        
        # Get the DB field dropdown for this row
        cmb = self.tbl_cols.cellWidget(row, map_col)
        if not isinstance(cmb, QComboBox):
            return
        
        selected_field = cmb.currentData()
        
        if label_enabled and selected_field == "color_meter":
            # Auto-set multiplier for color_meter if needed
            pass
        elif label_enabled and selected_field == "bw_meter":
            # Auto-set multiplier for bw_meter if needed
            pass

    def _collect_mapping(self):
        """
        อ่าน mapping จากตาราง → คืน ({db_field_key: [col_index, ...]}, {col_index: multiplier})
        ถ้าหลาย column เลือก DB field เดียวกัน จะเก็บเป็น list → บวกกันตอนใช้งาน
        """
        mapping = {}
        multipliers = {}
        
        label_enabled = self._file_is_label

        # For label format: multiplier at col 4, mapping at col 5
        # For standard format: multiplier at col 5, mapping at col 6
        mult_col = 4 if label_enabled else 5
        map_col = 5 if label_enabled else 6
        
        for row in range(self.tbl_cols.rowCount()):
            # Multiplier
            mult_cmb = self.tbl_cols.cellWidget(row, mult_col)
            if isinstance(mult_cmb, QComboBox):
                mult_val = mult_cmb.currentData()
                try:
                    multipliers[row] = float(mult_val)
                except (ValueError, TypeError):
                    multipliers[row] = 1.0
            
            # Mapping
            cmb = self.tbl_cols.cellWidget(row, map_col)
            if isinstance(cmb, QComboBox):
                key = cmb.currentData()
                if key:
                    mapping.setdefault(key, []).append(row)
        return mapping, multipliers

    # ─────────────────────────────────────────────────────
    # ACTIONS
    # ─────────────────────────────────────────────────────
    def _upload_file(self, path: str = ""):
        """รับ path จาก DropZone signal หรือ drag & drop"""
        if not path:
            return
        try:
            headers, headers2, headers3, values, all_data_rows, machine, serial, date_str = read_meter_file(path)
            
            # Store data
            self._headers = headers[:]
            self._headers2 = headers2[:]
            self._headers3 = headers3[:]
            self._values = values[:]
            
            # Store all data rows from file (for row selection)
            self._all_file_rows = all_data_rows if all_data_rows else [values]
            
            # Build available rows list for selection
            # For Label format, show readable labels; for standard, show "Data Row N"
            self._available_rows = []
            for i, row in enumerate(self._all_file_rows, start=1):
                # Try to create readable label: if row has 3+ items, use first 2
                # (especially for Label format: "Copy - Total", "Printer - Full Color")
                if len(row) >= 2:
                    label = f"{row[0]} - {row[1]}"
                else:
                    label = f"Data Row {i}"
                self._available_rows.append((label, row))
            
            # Update row selector combobox
            self.cmb_header_row.blockSignals(True)
            self.cmb_header_row.clear()
            for label, _ in self._available_rows:
                self.cmb_header_row.addItem(label)
            self.cmb_header_row.setCurrentIndex(0)
            self.cmb_header_row.blockSignals(False)
            self._selected_row_idx = 0
            self._reading_mode = 0
            self._file_is_label = "Label" in machine  # ตรวจจากชื่อเครื่องจริงๆ

            fname = Path(path).name
            self.drop_zone.set_filename(fname)
            self.lbl_status.setText(
                f"✓ อ่านไฟล์สำเร็จ  |  {machine}  |  SN: {serial}"
            )
            self.lbl_status.setStyleSheet(f"color:{cfg.C_GREEN};")

            # refresh table ด้วย mapping เดิม (ถ้ามี) — รองรับทั้ง {key:int} และ {key:[int,...]}
            p = self._profiles[self._current_idx]
            col_map = p.get("column_map", {})
            col_multipliers = p.get("column_multipliers", {})
            col_to_key = {}
            for db_key, val in col_map.items():
                if isinstance(val, list):
                    for c in val:
                        if isinstance(c, int) and c >= 0:
                            col_to_key[c] = db_key
                elif isinstance(val, int) and val >= 0:
                    col_to_key[val] = db_key
            # Label: นับ rows; Standard: นับ columns
            n = len(self._all_file_rows) if self._file_is_label else max(len(headers), len(values))
            self._setup_table_columns()
            self._populate_table(n, headers, headers2, headers3, values, col_to_key, col_multipliers)
            
            # Update reading mode UI
            self.cmb_reading_mode.blockSignals(True)
            self.cmb_reading_mode.setCurrentIndex(0)
            self.cmb_reading_mode.blockSignals(False)
            self._update_reading_mode_ui()

        except Exception as e:
            QMessageBox.critical(self, "อ่านไฟล์ไม่ได้", with_diagnostic(str(e), e, "Parser / อ่านไฟล์ไม่ได้"))
            self.lbl_status.setText(f"✗ {e}")
            self.lbl_status.setStyleSheet(f"color:{cfg.C_RED};")

    def _save_current(self):
        idx = self._current_idx
        p = self._profiles[idx]
        p["name"]       = self.inp_name.text().strip() or f"Parser Profile {p['slot']}"
        p["models"]     = self.inp_models.text().strip()
        p["types"]      = [k for k, cb in self._type_checks.items() if cb.isChecked()]
        mapping, multipliers = self._collect_mapping()
        p["column_map"] = mapping
        p["column_multipliers"] = multipliers

        save_profiles(self._profiles)
        self._refresh_list_item(idx)
        self._update_center_page()

        self.lbl_status.setText("💾  บันทึกแล้ว")
        self.lbl_status.setStyleSheet(f"color:{cfg.C_GREEN};")

    # ─────────────────────────────────────────────────────
    # READING MODE HANDLERS
    # ─────────────────────────────────────────────────────
    def _on_label_type_changed(self):
        """Label checkbox บันทึกประเภทเท่านั้น — layout ตารางตามไฟล์ที่โหลดจริง"""
        pass  # ไม่ refresh table (เพื่อป้องกัน layout ผิดเพี้ยนเมื่อโหลดไฟล์ต่างประเภท)
    
    def _on_reading_mode_changed(self, index):
        """User changed reading mode: Data Row (0) vs Header Row (1)"""
        self._reading_mode = index
        self._update_reading_mode_ui()
        self._apply_reading_mode()
    
    def _on_header_row_selected(self, index):
        """User selected which row to read from"""
        self._selected_row_idx = index
        self._apply_reading_mode()
    
    def _update_reading_mode_ui(self):
        """Show/hide row selector and update available options based on mode"""
        is_header_mode = (self._reading_mode == 1)
        self.lbl_row_selector.setVisible(is_header_mode)
        self.cmb_header_row.setVisible(is_header_mode)
        
        # Update combobox options based on mode
        self.cmb_header_row.blockSignals(True)
        self.cmb_header_row.clear()
        
        if is_header_mode:
            # Header row mode - show h1, h2, h3
            self.lbl_row_selector.setText("Select Header Row:")
            self._available_rows = [
                ("Header Row 1 (h1)", self._headers),
                ("Header Row 2 (h2)", self._headers2),
                ("Header Row 3 (h3)", self._headers3),
            ]
        else:
            # Data row mode - show available data rows from file
            self.lbl_row_selector.setText("Select Data Row:")
            self._available_rows = [
                (f"Data Row {i}", row) 
                for i, row in enumerate(self._all_file_rows, start=1)
            ]
        
        for label, _ in self._available_rows:
            self.cmb_header_row.addItem(label)
        
        self.cmb_header_row.setCurrentIndex(0)
        self.cmb_header_row.blockSignals(False)
        self._selected_row_idx = 0
    
    def _apply_reading_mode(self):
        """Apply the current reading mode - use appropriate row as values"""
        if not self._all_file_rows:
            return
        
        if self._reading_mode == 0:  # Data Row mode (normal)
            # Use selected row from file
            if 0 <= self._selected_row_idx < len(self._all_file_rows):
                self._values = self._all_file_rows[self._selected_row_idx][:]
                label = f"Data Row {self._selected_row_idx + 1}"
                status = f"📊 Using: {label}"
            else:
                self._values = self._all_file_rows[0][:]
                status = "📊 Using: Data Row 1 (default)"
        else:  # Header Row mode (transposed)
            # User explicitly selected a row to read from
            if 0 <= self._selected_row_idx < len(self._available_rows):
                _, row_data = self._available_rows[self._selected_row_idx]
                self._values = row_data[:]
                label = self._available_rows[self._selected_row_idx][0]
                status = f"🔄 Reading from: {label}"
            else:
                self._values = self._all_file_rows[0][:]
                status = "📊 Using: Data Row 1 (default)"
        
        self.lbl_status.setText(status)
        self.lbl_status.setStyleSheet(f"color:{cfg.C_TEXT3};")
        self._refresh_table_display()


    def _refresh_table_display(self):
        """อัปเดตตารางให้แสดงข้อมูลปัจจุบัน (respects current reading mode)"""
        if self._profiles and self._current_idx < len(self._profiles):
            p = self._profiles[self._current_idx]
            col_map = p.get("column_map", {})
            col_multipliers = p.get("column_multipliers", {})
            col_to_key = {}
            for db_key, val in col_map.items():
                if isinstance(val, list):
                    for c in val:
                        if isinstance(c, int) and c >= 0:
                            col_to_key[c] = db_key
                elif isinstance(val, int) and val >= 0:
                    col_to_key[val] = db_key
            # Use all_file_rows length (not header length)
            n = len(self._all_file_rows) if (self._file_is_label and self._all_file_rows) \
                else max(len(self._headers), len(self._values), 0)
            self._setup_table_columns()
            self._populate_table(n, self._headers, self._headers2, self._headers3, self._values, col_to_key, col_multipliers)

    def _clear_current(self):
        """Clear current profile data"""
        reply = QMessageBox.question(
            self, "ยืนยัน",
            f"เคลียร์ข้อมูล Profile {self._current_idx + 1} ทั้งหมด?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        idx = self._current_idx
        self._profiles[idx] = _empty_profile(idx + 1)
        save_profiles(self._profiles)
        self._refresh_list_item(idx)
        self._select_profile(idx)
        self._update_center_page()
        self.lbl_status.setText("🗑  เคลียร์แล้ว")
        self.lbl_status.setStyleSheet(f"color:{cfg.C_ORANGE};")

    # ─────────────────────────────────────────────────────
    # ADD / REMOVE PARSER
    # ─────────────────────────────────────────────────────
    def _add_parser(self):
        """เพิ่ม Parser Profile ใหม่"""
        slot = len(self._profiles) + 1
        new_p = _empty_profile(slot)
        self._profiles.append(new_p)
        self._add_profile_item(new_p)
        save_profiles(self._profiles)
        self.profile_list.setCurrentRow(len(self._profiles) - 1)

    def _remove_parser(self):
        """ลบ Parser Profile ที่เลือกอยู่"""
        if len(self._profiles) <= 1:
            QMessageBox.warning(self, "ไม่สามารถลบได้",
                                "ต้องมี Parser อย่างน้อย 1 รายการ")
            return
        idx = self._current_idx
        p = self._profiles[idx]
        reply = QMessageBox.question(
            self, "ยืนยันการลบ",
            f"ลบ Parser Profile {p['slot']}: «{p.get('name', '')}» ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._profiles.pop(idx)
        # Re-number slots
        for i, prof in enumerate(self._profiles):
            prof["slot"] = i + 1
        # Rebuild list widget
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for prof in self._profiles:
            self._add_profile_item(prof)
        self.profile_list.blockSignals(False)
        save_profiles(self._profiles)
        new_idx = min(idx, len(self._profiles) - 1)
        self.profile_list.setCurrentRow(new_idx)
        self._select_profile(new_idx)
        self.lbl_status.setText("🗑  ลบ Parser แล้ว")
        self.lbl_status.setStyleSheet(f"color:{cfg.C_ORANGE};")

    # ─────────────────────────────────────────────────────
    # IMPORT / EXPORT PARSERS
    # ─────────────────────────────────────────────────────
    def _import_parsers(self):
        """นำเข้า Parser Profiles จากไฟล์ JSON (เปิด dialog เลือกไฟล์)"""
        path, _ = QFileDialog.getOpenFileName(
            self, "นำเข้า Parser Profiles",
            str(Path.home()), "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        self._do_import_from_path(path)

    def _do_import_from_path(self, path: str):
        """นำเข้า Parser Profiles จาก path ไฟล์ JSON โดยตรง"""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            incoming = data.get("profiles", [])
            if not incoming:
                QMessageBox.warning(self, "ไฟล์ไม่ถูกต้อง",
                                    "ไม่พบข้อมูล profiles ในไฟล์นี้")
                return
            reply = QMessageBox.question(
                self, "ยืนยันการนำเข้า",
                f"พบ {len(incoming)} Parser Profile\n"
                f"แทนที่ข้อมูลทั้งหมดในปัจจุบัน ({len(self._profiles)} Profile) ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._profiles = []
            for i, p in enumerate(incoming):
                self._profiles.append({**_empty_profile(i + 1), **p, "slot": i + 1})
            save_profiles(self._profiles)
            self.profile_list.blockSignals(True)
            self.profile_list.clear()
            for p in self._profiles:
                self._add_profile_item(p)
            self.profile_list.blockSignals(False)
            self.profile_list.setCurrentRow(0)
            self._select_profile(0)
            self._update_center_page()
            self.lbl_status.setText(f"📥  นำเข้าสำเร็จ — {len(self._profiles)} Profiles")
            self.lbl_status.setStyleSheet(f"color:{cfg.C_GREEN};")
        except Exception as e:
            QMessageBox.critical(self, "นำเข้าไม่ได้", with_diagnostic(str(e), e, "Parser / นำเข้าไม่ได้"))

    def _export_parsers(self):
        """ส่งออก Parser Profiles ทั้งหมดเป็นไฟล์ JSON"""
        # ดึงชื่อ Parser ที่เลือกอยู่มาใช้เป็นชื่อไฟล์ default
        cur_name = self._profiles[self._current_idx].get("name", "").strip()
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in cur_name).strip()
        default_name = f"parser_{safe_name}.json" if safe_name else "parser_profiles_export.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "ส่งออก Parser Profiles",
            str(Path.home() / default_name),
            "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps({"profiles": self._profiles}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            QMessageBox.information(
                self, "ส่งออกสำเร็จ",
                f"บันทึก {len(self._profiles)} Parser Profiles แล้ว:\n{path}"
            )
            self.lbl_status.setText("📤  ส่งออกสำเร็จ")
            self.lbl_status.setStyleSheet(f"color:{cfg.C_GREEN};")
        except Exception as e:
            QMessageBox.critical(self, "ส่งออกไม่ได้", with_diagnostic(str(e), e, "Parser / ส่งออกไม่ได้"))

# ENTRY POINT
# ════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = ParserEditorWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()


