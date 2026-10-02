# ═══════════════════════════════════════════════════════════
# widgets.py  —  Widget และ helper ที่ใช้ซ้ำทั่วโปรแกรม
# ═══════════════════════════════════════════════════════════

from ui.styles import surfaces as surfaces_styles
from ui.styles import text as text_styles
from ui.styles import tables as tables_styles

from PyQt6.QtWidgets import (
    QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QScrollBar, QWidget,
    QStyledItemDelegate, QCheckBox, QSizePolicy, QAbstractItemView,
)
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui  import QColor, QPainter, QPen
from ui.styles.tokens import (
    C_ACCENT,
    C_GREEN,
    C_TEXT,
    C_TEXT3,
    F_2XL,
    F_LG,
    F_MD,
    F_NUM,
    F_SM,
    F_XL,
    F_XS,
)

# ══════════════════════════════════════════════════════════
# FONT HELPER
# ══════════════════════════════════════════════════════════
from ui.styles.typography import fnt as fnt

# ══════════════════════════════════════════════════════════
# FORMAT HELPERS
# ══════════════════════════════════════════════════════════
def fn(n) -> str:
    """แสดงตัวเลขพร้อม comma เช่น 1,234 หรือ — ถ้าไม่มีค่า"""
    if n is None: return "—"
    try: return f"{int(n):,}"
    except: return "—"

def fd(n) -> str:
    """แสดงส่วนต่าง เช่น +123 หรือ ±0"""
    if n is None: return "—"
    if n == 0:    return "±0"
    return f"+{n:,}"

def fmt_baht(n) -> str:
    """แสดงจำนวนเงิน เช่น ฿1,234.50"""
    if n is None: return "—"
    try: return f"฿{n:,.2f}"
    except: return "—"

# ══════════════════════════════════════════════════════════
# LAYOUT HELPERS
# ══════════════════════════════════════════════════════════
def hline() -> QFrame:
    """เส้นแบ่งแนวนอน"""
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(surfaces_styles.divider())
    return f


def sec_title(text: str) -> QLabel:
    """หัวข้อหน้า — ขนาด F_2XL bold"""
    l = QLabel(text)
    l.setFont(fnt(F_2XL, True))
    l.setStyleSheet(surfaces_styles.section_title())
    return l

def sub_title(text: str) -> QLabel:
    """หัวข้อย่อย — ขนาด F_XL bold"""
    l = QLabel(text)
    l.setFont(fnt(F_XL, True))
    l.setStyleSheet(text_styles.label(C_TEXT))
    return l

# ══════════════════════════════════════════════════════════
# CARD WIDGETS
# ══════════════════════════════════════════════════════════
def mk_card(top_color: str = None) -> QFrame:
    """สร้าง card สีขาว ขอบมน — top_color ใส่เส้นสีด้านบน"""
    f = QFrame(); f.setObjectName("card")
    if top_color:
        f.setStyleSheet(surfaces_styles.accent_card(top_color))
    return f

def mk_preview_card() -> QFrame:
    """card สีเหลืองอ่อน ใช้แสดง Preview ก่อนบันทึก"""
    f = QFrame(); f.setObjectName("preview_card")
    return f

def mk_warn_card() -> QFrame:
    """card สีแดงอ่อน ใช้แสดงคำเตือน"""
    f = QFrame(); f.setObjectName("warn_card")
    return f

