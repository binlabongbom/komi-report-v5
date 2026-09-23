"""Team-assisted clean reinstallation; never pretend to restore a lost key."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QDialogButtonBox, QFileDialog, QApplication
from ui.counter_review import plain
from widgets import btn
from i18n import tr
from database import get_db_path


class PeerReinstallationDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.source = Path(get_db_path()).resolve()
        self.future = self.target = None
        self.setWindowTitle(tr('เริ่มสมาชิกใหม่โดยเก็บฐานเดิม', 'Start a new member and keep the old database'))
        self.setMinimumSize(640,420)
        layout = QVBoxLayout(self)
        layout.addWidget(plain(tr(
            'ใช้เมื่อทีมติดตั้งยืนยันว่ากู้กุญแจเดิมไม่ได้ จะสร้างฐานว่างอีกไฟล์และเริ่ม Wizard ใหม่เมื่อเปิดโปรแกรมครั้งถัดไป ฐานเดิมและ Archive ยังอยู่ครบ แต่ประวัติเดิมจะไม่ถูกนำเข้าฐานใหม่อัตโนมัติ\n\nเครื่องในกลุ่มเดิมเปิดรับสมาชิกไว้ตลอด ถ้าไม่พบกลุ่ม ให้ทีมติดตั้งค้นซ้ำหรือกรอก IP เครื่องที่แชร์ การลงทะเบียน Host ของการติดตั้งใหม่ยังเป็นขั้นตอนปกติ',
            'Use after the installation team confirms the original key cannot be restored. Create a separate empty database and run the Wizard on next launch. The old database and archives remain intact; old history is not automatically merged.\n\nExisting computers keep joining enabled. If the group is not found, the installation team can retry discovery or enter its IP. Normal Host registration still applies to the new installation.')))
        layout.addWidget(plain(str(self.source)))
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        layout.addWidget(self.path)
        choose = btn(tr('เลือกชื่อฐานข้อมูลใหม่', 'Choose a new database filename'), 'outline')
        choose.clicked.connect(self.choose)
        layout.addWidget(choose)
        self.status = plain('')
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('ยกเลิก','Cancel'))
        self.ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText(tr('สร้างฐานใหม่', 'Create new database'))
        self.ok.setEnabled(False)
        self.buttons.accepted.connect(self.run)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.pool = ThreadPoolExecutor(max_workers=1,thread_name_prefix='komi-new-installation')
        self.destroyed.connect(lambda _=None,pool=self.pool:pool.shutdown(wait=False,cancel_futures=True))
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.collect)

    def choose(self):
        if self.future is not None or self.target is not None:
            return
        path,_ = QFileDialog.getSaveFileName(self,tr('ฐานใหม่','New database'),str(self.source.with_name('KOMI_Report_new.db')),'SQLite (*.db)')
        if path:
            self.path.setText(path)
            self.ok.setEnabled(True)

    def run(self):
        if self.future is not None:
            return
        if self.target is not None:
            from runtime_config import save_runtime_database_path
            try:
                save_runtime_database_path(self.target)
            except Exception as error:
                self.status.setText(str(error))
                return
            self.accept()
            QApplication.instance().quit()
            return
        from services.peer_reinstallation import create_clean_database
        self.ok.setEnabled(False)
        self.future = self.pool.submit(create_clean_database,self.source,Path(self.path.text()))
        self.timer.start()

    def collect(self):
        if not self.future.done():
            return
        self.timer.stop()
        future,self.future = self.future,None
        try:
            self.target = future.result()
        except Exception as error:
            self.status.setText(str(error))
        else:
            self.status.setText(tr('สร้างฐานว่างแล้ว ยืนยันเพื่อปิดโปรแกรม จากนั้นเปิดใหม่เพื่อเริ่ม Wizard ฐานเดิมยังเก็บอยู่ที่ตำแหน่งเดิม',
                'Empty database created. Confirm to close the app, then launch it again for the Wizard. The original database is preserved.'))
            self.ok.setText(tr('ใช้ฐานใหม่และปิดโปรแกรม', 'Use new database and close'))
        self.ok.setEnabled(True)

    def reject(self):
        if self.future is None:
            super().reject()
