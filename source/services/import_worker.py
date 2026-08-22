from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from services.import_service import save_import


class ImportSaveWorker(QObject):
    progress = pyqtSignal(str)
    success = pyqtSignal(object)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, slot: int, parsed: dict, path: str):
        super().__init__()
        self.slot = slot
        self.parsed = parsed
        self.path = path

    @pyqtSlot()
    def run(self):
        try:
            self.progress.emit("กำลังบันทึกข้อมูล...")
            self.progress.emit("กำลังจัดเก็บไฟล์นำเข้า...")
            result = save_import(self.slot, self.parsed, self.path)
            self.success.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()