# ══════════════════════════════════════════════════════════
# STAT CARD WIDGET
# ══════════════════════════════════════════════════════════
class StatCard(QFrame):
    """
    การ์ดแสดงตัวเลขสถิติ
    ┌──────────────┐
    │ Title        │
    │ 1,234        │  ← ตัวเลขใหญ่ (สี color)
    │ +56          │  ← ส่วนต่าง (เขียว/เทา)
    └──────────────┘
    """
    def __init__(self, title: str, color: str = C_ACCENT, parent=None, compact=False):
        super().__init__(parent)
        self.setObjectName("stat_card")
        lay = QVBoxLayout(self)
        if compact:
            lay.setContentsMargins(10, 8, 10, 8)
            lay.setSpacing(2)
        else:
            lay.setContentsMargins(16, 14, 16, 14)
            lay.setSpacing(4)

        self.lbl_title = QLabel(title)
        self.lbl_title.setFont(fnt(F_XS if compact else F_SM))
        self.lbl_title.setStyleSheet(text_styles.label(C_TEXT3))
        self.lbl_title.setWordWrap(True)

        self.lbl_val = QLabel("—")
        self.lbl_val.setFont(fnt(F_XL if compact else F_NUM, True, not compact))
        self.lbl_val.setStyleSheet(text_styles.label(color))

        self.lbl_diff = QLabel("")
        self.lbl_diff.setFont(fnt(F_XS if compact else F_MD))
        self.lbl_diff.setStyleSheet(text_styles.label(C_TEXT3))

        lay.addWidget(self.lbl_title)
        lay.addWidget(self.lbl_val)
        lay.addWidget(self.lbl_diff)

    def set_value(self, val, diff=None):
        """อัปเดตค่าและส่วนต่าง"""
        self.lbl_val.setText(fn(val))
        if diff is not None:
            self.lbl_diff.setText(fd(diff))
            color = C_GREEN if (isinstance(diff,(int,float)) and diff > 0) else C_TEXT3
            self.lbl_diff.setStyleSheet(text_styles.label(color))
        else:
            self.lbl_diff.setText("")

    def set_baht(self, val):
        """แสดงเป็นจำนวนเงิน"""
        self.lbl_val.setText(fmt_baht(val))

