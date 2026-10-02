"""Interactive Users graph explanation with in-memory sample data only."""
import os
from dataclasses import replace
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'source'), str(ROOT / 'source/tests')]
os.environ.pop('QT_QPA_PLATFORM', None)
OUT = ROOT / 'outputs' / 'users-graph-demo'
OUT.mkdir(parents=True, exist_ok=True)


def main():
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
    from excel_export_fixture import report_for
    from i18n import set_language
    from ui.cloud_reports import CloudReportsWidget
    from ui_consistency import install_button_system

    app = QApplication(sys.argv)
    install_button_system(app)
    set_language('th')
    report = report_for(users=8, days=4, printers=3)
    # The preview contains complete, consistent synthetic counter and price evidence.
    weight = lambda user, slot: (8 - user) * (slot + 1)
    subjects = tuple(replace(subject, subject_name=f'User {int(subject.subject_id) + 1:02d}',
        period_usage=32 * weight(int(subject.subject_id), subject.device_slot)) for subject in report.subjects)
    raw = tuple(replace(record, delta_value=(weight(int(record.subject_id), record.device_slot)
        if record.is_subject else sum(weight(user, record.device_slot) for user in range(8))),
        subject_name=f'User {int(record.subject_id) + 1:02d}' if record.is_subject else record.subject_name)
        for record in report.raw_counter_records)
    costs = tuple(replace(cost, **{field: 4 * sum(weight(user, cost.device_slot) for user in range(8)) * (cost.device_slot + 1)
        for field in ('a4_color', 'a4_bw', 'a3_color', 'a3_bw')}) for cost in report.category_costs)

    class UsersPreview(CloudReportsWidget):
        def _render_users_charts(self):
            # Retain the original total-only charts while their redesign is under discussion.
            from ui.cloud_reports import replace_chart, ORANGE, BLUE
            users = self._user_rows[:8]
            replace_chart(self.users_top_chart, self._horizontal_like_chart(
                [row['name'] for row in users], [row['usage'] for row in users], ORANGE))
            selected = next((row for row in self._user_rows if row['key'] == self._selected_user), None)
            chosen = (selected,) if selected else self._user_rows
            values = [sum(row['by_slot'].get(slot, {}).get('total', 0) for row in chosen) for slot in range(3)]
            replace_chart(self.users_printer_chart, self._horizontal_like_chart(
                [f'Slot {slot + 1}' for slot in range(3)], values, BLUE))

    window = QWidget()
    window.setWindowTitle('KOMI Users - Preview ภาพรวม / รายเครื่อง (ข้อมูลจำลอง)')
    layout = QVBoxLayout(window)
    banner = QLabel('ข้อมูลจำลอง 8 ผู้ใช้ / 3 เครื่อง · ตัวอย่างเพื่ออธิบายกราฟเดิม ยังไม่ใช่แบบกราฟใหม่ที่ตกลงแล้ว\n'
                    'ซ้าย: เปรียบเทียบยอดรวมต่อผู้ใช้ · ขวา: ยอดตามเครื่อง · คลิกผู้ใช้ในตารางเพื่อกรองกราฟขวา')
    banner.setWordWrap(True)
    banner.setStyleSheet('background:#FFF3CD;color:#5C4300;padding:10px;font-size:14px;')
    layout.addWidget(banner)
    reports = UsersPreview()
    layout.addWidget(reports)
    reports.set_periods((report.period,), report.period)
    reports.set_data(records=report.selected_records, daily_records=report.selected_daily_records,
                     subjects=tuple(subjects), devices=report.devices, period=report.period,
                     last_sync_at=None, raw_counter_records=raw, category_costs=costs)
    reports.tabs.setCurrentIndex(1)
    for index in range(reports.tabs.count()):
        reports.tabs.tabBar().setTabVisible(index, index == 1)
    for start, end in reports.period_edit_pairs:
        start.setEnabled(False)
        end.setEnabled(False)
    reports.export_button.setEnabled(False)
    reports.refresh_button.setEnabled(False)
    window.resize(1400, 950)
    window.show()
    (OUT / 'pid.txt').write_text(str(os.getpid()), encoding='utf-8')
    def capture_overview():
        window.grab().save(str(OUT / 'users.png'))
        reports.user_printers_button.click()
        QTimer.singleShot(400, capture_printers)
    def capture_printers():
        window.grab().save(str(OUT / 'users-printers.png'))
        reports.user_overview_button.click()
    QTimer.singleShot(1500, capture_overview)
    return app.exec()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        (OUT / 'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise
