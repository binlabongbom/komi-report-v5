"""Member roles and evidence times in Automation, without network refresh work."""
from ui.resource_cleanup import close_executor_with
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView

from database import get_db_path
from i18n import tr
from services.reader_status import member_evidence, member_rows, display_time


class StatusLinkLabel(QLabel):
    clicked = pyqtSignal()

    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class ReaderMembersPanel(QWidget):
    _completed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.polling = None
        self._future = None
        self._again = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='komi-members-ui')
        close_executor_with(self, self._pool)
        self._completed.connect(self._render)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 12)
        title = QLabel(tr('สมาชิกคอมพิวเตอร์และสถานะการอ่าน', 'Computer members and reader roles'))
        title.setStyleSheet('font-weight:700;color:#123262;')
        layout.addWidget(title)
        self.note = QLabel(tr('บทบาทที่ระบบเลือกล่าสุด · เวลาเชื่อมต่อแยกจากเวลาข้อมูลที่อ่านหรือยืนยันรับแล้ว',
                              'Last selected roles · Connection time is separate from saved reading / acknowledged data time'))
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([tr('คอมพิวเตอร์', 'Computer'), tr('บทบาท', 'Role'),
            tr('เครื่องพิมพ์\nที่อ่าน / รับ', 'Printers\nread / received'),
            tr('เชื่อมต่อสำเร็จ\nล่าสุด', 'Last successful\nconnection'), tr('ข้อมูลล่าสุด', 'Latest data')])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.table.horizontalHeader().setMinimumSectionSize(90)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setStyleSheet('QTableWidget{background:white;border:1px solid #D7E0E8;}'
            'QHeaderView::section{background:#EDF2F7;color:#123262;padding:6px;border:1px solid #D7E0E8;}'
            'QTableWidget::item{padding:5px;}')
        self.table.setMinimumHeight(130)
        layout.addWidget(self.table)

    def bind_runtime(self, polling):
        self.polling = polling
        for signal in (polling.peer_history.changed, polling.activity_changed,
                       polling.device_updated, polling.peer_network_runtime.changed):
            signal.connect(self.schedule_refresh)
        self.schedule_refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.schedule_refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'table'):
            self.table.resizeRowsToContents()

    def schedule_refresh(self, *_args):
        if self.isVisible():
            self._timer.start(150)

    def refresh(self):
        if self.polling is None or not self.isVisible():
            return
        if self._future is not None:
            self._again = True
            return
        self._future = self._pool.submit(member_evidence, get_db_path())
        self._future.add_done_callback(self._finished)

    def _finished(self, future):
        try:
            self._completed.emit(future)
        except RuntimeError:
            pass

    def _render(self, future):
        self._future = None
        if self._again:
            self._again = False
            self.schedule_refresh()
        try:
            evidence = future.result()
        except Exception:
            self.note.setText(tr('ยังโหลดสถานะสมาชิกไม่สำเร็จ', 'Member status could not be loaded'))
            return
        self.note.setText(tr('บทบาทที่ระบบเลือกล่าสุด · เวลาเชื่อมต่อแยกจากเวลาข้อมูลที่อ่านหรือยืนยันรับแล้ว',
                              'Last selected roles · Connection time is separate from saved reading / acknowledged data time'))
        rows = member_rows(self.polling, evidence)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            values = (row['name'], row['role'], row['details'], row['connection'] +
                ('\n' + display_time(row['connected_at']) if row['connected_at'] else ''), display_time(row['data_at']))
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(i, j, item)
        self.table.resizeRowsToContents()
        self.table.setFixedHeight(min(360, self.table.horizontalHeader().height()
            + 2 * self.table.frameWidth() + sum(self.table.rowHeight(i) for i in range(len(rows)))))
