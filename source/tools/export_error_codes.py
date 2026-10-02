"""Generate the support reference from the same catalog used by the application."""
from pathlib import Path

from services.error_codes import ERROR_CODES
from services.support_diagnostics import CATALOG
from services.error_reference import CHECKS


def reference_markdown():
    lines = [
        '# ตาราง Error Code — KOMI Report', '',
        'ตารางนี้สร้างจากรายการรหัสกลางของแอป ห้ามเปลี่ยนความหมายหรือนำรหัสเดิมไปใช้กับปัญหาอื่น', '',
        'ผู้ใช้แจ้ง Error Code ที่ปรากฏบนหน้าจอ หรือกด **คัดลอกรายละเอียด** เพื่อส่งรหัสพร้อมหลักฐานของเหตุการณ์ได้ทันที',
        'รหัสระบุประเภทความผิดพลาดตามหลักฐาน ไม่ได้ยืนยันสาเหตุที่ตรวจไม่พบ เช่น TLS ล้มเหลวไม่ได้แปลว่า PKI ปิด และ timeout ไม่ได้แปลว่ารหัสผ่านผิด',
        'KOMI-UI-001 เป็นคำเตือนตามเงื่อนไขหน้าจอ และ KOMI-APP-999 เป็นข้อผิดพลาดที่ยังจำแนกไม่ได้ ต้องอ่านรายละเอียดที่แอปแนบมาด้วยเพื่อระบุเหตุการณ์', '',
        f'ทั้งหมด {len(ERROR_CODES)} รหัส ครอบคลุมรายการวินิจฉัยส่วนกลางในแอป Desktop; ไม่แทนรหัสของ Windows หรือตัวติดตั้ง', '',
        '| Error Code | รหัสภายใน | ปัญหา | สาเหตุที่ยืนยันได้ | แนวทางตรวจสอบ | ตำแหน่งและวิธีแก้ |',
        '|---|---|---|---|---|---|',
    ]
    for key, public in sorted(ERROR_CODES.items(), key=lambda pair: pair[1]):
        summary, cause, action = CATALOG[key]
        cells = (public, key, summary, cause, CHECKS[key], action)
        lines.append('| ' + ' | '.join(value.replace('|', '\\|').replace('\n', '<br>') for value in cells) + ' |')
    lines.extend(['', 'สร้างใหม่ด้วย `PYTHONPATH=source python -m tools.export_error_codes` จากโฟลเดอร์โครงการ', ''])
    return '\n'.join(lines)


if __name__ == '__main__':
    target = Path(__file__).resolve().parents[2] / 'ERROR_CODES.md'
    target.write_text(reference_markdown(), encoding='utf-8')
    print(target)