# ══════════════════════════════════════════════════════════
# BUTTON HELPERS
# ══════════════════════════════════════════════════════════
def btn(text: str, style: str = "primary", parent=None) -> QPushButton:
    """
    สร้างปุ่ม style ต่างๆ:
    style = "primary" / "outline" / "danger" / "success" / "warning"
    """
    b = QPushButton(text, parent)
    b.setObjectName(f"btn_{style}")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class VisibleCheckBox(QCheckBox):
    """Checkbox with a platform-independent visible empty and checked state."""

    _indicator_size = 18
    _spacing = 8

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self):
        base = super().sizeHint()
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(
            max(base.width(), self._indicator_size + self._spacing + text_width + 4),
            max(base.height(), self._indicator_size + 4),
        )

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = self._indicator_size
        x = 1.0
        y = (self.height() - size) / 2.0
        enabled = self.isEnabled()
        checked = self.checkState() != Qt.CheckState.Unchecked
        border = QColor("#64748B" if enabled else "#CBD5E1")
        fill = QColor("#0879C9" if enabled else "#94A3B8")

        painter.setPen(QPen(fill if checked else border, 2))
        painter.setBrush(fill if checked else QColor("#FFFFFF"))
        painter.drawRoundedRect(QRectF(x, y, size, size), 3, 3)

        if self.checkState() == Qt.CheckState.Checked:
            painter.setPen(QPen(QColor("#FFFFFF"), 2.2))
            painter.drawLine(
                QPointF(x + 4.2, y + 9.4),
                QPointF(x + 7.6, y + 12.6),
            )
            painter.drawLine(
                QPointF(x + 7.6, y + 12.6),
                QPointF(x + 14.2, y + 5.6),
            )
        elif self.checkState() == Qt.CheckState.PartiallyChecked:
            painter.setPen(QPen(QColor("#FFFFFF"), 2.2))
            painter.drawLine(
                QPointF(x + 4.2, y + 9.0),
                QPointF(x + 13.8, y + 9.0),
            )

        text_x = int(x + size + self._spacing)
        text_width = max(0, self.width() - text_x)
        text = self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, text_width
        )
        painter.setPen(
            self.palette().color(
                self.foregroundRole()
                if enabled
                else self.backgroundRole()
            )
            if enabled
            else QColor("#94A3B8")
        )
        painter.setFont(self.font())
        painter.drawText(
            text_x,
            0,
            text_width,
            self.height(),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

# ══════════════════════════════════════════════════════════
# TABLE HELPERS
# ══════════════════════════════════════════════════════════
def tbl_item(text: str,
             align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
             color: str = None,
             bold: bool = False,
             mono: bool = False) -> QTableWidgetItem:
    """สร้าง QTableWidgetItem พร้อม style"""
    item = QTableWidgetItem(str(text))
    item.setTextAlignment(align)
    if color:
        item.setForeground(QColor(color))
    if bold or mono:
        item.setFont(fnt(F_LG if bold else F_MD, bold, mono))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


# ══════════════════════════════════════════════════════════
# FROZEN COLUMN TABLE — คอลัมน์ซ้าย/ขวา freeze, กลาง scroll
# ══════════════════════════════════════════════════════════

class FrozenColTable(QWidget):
    """Table with frozen first and last columns; middle columns scroll horizontally."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._n_cols = 0

        # Outer vertical layout: row1 = tables, row2 = horizontal scrollbar
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._left  = QTableWidget()
        self._mid   = QTableWidget()
        self._right = QTableWidget()

        _tbl_style = (
            tables_styles.DETAIL_TABLE
        )
        self._row_h = 30  # ความสูง row คงที่
        for t in (self._left, self._mid, self._right):
            t.verticalHeader().setVisible(False)
            t.verticalHeader().setDefaultSectionSize(self._row_h)
            t.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            t.setStyleSheet(_tbl_style)

        # ซ่อน scrollbar ทั้งหมดในตัวตาราง — ใช้ scrollbar ภายนอกแทน
        for t in (self._left, self._mid, self._right):
            t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            t.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Shared vertical scrollbar
        self._vsb = QScrollBar(Qt.Orientation.Vertical)
        self._scroll_guard = False
        self._mid.verticalScrollBar().rangeChanged.connect(self._sync_range)
        self._vsb.valueChanged.connect(self._on_vsb)
        for t in (self._left, self._mid, self._right):
            t.verticalScrollBar().valueChanged.connect(self._on_tbl_scroll)

        lay.addWidget(self._left)
        lay.addWidget(self._mid, 1)
        lay.addWidget(self._right)
        lay.addWidget(self._vsb)

        # External horizontal scrollbar (อยู่ใต้ตาราง ไม่กินพื้นที่ content area)
        self._hsb = QScrollBar(Qt.Orientation.Horizontal)
        self._hsb_left_sp = QWidget()
        self._hsb_right_sp = QWidget()
        self._hscroll_guard = False

        self._mid.horizontalScrollBar().rangeChanged.connect(self._sync_hrange)
        self._hsb.valueChanged.connect(self._on_hsb)
        self._mid.horizontalScrollBar().valueChanged.connect(self._on_mid_hscroll)

        hsb_row = QHBoxLayout()
        hsb_row.setContentsMargins(0, 0, 0, 0)
        hsb_row.setSpacing(0)
        hsb_row.addWidget(self._hsb_left_sp)
        hsb_row.addWidget(self._hsb, 1)
        hsb_row.addWidget(self._hsb_right_sp)

        outer.addLayout(lay, 1)
        outer.addLayout(hsb_row)

    # ── scroll sync (vertical) ────────────────────────────
    def _sync_range(self, mn, mx):
        sb = self._mid.verticalScrollBar()
        self._vsb.setRange(mn, mx)
        self._vsb.setPageStep(sb.pageStep())
        self._vsb.setSingleStep(sb.singleStep())

    # ── scroll sync (horizontal) ──────────────────────────
    def _sync_hrange(self, mn, mx):
        hsb_src = self._mid.horizontalScrollBar()
        self._hsb.setRange(mn, mx)
        self._hsb.setPageStep(hsb_src.pageStep())
        self._hsb.setSingleStep(hsb_src.singleStep())
        self._hsb.setVisible(mx > mn)

    def _on_hsb(self, val):
        if self._hscroll_guard:
            return
        self._hscroll_guard = True
        self._mid.horizontalScrollBar().setValue(val)
        self._hscroll_guard = False

    def _on_mid_hscroll(self, val):
        if self._hscroll_guard:
            return
        self._hscroll_guard = True
        self._hsb.setValue(val)
        self._hscroll_guard = False

    def _on_vsb(self, val):
        if self._scroll_guard:
            return
        self._scroll_guard = True
        for t in (self._left, self._mid, self._right):
            t.verticalScrollBar().setValue(val)
        self._scroll_guard = False

    def _on_tbl_scroll(self, val):
        if self._scroll_guard:
            return
        self._scroll_guard = True
        self._vsb.setValue(val)
        for t in (self._left, self._mid, self._right):
            t.verticalScrollBar().setValue(val)
        self._scroll_guard = False

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        step = self._vsb.singleStep() or 1
        self._vsb.setValue(self._vsb.value() - (delta // 120) * step)
        event.accept()

    # ── column mapping ────────────────────────────────────
    def _map(self, c):
        """Map global col → (table, local_col)"""
        if c == 0:
            return self._left, 0
        elif c >= self._n_cols - 1:
            return self._right, 0
        else:
            return self._mid, c - 1

    # ── configure ─────────────────────────────────────────
    def configure(self, cols, left_width=160, right_width=110, mid_col_width=88):
        """ตั้ง column headers ทั้งหมด + ขนาด"""
        self._n_cols = len(cols)

        # Left: 1 column
        self._left.setColumnCount(1)
        self._left.setHorizontalHeaderLabels([cols[0]])
        self._left.setFixedWidth(left_width)
        self._left.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)

        # Middle: N-2 columns
        mid_labels = cols[1:-1]
        self._mid.setColumnCount(len(mid_labels))
        self._mid.setHorizontalHeaderLabels(mid_labels)
        h = self._mid.horizontalHeader()
        h.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        for i in range(len(mid_labels)):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self._mid.setColumnWidth(i, mid_col_width)

        # Right: 1 column
        self._right.setColumnCount(1)
        self._right.setHorizontalHeaderLabels([cols[-1]])
        self._right.setFixedWidth(right_width)
        self._right.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)

        # Sync header heights — ใช้ค่า max จากทั้ง 3 ตาราง
        max_hh = max(t.horizontalHeader().sizeHint().height() for t in (self._left, self._mid, self._right))
        for t in (self._left, self._mid, self._right):
            t.horizontalHeader().setFixedHeight(max_hh)

        # อัปเดต spacer widths ของ horizontal scrollbar row ให้ตรงกับ left/right+vsb
        self._hsb_left_sp.setFixedWidth(left_width)
        vsb_w = self._vsb.sizeHint().width()
        self._hsb_right_sp.setFixedWidth(right_width + vsb_w)

    # ── proxy methods (compatible with QTableWidget API) ──
    def setRowCount(self, n):
        for t in (self._left, self._mid, self._right):
            t.setRowCount(n)

    def rowCount(self):
        return self._left.rowCount()

    def insertRow(self, r):
        for t in (self._left, self._mid, self._right):
            t.insertRow(r)

    def setItem(self, r, c, item):
        tbl, lc = self._map(c)
        tbl.setItem(r, lc, item)

    def item(self, r, c):
        tbl, lc = self._map(c)
        return tbl.item(r, lc)

    def columnCount(self):
        return self._n_cols

    def horizontalHeaderItem(self, c):
        tbl, lc = self._map(c)
        return tbl.horizontalHeaderItem(lc)

    def setAlternatingRowColors(self, b):
        for t in (self._left, self._mid, self._right):
            t.setAlternatingRowColors(b)

    def setRowHeight(self, r, h):
        for t in (self._left, self._mid, self._right):
            t.setRowHeight(r, h)


# ══════════════════════════════════════════════════════════
# FROZEN LEFT TABLE — ค้างเฉพาะคอลัมน์แรก (ซ้าย), ที่เหลือ scroll
# ══════════════════════════════════════════════════════════
class _FrozenLeftHHeader:
    """Proxy สำหรับ horizontalHeader() ของ FrozenLeftTable."""
    def __init__(self, left_hh, right_hh):
        self._l = left_hh
        self._r = right_hh

    def setDefaultAlignment(self, align):
        self._l.setDefaultAlignment(align)
        self._r.setDefaultAlignment(align)

    def setSectionResizeMode(self, *args):
        if len(args) == 1:
            # Apply only to right (scrollable) table; left col is always Fixed
            self._r.setSectionResizeMode(args[0])
        elif len(args) == 2:
            col, mode = args
            if col == 0:
                self._l.setSectionResizeMode(0, mode)
            else:
                rc = col - 1
                if rc < self._r.count():
                    self._r.setSectionResizeMode(rc, mode)

    def setFixedHeight(self, h):
        self._l.setFixedHeight(h)
        self._r.setFixedHeight(h)

    def sizeHint(self):
        return self._r.sizeHint()


class _ColumnSeparatorDelegate(QStyledItemDelegate):
    """Paint stronger vertical separators between logical column groups."""

    def __init__(self, columns=(), color="#94A3B8", width=2, parent=None):
        super().__init__(parent)
        self.columns = frozenset(int(column) for column in columns)
        self.color = QColor(color)
        self.width = max(1, int(width))

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.column() not in self.columns:
            return
        painter.save()
        painter.setPen(QPen(self.color, self.width))
        x = option.rect.right()
        painter.drawLine(x, option.rect.top(), x, option.rect.bottom())
        painter.restore()


class FrozenLeftTable(QWidget):
    """Table with a frozen first column; remaining columns scroll horizontally."""

    _TBL_STYLE = (
        tables_styles.FROZEN_TABLE
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._n_cols = 0
        self._row_h = 30
        self._group_separator_columns = ()
        self._body_separator_delegate = None
        self._header_separator_delegate = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._group_header = QWidget()
        group_lay = QHBoxLayout(self._group_header)
        group_lay.setContentsMargins(0, 0, 0, 0)
        group_lay.setSpacing(0)
        self._group_left = QTableWidget(2, 1)
        self._group_right = QTableWidget(2, 0)
        self._group_vsb_spacer = QWidget()
        self._group_vsb_spacer.setFixedWidth(QScrollBar().sizeHint().width())
        group_lay.addWidget(self._group_left)
        group_lay.addWidget(self._group_right, 1)
        group_lay.addWidget(self._group_vsb_spacer)
        # The two-row group header is intentionally outside the scrollable
        # tables.  Keep its height fixed so report-period headers remain in
        # view while the user scrolls the report body vertically.
        self._group_header.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._group_header.setFixedHeight(70)
        self._group_header.setVisible(False)

        group_style = (
            tables_styles.GROUP_HEADER
        )
        for table in (self._group_left, self._group_right):
            table.horizontalHeader().setVisible(False)
            table.verticalHeader().setVisible(False)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
            table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            table.setTextElideMode(Qt.TextElideMode.ElideNone)
            table.setWordWrap(True)
            table.setStyleSheet(group_style)
            table.setRowHeight(0, 34)
            table.setRowHeight(1, 34)
            table.setFixedHeight(70)

        # Use a real body container instead of a nested layout.  This keeps
        # the sticky group header and the scrolling body as separate geometry
        # regions even when the table is resized inside a report tab.
        self._body = QWidget()
        lay = QHBoxLayout(self._body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._left  = QTableWidget()   # frozen col 0
        self._right = QTableWidget()   # scrollable cols 1..N-1

        for t in (self._left, self._right):
            t.verticalHeader().setVisible(False)
            t.verticalHeader().setDefaultSectionSize(self._row_h)
            t.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            t.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            t.setAlternatingRowColors(True)
            t.setStyleSheet(self._TBL_STYLE)
            t.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)

        self._left.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._left.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._right.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._right.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._vsb = QScrollBar(Qt.Orientation.Vertical)
        self._scroll_guard = False
        self._right.verticalScrollBar().rangeChanged.connect(self._sync_range)
        self._vsb.valueChanged.connect(self._on_vsb)
        for t in (self._left, self._right):
            t.verticalScrollBar().valueChanged.connect(self._on_tbl_scroll)

        self._hh_proxy = _FrozenLeftHHeader(
            self._left.horizontalHeader(), self._right.horizontalHeader())

        self._group_hscroll_guard = False
        self._right.horizontalScrollBar().valueChanged.connect(self._on_body_hscroll)
        self._right.horizontalScrollBar().rangeChanged.connect(
            self._sync_left_bottom_margin
        )
        self._group_right.horizontalScrollBar().valueChanged.connect(self._on_group_hscroll)

        lay.addWidget(self._left)
        lay.addWidget(self._right, 1)
        lay.addWidget(self._vsb)
        outer.addWidget(self._group_header)
        outer.addWidget(self._body, 1)

    def _sync_left_bottom_margin(self, minimum: int, maximum: int) -> None:
        """Keep frozen and scrollable viewports at the same body height.

        The right table owns the horizontal scrollbar.  When it appears, Qt
        reduces only that table's viewport, which otherwise makes equal
        vertical scrollbar values land on adjacent rows near the bottom.
        Reserve the same height below the frozen column without displaying a
        second scrollbar.
        """
        reserve = (
            self._right.horizontalScrollBar().sizeHint().height()
            if maximum > minimum
            else 0
        )
        self._left.setViewportMargins(0, 0, 0, reserve)

    def _refresh_viewport_alignment(self):
        horizontal = self._right.horizontalScrollBar()
        self._sync_left_bottom_margin(horizontal.minimum(), horizontal.maximum())
        right_scroll = self._right.verticalScrollBar()
        self._sync_range(right_scroll.minimum(), right_scroll.maximum())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._refresh_viewport_alignment)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._refresh_viewport_alignment)

    def _on_body_hscroll(self, value):
        if self._group_hscroll_guard:
            return
        self._group_hscroll_guard = True
        self._group_right.horizontalScrollBar().setValue(value)
        self._group_hscroll_guard = False

    def _on_group_hscroll(self, value):
        if self._group_hscroll_guard:
            return
        self._group_hscroll_guard = True
        self._right.horizontalScrollBar().setValue(value)
        self._group_hscroll_guard = False

    # ── Scroll sync ──────────────────────────────────────
    def _sync_range(self, mn, mx):
        sb = self._right.verticalScrollBar()
        horizontal = self._right.horizontalScrollBar()
        self._sync_left_bottom_margin(horizontal.minimum(), horizontal.maximum())
        left_sb = self._left.verticalScrollBar()
        # QTableWidget computes a shorter range for the frozen side because it
        # has no horizontal scrollbar of its own.  Use the scrollable body's
        # range on both sides so an identical pixel offset always means the
        # identical top row.
        left_sb.setRange(mn, mx)
        left_sb.setPageStep(sb.pageStep())
        left_sb.setSingleStep(sb.singleStep())
        self._vsb.setRange(mn, mx)
        self._vsb.setPageStep(sb.pageStep())
        self._vsb.setSingleStep(sb.singleStep())

    def _on_vsb(self, val):
        if self._scroll_guard:
            return
        self._scroll_guard = True
        right_scroll = self._right.verticalScrollBar()
        left_scroll = self._left.verticalScrollBar()
        right_scroll.setValue(val)
        left_scroll.setRange(right_scroll.minimum(), right_scroll.maximum())
        left_scroll.setPageStep(right_scroll.pageStep())
        left_scroll.setSingleStep(right_scroll.singleStep())
        left_scroll.setValue(right_scroll.value())
        anchor_row = self._right.rowAt(1)
        if anchor_row >= 0:
            offset_delta = (
                self._left.rowViewportPosition(anchor_row)
                - self._right.rowViewportPosition(anchor_row)
            )
            if offset_delta:
                left_scroll.setValue(left_scroll.value() + offset_delta)
        self._scroll_guard = False

    def _on_tbl_scroll(self, val):
        if self._scroll_guard:
            return
        self._scroll_guard = True
        self._vsb.setValue(val)
        for t in (self._left, self._right):
            t.verticalScrollBar().setValue(val)
        self._scroll_guard = False

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        step = self._vsb.singleStep() or 1
        self._vsb.setValue(self._vsb.value() - (delta // 120) * step)
        event.accept()

    # ── QTableWidget-compatible API ───────────────────────
    def setColumnCount(self, n):
        self._n_cols = n
        self._left.setColumnCount(1)
        self._right.setColumnCount(max(0, n - 1))

    def columnCount(self):
        return self._n_cols

    def setRowCount(self, n):
        self._left.setRowCount(n)
        self._right.setRowCount(n)
        for row in range(n):
            self.setRowHeight(row, self._row_h)

    def rowCount(self):
        return self._left.rowCount()

    def setHorizontalHeaderLabels(self, labels):
        if labels:
            self._left.setColumnCount(1)
            self._left.setHorizontalHeaderLabels([labels[0]])
        if len(labels) > 1:
            self._right.setColumnCount(len(labels) - 1)
            self._right.setHorizontalHeaderLabels(labels[1:])
        # Sync header heights
        lh = self._left.horizontalHeader().sizeHint().height()
        rh = self._right.horizontalHeader().sizeHint().height()
        hh = max(lh, rh, 24)
        self._left.horizontalHeader().setFixedHeight(hh)
        self._right.horizontalHeader().setFixedHeight(hh)

    def setColumnWidth(self, c, w):
        if c == 0:
            self._left.setFixedWidth(w + 2)
            self._left.setColumnWidth(0, w)
            self._group_left.setFixedWidth(w + 2)
            self._group_left.setColumnWidth(0, w)
        else:
            self._right.setColumnWidth(c - 1, w)
            if c - 1 < self._group_right.columnCount():
                self._group_right.setColumnWidth(c - 1, w)

    def setColumnHidden(self, c, hide):
        # [V4.5] รองรับการซ่อนคอลัมน์ที่ 0 (frozen left) ด้วย
        if c == 0:
            self._left.setVisible(not hide)
            self._group_left.setVisible(not hide)
        else:
            self._right.setColumnHidden(c - 1, hide)
            if c - 1 < self._group_right.columnCount():
                self._group_right.setColumnHidden(c - 1, hide)

    def setRowHeight(self, row, height):
        """Keep frozen labels and values on the exact same row geometry."""
        height = max(1, int(height))
        self._left.setRowHeight(row, height)
        self._right.setRowHeight(row, height)

    def rowHeight(self, row):
        return self._right.rowHeight(row)

    def setGroupSeparators(self, columns, color="#94A3B8", width=2):
        """Draw separators after the given global (frozen-table) columns."""
        self._group_separator_columns = tuple(sorted({
            int(column) for column in columns
            if 0 < int(column) < self._n_cols
        }))
        local_columns = tuple(column - 1 for column in self._group_separator_columns)
        self._body_separator_delegate = _ColumnSeparatorDelegate(
            local_columns, color, width, self._right
        )
        self._header_separator_delegate = _ColumnSeparatorDelegate(
            local_columns, color, width, self._group_right
        )
        self._right.setItemDelegate(self._body_separator_delegate)
        self._group_right.setItemDelegate(self._header_separator_delegate)
        self._right.viewport().update()
        self._group_right.viewport().update()

    def groupSeparatorColumns(self):
        return self._group_separator_columns

    def setGroupedHeader(self, left_label, groups, sublabels):
        """Show a two-level header aligned with the frozen-left table."""
        normalized_groups = [
            (group[0], group[1], group[2] if len(group) > 2 else None)
            for group in groups
        ]
        if sum(span for _label, span, _color in normalized_groups) != self._n_cols - 1:
            raise ValueError("grouped header spans must match scrollable columns")
        if len(sublabels) != self._n_cols - 1:
            raise ValueError("grouped header sublabels must match scrollable columns")

        self._set_group_header_rows(2)
        self._group_left.clearSpans()
        self._group_left.setRowCount(2)
        self._group_left.setColumnCount(1)
        self._group_left.setSpan(0, 0, 2, 1)
        left_item = QTableWidgetItem(str(left_label))
        left_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._group_left.setItem(0, 0, left_item)

        self._group_right.clearSpans()
        self._group_right.setRowCount(2)
        self._group_right.setColumnCount(self._n_cols - 1)
        column = 0
        for label, span, color in normalized_groups:
            if span > 1:
                self._group_right.setSpan(0, column, 1, span)
            item = QTableWidgetItem(str(label))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if color:
                item.setBackground(QColor(color))
            self._group_right.setItem(0, column, item)
            for subcolumn in range(column, column + span):
                subitem = QTableWidgetItem(str(sublabels[subcolumn]))
                subitem.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if color:
                    subitem.setBackground(QColor(color).lighter(112))
                self._group_right.setItem(1, subcolumn, subitem)
            column += span

        for column in range(self._n_cols - 1):
            width = self._right.columnWidth(column)
            self._group_right.setColumnWidth(column, width)
        self._left.horizontalHeader().setVisible(False)
        self._right.horizontalHeader().setVisible(False)
        self._group_header.setVisible(True)

    def setThreeLevelGroupedHeader(
        self,
        left_label,
        outer_groups,
        middle_groups,
        sublabels,
    ):
        """Show device, operation, and detail as three readable header rows."""
        normalized_outer = [
            (group[0], group[1], group[2] if len(group) > 2 else None)
            for group in outer_groups
        ]
        normalized_middle = [
            (group[0], group[1], group[2] if len(group) > 2 else None)
            for group in middle_groups
        ]
        scrollable_columns = self._n_cols - 1
        if sum(span for _label, span, _color in normalized_outer) != scrollable_columns:
            raise ValueError("outer grouped header spans must match scrollable columns")
        if sum(span for _label, span, _color in normalized_middle) != scrollable_columns:
            raise ValueError("middle grouped header spans must match scrollable columns")
        if len(sublabels) != scrollable_columns:
            raise ValueError("grouped header sublabels must match scrollable columns")

        self._set_group_header_rows(3)
        self._group_left.clearSpans()
        self._group_left.setRowCount(3)
        self._group_left.setColumnCount(1)
        self._group_left.setSpan(0, 0, 3, 1)
        left_item = QTableWidgetItem(str(left_label))
        left_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._group_left.setItem(0, 0, left_item)

        self._group_right.clearSpans()
        self._group_right.setRowCount(3)
        self._group_right.setColumnCount(scrollable_columns)
        column = 0
        for label, span, color in normalized_outer:
            if span > 1:
                self._group_right.setSpan(0, column, 1, span)
            item = QTableWidgetItem(str(label))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if color:
                item.setBackground(QColor(color))
            self._group_right.setItem(0, column, item)
            column += span

        column = 0
        for label, span, color in normalized_middle:
            if span > 1:
                self._group_right.setSpan(1, column, 1, span)
            item = QTableWidgetItem(str(label))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if color:
                item.setBackground(QColor(color))
            self._group_right.setItem(1, column, item)
            for subcolumn in range(column, column + span):
                subitem = QTableWidgetItem(str(sublabels[subcolumn]))
                subitem.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if color:
                    subitem.setBackground(QColor(color).lighter(112))
                self._group_right.setItem(2, subcolumn, subitem)
            column += span

        for column in range(scrollable_columns):
            self._group_right.setColumnWidth(column, self._right.columnWidth(column))
        self._left.horizontalHeader().setVisible(False)
        self._right.horizontalHeader().setVisible(False)
        self._group_header.setVisible(True)

    def _set_group_header_rows(self, row_count):
        row_height = 34
        fixed_height = row_count * row_height + 2
        for table in (self._group_left, self._group_right):
            table.setRowCount(row_count)
            for row in range(row_count):
                table.setRowHeight(row, row_height)
            table.setFixedHeight(fixed_height)
        self._group_header.setFixedHeight(fixed_height)

    def groupedHeaderItem(self, row, c):
        if c == 0:
            return self._group_left.item(row, 0)
        return self._group_right.item(row, c - 1)

    def groupedHeaderSpan(self, row, c):
        if c == 0:
            return self._group_left.rowSpan(row, 0), self._group_left.columnSpan(row, 0)
        return self._group_right.rowSpan(row, c - 1), self._group_right.columnSpan(row, c - 1)

    def setItem(self, r, c, item):
        if c == 0:
            self._left.setItem(r, 0, item)
        else:
            self._right.setItem(r, c - 1, item)
        # QTableWidget can recalculate one side after inserting wrapped or bold
        # content. Reassert both heights so the frozen column never drifts.
        self.setRowHeight(r, self._row_h)

    def item(self, r, c):
        if c == 0:
            return self._left.item(r, 0)
        return self._right.item(r, c - 1)

    def horizontalHeaderItem(self, c):
        if c == 0:
            return self._left.horizontalHeaderItem(0)
        return self._right.horizontalHeaderItem(c - 1)

    def horizontalHeader(self):
        return self._hh_proxy

    def verticalHeader(self):
        return self._left.verticalHeader()

    def setEditTriggers(self, t):
        self._left.setEditTriggers(t)
        self._right.setEditTriggers(t)

    def setAlternatingRowColors(self, v):
        self._left.setAlternatingRowColors(v)
        self._right.setAlternatingRowColors(v)

    def alternatingRowColors(self):
        return self._left.alternatingRowColors()

    def setCurrentCell(self, row, column):
        if column == 0:
            self._left.setCurrentCell(row, 0)
        else:
            self._right.setCurrentCell(row, column - 1)

    def clearSelection(self):
        self._left.clearSelection()
        self._right.clearSelection()

    def blockSignals(self, b):
        self._left.blockSignals(b)
        self._right.blockSignals(b)
        return super().blockSignals(b)


def make_table(cols: list, stretch_cols: list = None,
               fixed_cols: dict = None, height: int = None) -> QTableWidget:
    """
    สร้าง QTableWidget พร้อม style มาตรฐาน
    cols = รายชื่อ column
    stretch_cols = index ที่ต้องการให้ขยายเต็ม
    fixed_cols = {index: width} กำหนดความกว้างคงที่
    """
    t = QTableWidget(0, len(cols))
    t.setHorizontalHeaderLabels(cols)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    t.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)

    if stretch_cols:
        for i in stretch_cols:
            t.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
    if fixed_cols:
        for i, w in fixed_cols.items():
            t.setColumnWidth(i, w)
    if height:
        t.setFixedHeight(height)
    return t

# ══════════════════════════════════════════════════════════
# BADGE LABEL
# ══════════════════════════════════════════════════════════
def badge(text: str, bg: str = C_ACCENT, fg: str = "white") -> QLabel:
    """ป้ายสี เช่น "User" "SUM" "ซ้ำ" "ปกติ" """
    l = QLabel(f"  {text}  ")
    l.setFont(fnt(F_XS, True))
    l.setStyleSheet(surfaces_styles.badge(bg, fg))
    l.setFixedHeight(20)
    return l

# ══════════════════════════════════════════════════════════
# INFO ROW — แสดงคู่ label:value
# ══════════════════════════════════════════════════════════
