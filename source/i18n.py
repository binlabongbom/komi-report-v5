"""Small, dependency-free Thai/English UI localization layer.

The legacy desktop UI predates Qt translation catalogs and contains literal
Thai strings.  This module lets new code use ``tr(thai, english)`` while also
translating the existing widget tree, table headers and dynamic status rows.
Business data, printer names, IP addresses and counter keys are never changed.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTabWidget,
    QWidget,
)

THAI = "th"
ENGLISH = "en"
SUPPORTED_LANGUAGES = (THAI, ENGLISH)
_language = THAI
_ITEM_SOURCE_ROLE = int(Qt.ItemDataRole.UserRole) + 37


def normalize_language(value: str | None) -> str:
    return ENGLISH if str(value or "").strip().lower().startswith("en") else THAI


def set_language(value: str | None) -> str:
    global _language
    _language = normalize_language(value)
    return _language


def get_language() -> str:
    return _language


def tr(thai: str, english: str) -> str:
    return english if _language == ENGLISH else thai


# Exact labels used throughout the six main workspaces and the setup wizard.
# Longer/dynamic messages are handled by the phrase replacements below.
_EN: dict[str, str] = {
    "ภาษา": "Language",
    "ภาษา / Language": "Language / ภาษา",
    "ไทย": "Thai",
    "อังกฤษ": "English",
    "ภาพรวม": "Overview",
    "อุปกรณ์": "Devices",
    "นำเข้า": "Import",
    "รายงาน": "Reports",
    "บันทึกการซิงก์": "Sync Log",
    "ตั้งค่า": "Settings",
    "คู่มือ": "Manual",
    "ตั้งค่าการใช้งาน": "Settings",
    "ถ้าระบบทำงานปกติ คุณไม่จำเป็นต้องเปลี่ยนค่าใด": "If the system is working normally, you do not need to change anything.",
    "เปลี่ยน": "Change",
    "จัดเวลา": "Schedule",
    "จัดการ": "Manage",
    "แก้ปัญหา": "Troubleshoot",
    "ปิด": "Close",
    "ข้อมูลที่ใช้ในรายงาน": "Report data",
    "บันทึกรอบบิลและตรวจสอบ": "Save and verify billing",
    "บันทึกเวลาและตรวจสอบ": "Save and verify schedule",
    "บันทึกและตรวจสอบ LAN": "Save and verify LAN access",
    "มีผลทันที": "Takes effect immediately",
    "การเปลี่ยนรหัสมีผลทันที": "Changing the access code takes effect immediately",
    "คัดลอกที่อยู่ LAN": "Copy LAN address",
    "ช่วยเหลือและตรวจสอบปัญหา": "Help and troubleshooting",
    "พบปัญหาอะไร": "What problem do you see?",
    "ข้อมูลไม่อัปเดต": "Data is not updating",
    "ยอดไม่ตรง": "Totals do not match",
    "เปิด Web ไม่ได้": "Cannot open Web Report",
    "การเปลี่ยนแปลงมีผลกับรายการใหม่เท่านั้น และไม่แก้ยอดย้อนหลัง": "Changes affect new records only and do not rewrite past totals.",
    "เลือกเฉพาะสิ่งที่ต้องการเปลี่ยน ระบบจะใช้ค่าที่แนะนำให้หากไม่แน่ใจ": "Change only what you need. Recommended values are used when you are unsure.",
    "ต้องเพิ่มเครื่องพิมพ์": "Add a printer",
    "อ่านข้อมูลอัตโนมัติ": "Automatic readings",
    "การอ่านข้อมูลอัตโนมัติ": "Automatic readings",
    "เปิดใช้งาน": "Enabled",
    "ปิดอยู่": "Disabled",
    "● ปิดอยู่ · Web service ปิดอยู่": "● Disabled · Web service is stopped",
    "Web service พร้อมใช้งาน": "Web service is ready",
    "Web service ปิดอยู่": "Web service is stopped",
    "กำลังเตรียม Web runtime หรือรอ service พร้อม": "Preparing the Web runtime or waiting for the service",
    "Web service เริ่มไม่สำเร็จ · เปิด Log เพื่อดูรายละเอียด": "Web service could not start · Open the log for details",
    "บันทึกรหัสแล้ว แต่ Web service เปิดจากโปรแกรมอื่น กรุณาปิดและเปิดใหม่": "Access code saved, but the Web service is running outside this app. Stop and restart it.",
    "เครื่องพิมพ์และราคา": "Printers & pricing",
    "เพิ่มหรือเปลี่ยนเครื่องพิมพ์ ตั้งชื่อที่จำง่าย และแก้ราคาต่อหน้าได้จากหน้าติดตั้งเดิม": "Add or replace printers, use clear names, and update per-page pricing through the setup flow.",
    "กำหนดวันที่ปิดรอบและส่วนลดกระดาษเสีย การเปลี่ยนแปลงมีผลกับรายการใหม่เท่านั้น": "Set the billing-cycle end day and waste-paper discount. Changes affect new records only.",
    "ถ้าเดือนไม่มีวันที่เลือก ระบบใช้วันสุดท้ายของเดือน": "Shorter months use their final day.",
    "หักออกจากยอดค่าใช้จ่ายก่อนสรุปรอบบิล": "Deducted from cost before the billing cycle is summarized.",
    "โปรแกรมจะอ่านข้อมูลเครื่องพิมพ์ตามเวลาที่กำหนด แม้ปิดหน้าต่างไว้ใน System Tray": "The application reads printer data on schedule while its window is closed to the System Tray.",
    "รายงานผ่านเว็บและ Database": "Web reports & database",
    "เปิดรายงานจากเครื่องอื่นในเครือข่ายเดียวกัน และตรวจตำแหน่งที่เก็บข้อมูลของโปรแกรม": "Open reports from another computer on the same LAN and check where application data is stored.",
    "รายงานจากเครื่องอื่นใน LAN": "Reports on other LAN computers",
    "อนุญาตให้เครื่องอื่นในเครือข่ายเดียวกันเปิดดูรายงานผ่าน Web ส่วนเครื่องนี้ใช้แอป Desktop ตามปกติ": "Allow other computers on the same LAN to view Web reports. Continue using the Desktop app on this computer.",
    "อนุญาตให้เครื่องอื่นใน LAN เปิดดูรายงาน": "Allow other LAN computers to view reports",
    "เปิดรายงานผ่าน Web สำหรับเครื่องอื่นใน LAN": "Enable Web reports for other LAN computers",
    "ที่อยู่ Web Report สำหรับเครื่องอื่นใน LAN": "Web Report address for other LAN computers",
    "ข้อมูลสำหรับเจ้าหน้าที่": "Staff information",
    "ใช้เมื่อต้องตรวจสอบเหตุขัดข้องหรือข้อมูลรอบบิล ผู้ใช้งานทั่วไปไม่จำเป็นต้องเปิดส่วนนี้": "Use this only to troubleshoot readings or billing-cycle data. General users do not need this section.",
    "ซ่อนข้อมูลทางเทคนิคไว้เพื่อลดความสับสน ผู้ใช้งานทั่วไปไม่จำเป็นต้องเปิดส่วนนี้": "Technical information stays hidden to reduce confusion. General users do not need this section.",
    "แสดงข้อมูลสำหรับเจ้าหน้าที่": "Show staff information",
    "ซ่อนข้อมูลสำหรับเจ้าหน้าที่": "Hide staff information",
    "แสดงหรือซ่อนข้อมูลสำหรับเจ้าหน้าที่": "Show or hide staff information",
    "คำเตือน: รายละเอียดบางรายการมีผลต่อฐานข้อมูลและประวัติการใช้งาน โปรดอ่านข้อความยืนยันก่อนดำเนินการ": "Warning: some actions affect the database and usage history. Read the confirmation before continuing.",
    "สถานะการตั้งค่า": "Settings status",
    "รายชื่อเครื่องพิมพ์ที่ใช้งาน": "Configured printers",
    "วันสิ้นสุดรอบบิล": "Billing-cycle end day",
    "วันตัดรอบบิล": "Billing-cycle end day",
    "ส่วนลดกระดาษเสีย": "Waste-paper discount",
    "สรุปเวลาการอ่านข้อมูลอัตโนมัติ": "Automatic reading schedule summary",
    "แสดงหรือซ่อนการตั้งเวลาแบบละเอียด": "Show or hide the custom reading schedule",
    "ตารางเวลาการอ่านข้อมูลแบบละเอียด": "Custom reading schedule table",
    "เปิดรายงานผ่านเว็บสำหรับเครือข่ายภายใน": "Enable Web reports on the local network",
    "ตำแหน่งฐานข้อมูลที่กำลังใช้งาน": "Current database location",
    "คำเตือนสำหรับเครื่องมือเจ้าหน้าที่": "Warning for staff tools",
    "รายการ Billing Audit": "Billing Audit records",
    "กลับไปหน้าการตั้งค่าหลัก": "Back to main Settings",
    "ตารางค่าเริ่มต้นใหม่พร้อมบันทึก": "New default schedule ready to save",
    "เลือกข้อมูลที่แสดงในรายงาน": "Choose report data",
    "เปิดโปรแกรมอัตโนมัติเมื่อเข้าสู่ระบบ": "Start automatically at sign-in",
    "ปรับเวลาแบบละเอียด": "Customize schedule",
    "อนุญาตให้เครื่องอื่นใน LAN เปิดรายงานผ่าน Web": "Allow other computers on the LAN to open Web reports",
    "เปิด Web Report อัตโนมัติพร้อม KOMI Report": "Start Web Report automatically with KOMI Report",
    "เปิด Web Report อัตโนมัติเมื่อเปิดโปรแกรม": "Start Web Report automatically when the app opens",
    "ตั้งรหัสเข้า Web Report": "Set Web Report access code",
    "รหัสสำหรับเครื่องอื่นใน LAN": "Access code for other LAN computers",
    "ผู้ใช้ที่เปิด Web Report จากเครื่องอื่นต้องใช้รหัสนี้ เมื่อเปลี่ยนแล้วทุกเครื่องจะต้องเข้าสู่ระบบใหม่": "Users opening Web Report from another computer need this code. Changing it signs every computer out.",
    "รหัสใหม่": "New access code",
    "ยืนยันรหัส": "Confirm access code",
    "อย่างน้อย 12 ตัวอักษร": "At least 12 characters",
    "รหัส Web ต้องยาวอย่างน้อย 12 ตัวอักษร": "The Web access code must contain at least 12 characters",
    "รหัส Web ต้องไม่เกิน 128 ตัวอักษร": "The Web access code must not exceed 128 characters",
    "กรอกรหัสเดิมอีกครั้ง": "Enter the same code again",
    "รหัส Web ใหม่": "New Web access code",
    "ยืนยันรหัส Web ใหม่": "Confirm new Web access code",
    "แสดงรหัสที่กำลังกรอก": "Show the code being entered",
    "บันทึกรหัสใหม่": "Save new code",
    "รหัสเข้า Web Report": "Web Report access code",
    "สถานะรหัสเข้า Web Report": "Web Report access-code status",
    "เปลี่ยนรหัส Web": "Change Web access code",
    "ตั้งรหัส Web": "Set Web access code",
    "ตั้งหรือเปลี่ยนรหัสเข้า Web Report": "Set or change the Web Report access code",
    "ยังไม่ได้ตั้งรหัส · เครื่องอื่นใน LAN จะยังเข้าสู่ระบบไม่ได้": "Access code not set · Other LAN computers cannot sign in yet",
    "รหัสใหม่และช่องยืนยันไม่ตรงกัน": "The new code and confirmation do not match",
    "เปลี่ยนรหัส Web ไม่สำเร็จ": "Could not change the Web access code",
    "บันทึกรหัสแล้ว": "Access code saved",
    "บันทึกรหัสใหม่แล้ว แต่ Web service เปิดจาก Shortcut แยก กรุณาปิด Web service เดิมและเปิดใหม่ก่อนใช้งาน": "The new code was saved, but Web Report was started from a separate shortcut. Stop and restart that Web service before signing in.",
    "เปลี่ยนรหัส Web แล้ว": "Web access code changed",
    "เครื่องอื่นใน LAN ต้องเข้าสู่ระบบใหม่ด้วยรหัสที่เพิ่งตั้ง": "Other LAN computers must sign in again with the new code.",
    "เปิดหน้า Web": "Open Web reports",
    "สร้าง Shortcut ใหม่": "Create shortcut",
    "สถานะและประวัติการอ่าน": "Reading status & history",
    "สถานะการอ่าน": "Reading status",
    "ตั้งเวลาอ่านข้อมูล": "Configure reading schedule",
    "ตรวจสอบรอบบิล": "Review billing cycle",
    "เครื่องมือขั้นสูง": "Advanced tools",
    "แก้ไขเครื่องพิมพ์และราคา": "Edit printers and pricing",
    "ใช้สำหรับตรวจสอบเมื่อข้อมูลไม่อัปเดต ผู้ใช้งานทั่วไปไม่จำเป็นต้องเปิดหน้านี้": "Use this when readings are not updating. General users do not need this page.",
    "เช็กว่าเครื่องใดอ่าน Meter สำเร็จ มีอะไรต้องทำหรือไม่ แล้วค่อยเปิดรายละเอียดเมื่อจำเป็น · Live Log เก็บเฉพาะรอบที่เปิดโปรแกรมนี้ สูงสุด 5,000 เหตุการณ์": "Check which printers were read successfully and whether action is needed. Open technical details only when necessary. The live log keeps up to 5,000 events from this session.",
    "ยังไม่มีเครื่องที่เปิดใช้งาน · ไปที่ตั้งค่าเพื่อเพิ่มเครื่องพิมพ์": "No active printers. Return to Settings to add one.",
    "รอรอบแรก": "Waiting for first reading",
    "ยังไม่มีการอ่าน Web Meter ที่สำเร็จในรอบนี้": "No successful Web Meter reading in this session",
    "รอ Scheduler เริ่มรอบแรก หรือกดอ่านข้อมูลตอนนี้": "Waiting for the first scheduler cycle, or select Read now",
    "← กลับไปการตั้งค่า": "← Back to Settings",
    "ไปตั้งค่ารอบซิงก์": "Open reading schedule",
    "สถานะการซิงก์": "Reading status",
    "ประวัติการอ่าน": "Reading history",
    "การทำงานอัตโนมัติ": "Automation",
    "ดูหลักฐานและรายการที่ระบบพักไว้เพื่อตรวจสอบ โดยไม่เปลี่ยนยอดย้อนหลังอัตโนมัติ": "Review evidence and held records without automatically changing historical totals.",
    "Ledger เป็น append-only: Hold จะไม่ถูกคิดเงิน และการแก้ยอดจะเพิ่ม Reversal + Replacement โดยไม่แก้หรือลบรายการเดิม · ดับเบิลคลิกแถวเพื่อดูหลักฐานครบ": "The Ledger is append-only. Held records are not billed, and corrections add a Reversal and Replacement without editing or deleting the original. Double-click a row to review its evidence.",
    "มีผลต่อยอด": "Effective",
    "Hold รอตรวจ": "Hold for review",
    "Reversal ยังไม่ครบคู่": "Unpaired reversal",
    "รายการแก้ไขทั้งหมด": "All corrections",
    "Event / ผล": "Event / result",
    "สุทธิ": "Net",
    "เชื่อมโยง Ledger": "Linked Ledger",
    "เหตุผล": "Reason",
    "บันทึกเมื่อ": "Recorded at",
    "คำเตือน: การรีเซ็ตหรือปรับ Parser อาจเปลี่ยนผลการอ่านข้อมูล กรุณาตรวจข้อความยืนยันทุกครั้ง": "Warning: resetting data or changing the parser can affect readings. Review every confirmation before continuing.",
    "ลำดับที่": "No.",
    "รายการ": "Item",
    "ค่าเก่า": "Previous value",
    "ค่าใหม่": "New value",
    "วัน/เวลา": "Date/time",
    "คัดลอก": "Copy",
    "ทุกเครื่อง": "All printers",
    "ทุกขั้นตอน": "All stages",
    "ตรวจสถานะ (SNMP)": "Status check (SNMP)",
    "อ่าน Meter (Web)": "Meter reading (Web)",
    "เก็บข้อมูล (RAM / DB)": "Store data (RAM / DB)",
    "กฎระบบ": "System rules",
    "เวลา": "Time",
    "ผลลัพธ์": "Result",
    "ข้อมูลที่อ่านวันนี้พักอยู่ใน Cache ก่อนปิดเป็น Daily Record เมื่อเปลี่ยนวัน · รายละเอียด raw อยู่ในคอลัมน์ด้านขวาเพื่อใช้ตรวจสอบ": "Today's readings stay in the Cache until they are closed into a Daily Record after the date changes. Raw details are available in the right-hand columns for staff review.",
    "รีเฟรชข้อมูลวันนี้": "Refresh today's data",
    "เครื่อง / IP": "Printer / IP",
    "แผนการอ่านข้อมูลวันนี้": "Today's reading schedule",
    "ช่วงเริ่มงาน": "Start-of-day window",
    "ช่วงเลิกงาน": "End-of-day window",
    "รายละเอียดทางเทคนิค": "Technical details",
    "กฎที่ใช้อยู่จริงสำหรับ Scheduler, Web Meter, Cache และการปิดข้อมูลรายวัน": "Current rules for the scheduler, Web Meter, Cache, and daily close.",
    "แสดงตารางรายละเอียดตามช่วงเวลา": "Show schedule details",
    "ขั้นตอน": "Stage",
    "ค่าปัจจุบัน": "Current value",
    "เงื่อนไข / ผลลัพธ์": "Condition / result",
    "ยังไม่มีเครื่องที่เปิดใช้งาน": "No active printers",
    "ค้นหาเหตุผล, counter หรือข้อความในเหตุการณ์...": "Search reasons, counters, or event messages...",
    "คลิกเหตุการณ์เพื่อดู Stage, endpoint และรายละเอียดเชิงเทคนิค": "Activate an event to view its stage, endpoint, and technical details.",
    "ค้นหา User / Account / เครื่อง": "Search users, accounts, or printers",
    "ค้นหา ID, เครื่อง, Serial, เหตุผล, hash หรือวันที่ แล้วกด Enter": "Search by ID, printer, serial number, reason, hash, or date, then press Enter",
    "🔍  ค้นหาชื่อ...": "🔍  Search by name...",
    "ไม่พบ OS registration · เลือก checkbox แล้วกดบันทึกเพื่อเปิดใช้งาน": "No OS registration found. Select the checkbox and save to enable it.",
    "ตรวจ OS registration ไม่ได้ · checkbox แสดงค่าที่บันทึกไว้": "OS registration could not be checked. The checkbox shows the saved setting.",
    "● พร้อมใช้งาน (เปิดจากภายนอก) · Web service พร้อมใช้งาน": "● Ready for LAN access · Web service is running",
    "● พร้อมใช้งานเฉพาะเครื่องนี้ · Web service พร้อมใช้งาน": "● Ready on this computer only · Web service is running",
    "ยังไม่มีการแก้ไข": "No unsaved changes",
    "มีการแก้ไขที่ยังไม่ได้บันทึก": "Changes have not been saved",
    "ซ่อนการตั้งเวลาแบบละเอียด": "Hide custom schedule",
    "ภาพรวมการใช้งานจากเครื่องพิมพ์ทั้งหมด": "Usage overview for all printers",
    "ยังไม่มีเวลาซิงก์ล่าสุด": "No recent reading time",
    "ช่วงรายงาน": "Report period",
    "วันที่เริ่มต้น": "Start date",
    "วันที่สิ้นสุด": "End date",
    "ตัวเลขทั้งหมดในแท็บนี้ใช้ช่วงเวลาเดียวกัน": "All figures in this tab use the same date range.",
    "ช่วงรายงานที่เลือก": "Selected report period",
    "มุมมอง": "View",
    "Timeline รวมตาม Slot · ประวัติ V4.6 ต่อกับ V5 โดยไม่คำนวณ Meter ข้ามการเปลี่ยนเครื่อง และไม่คิดค่าใช้จ่ายย้อนหลัง": "Timeline continuity follows each Slot · V4.6 history continues into V5 without calculating meters across printer replacement or applying historical cost",
    "ตามเครื่อง": "By printer",
    "ค่าใช้จ่ายโดยประมาณ": "Estimated cost",
    "แสดงรายวันเมื่อมี Daily record": "Shown by day when daily records are available",
    "Color, B&W และ Scan": "Color, B&W & Scan",
    "สัดส่วนยอดในช่วงที่เลือก": "Breakdown for the selected period",
    "ยอดจาก User Authentication / Account Track": "Usage from User Authentication / Account Track",
    "ผู้ใช้ที่มีข้อมูล": "Users with data",
    "คน": "users",
    "เฉลี่ยต่อผู้ใช้": "Average per user",
    "ผู้ใช้สูงสุด": "Highest user",
    "เลือกผู้ใช้จากตารางเพื่อกรองกราฟ": "Select a user in the table to filter the charts",
    "ล้างตัวกรอง": "Clear filter",
    "เรียงตามยอดใช้งานในช่วงที่เลือก": "Ranked by usage in the selected period",
    "กดผู้ใช้เพื่อดูการกระจายตามเครื่อง": "Select a user to see usage by printer",
    "ข้อมูล RAM ใช้เพื่อวิเคราะห์การกระจาย ไม่ใช้คำนวณค่าใช้จ่าย": "RAM data is used for distribution analysis, not cost calculation",
    "ยอดช่วงนี้": "Usage in period",
    "เครื่องที่ใช้": "Printers used",
    "ยอดตาม Physical identity ของเครื่อง": "Usage by physical printer identity",
    "เครื่องที่มีการใช้งาน": "Printers with usage",
    "พิมพ์ / ถ่ายเอกสาร": "Print / Copy",
    "กราฟเปรียบเทียบเครื่องพิมพ์ทุกเครื่องพร้อมกัน · คลิกแถวด้านล่างเพื่อดู Meter detail": "Charts compare all printers at once · select a row below to view Meter detail",
    "เปรียบเทียบยอดรายวันของทุกเครื่อง": "Compare daily usage for every printer",
    "แยก Color/B&W รายเครื่อง · ไม่รวม Scan": "Color/B&W by printer · Scan excluded",
    "คลิกชื่อเครื่องเพื่อดูรายละเอียด โดยกราฟยังแสดงทุกเครื่อง": "Select a printer for details; charts continue to show every printer",
    "ควรตรวจสอบ": "Needs review",
    "ค่าล่าสุดสำหรับเครื่องที่เลือก": "Latest values for the selected printer",
    "สำเร็จล่าสุด": "Last successful reading",
    "ยอดในช่วงนี้": "Usage in period",
    "ส่งออก Excel": "Export Excel",
    "ส่งออกรายงานเป็นไฟล์ Excel": "Export the report to Excel",
    "รีเฟรชข้อมูลรายงาน": "Refresh report data",
    "วันที่เริ่มต้นของรายงาน": "Report start date",
    "วันที่สิ้นสุดของรายงาน": "Report end date",
    "ประเภท": "Type",
    "รวม": "Total",
    "ภาพรวมรอบบิล": "Billing cycle overview",
    "ค่ามิเตอร์รายเครื่อง": "Printer meters",
    "ยอดใช้งานและค่าใช้จ่าย": "Usage & cost",
    "รายผู้ใช้": "Users",
    "แนวโน้ม": "Trends",
    "ช่วงรายงาน:": "Report period:",
    "แสดงรายละเอียดค่าใช้จ่าย": "Show cost details",
    "รีเฟรช": "Refresh",
    "ยอดใช้งานรวม": "Total usage",
    "ค่าใช้จ่ายรวม": "Total cost",
    "พิมพ์สี": "Color print",
    "พิมพ์ขาวดำ": "B&W print",
    "สำเนาสี": "Color copy",
    "สำเนาขาวดำ": "B&W copy",
    "แนวโน้มการใช้งาน": "Usage trend",
    "ไม่มี Counter แยกประเภท": "No separate counter",
    "ยังไม่มีข้อมูลสำหรับแสดงใน Overview": "No data to display in Overview",
    "ค่าใช้จ่ายสุทธิ": "Net cost",
    "เครื่องพิมพ์": "Printers",
    "เครื่อง": "Printer",
    "สถานะ": "Status",
    "หน้า": "pages",
    "บาท": "THB",
    "สี": "Color",
    "ขาวดำ": "B&W",
    "ระหว่างวัน": "Provisional",
    "ยืนยันแล้ว": "Confirmed",
    "รายละเอียด": "Details",
    "ทั้งหมด": "All",
    "ปัจจุบัน": "Current",
    "รายวัน": "Daily",
    "รายสัปดาห์": "Weekly",
    "รายเดือน": "Monthly",
    "รายปี": "Yearly",
    "ค้นหา": "Search",
    "บันทึก": "Save",
    "ยกเลิก": "Cancel",
    "ย้อนกลับ": "Back",
    "← ย้อนกลับ": "← Back",
    "ถัดไป →": "Next →",
    "ตรวจสอบ": "Review",
    "สำเร็จ": "Success",
    "ข้อผิดพลาด": "Error",
    "ไม่มีข้อมูล": "No data",
    "ยังไม่มีข้อมูล": "No data yet",
    "ชื่อเครื่อง": "Printer name",
    "ชื่อรุ่น": "Model",
    "สถานะเครื่องพิมพ์": "Printer status",
    "ปริมาณการใช้งาน": "Usage",
    "ค่า": "Value",
    "ดูอย่างเดียว": "read-only",
    "ไม่พบ User Authentication / Account Track ที่เปิดใช้งาน": "No enabled User Authentication / Account Track data",
    "ยังไม่มีข้อมูล User / Account ในช่วงนี้": "No User / Account data for this period",
    "อ่านข้อมูลทันที": "Read now",
    "อ่านข้อมูลล่าสุด": "Read latest data",
    "อ่านข้อมูลล่าสุดจากเครื่องพิมพ์ทุกเครื่อง": "Read latest data from every printer",
    "ดูสถานะการอ่าน": "View reading status",
    "ดูสถานะและประวัติการอ่านข้อมูล": "View reading status and history",
    "เชื่อมต่อและอ่านข้อมูลได้": "Connected and reading successfully",
    "เชื่อมต่อแล้ว": "Connected",
    "หมึก": "Toner",
    "อ่านค่าทุกเครื่องทันที": "Read all printers now",
    "กำลัง Sync": "Syncing",
    "Sync ล่าสุด": "Last sync",
    "ข้อมูลล่าสุด": "Latest data",
    "ยังไม่เคย Sync สำเร็จ": "No successful reading yet",
    "ข้อมูลล่าช้า": "Data delayed",
    "พร้อมใช้งาน": "Ready",
    "ตั้งค่า KOMI Report V5": "Set up KOMI Report V5",
    "ข้อมูลองค์กร": "Organization",
    "องค์กร": "Organization",
    "ข้อมูลสำหรับเริ่มใช้งาน": "Information to get started",
    "นำเครื่องพิมพ์เข้าระบบ": "Add printers securely",
    "ตั้งค่าราคา": "Configure pricing",
    "ราคา": "Pricing",
    "ค้นหาและเชื่อมต่อ": "Discover & connect",
    "ตั้งค่า Pricelist": "Configure price list",
    "ตรวจสอบและเริ่มใช้งาน": "Review & get started",
    "ทดสอบการเชื่อมต่อ": "Test connection",
    "ค้นหาเครื่องพิมพ์อัตโนมัติ": "Find printers automatically",
    "ค้นหาอีกครั้ง": "Search again",
    "ยกเลิกการค้นหา": "Cancel search",
    "ค้นหาไม่พบ? ใช้วิธีอื่น": "Can't find it? Try another method",
    "ซ่อนวิธีอื่น": "Hide other methods",
    "กำหนดช่วง IP": "Specify an IP range",
    "เพิ่ม IP ด้วยตนเอง": "Add IP addresses manually",
    "ตรวจสอบเครื่องที่เลือก": "Check selected printers",
    "กำลังทดสอบพร้อมกัน…": "Testing connections…",
    "เลือกแล้ว 0/3": "Selected 0/3",
    "พร้อมสแกนเครือข่าย": "Ready to scan the network",
    "มีประวัติการใช้งานจาก KOMI Report V4.6?": "Have usage history from KOMI Report V4.6?",
    "นำเข้า Meter/Usage History ตาม Slot · เปลี่ยนเครื่องได้โดยประวัติไม่ขาด และไม่แตะ Billing Ledger": "Import meter/usage history by Slot · printer replacement keeps history continuous and Billing Ledger is unchanged",
    "นำเข้าประวัติ V4.6…": "Import V4.6 history…",
    "กำหนด Slot และจุดติดตั้ง": "Assign Slots and installation points",
    "ชื่อจุดติดตั้ง / แผนก": "Installation point / department",
    "คลิกเพื่อเลือก": "Click to select",
    "เลือก": "Select",
    "สิทธิ์เข้าถึง": "Access",
    "ออนไลน์": "Online",
    "ออฟไลน์": "Offline",
    "พร้อม": "Ready",
    "ยังไม่ทดสอบ": "Not tested",
    "ข้อมูลไม่ครบ": "Incomplete information",
    "กรุณากรอกชื่อบริษัท": "Enter the company name to continue",
    "ตกลง": "OK",
    "ยังทดสอบไม่ผ่าน": "Connection test incomplete",
    "ตรวจสอบการตั้งค่า →": "Review settings →",
    "บันทึกและเริ่มใช้งาน": "Save & get started",
    "ตรวจสอบก่อนเริ่มใช้งาน": "Review before getting started",
    "เครื่องที่เลือก": "Selected printers",
    "วิธีใช้ราคา": "Pricing method",
    "ใช้ราคาเดียวกันทุกเครื่อง": "Use one price list for all printers",
    "ตั้งราคาแยกรายเครื่อง": "Set a price list per printer",
    "ตั้งค่าราคาภายหลัง": "Configure pricing later",
    "วันที่เริ่มใช้ราคาชุดนี้": "Price list effective date",
    "ส่วนลดกระดาษเสีย": "Waste-paper discount",
    "วันสิ้นสุดรอบบิล": "Billing cycle end day",
    "เริ่มนับ Usage วันนี้": "Start tracking usage today",
    "พร้อมเริ่มใช้งาน": "Ready to get started",
    "ตรวจสอบทีละส่วนก่อนบันทึก": "Review each section before saving",
    "แก้ไข": "Edit",
    "ข้อมูลและการทำงานเบื้องหลัง": "Data & background operation",
    "ข้อมูลลงทะเบียน": "Registration data",
    "ยังไม่ส่ง": "Not sent",
    "ระบุชื่อบริษัทสำหรับแสดงในรายงานและการลงทะเบียนโปรแกรม ส่วนวันที่เริ่มใช้และ Version ระบบกำหนดให้เพื่อป้องกันข้อมูลผิด": "Enter the company name shown in reports and used for registration. The start date and version are set automatically to prevent errors.",
    "ชื่อบริษัท *": "Company name *",
    "ชื่อบริษัท:": "Company:",
    "วันที่เริ่มใช้งาน": "Start date",
    "Version ที่ใช้": "Version",
    "เลือกตำแหน่ง…": "Choose location…",
    "นำเข้าฐานข้อมูลเดิม…": "Import existing database…",
    "สร้าง Database ใหม่ที่ Path นี้ · การนำเข้า V4.6 จะนำเข้าเฉพาะ Meter/Usage History": "Create the new database at this path · V4.6 import includes Meter/Usage History only",
    "เช่น บริษัท ตัวอย่าง จำกัด": "e.g. Example Company Limited",
    "<b>ขอบเขตข้อมูลที่ปลอดภัย:</b> ขั้นตอนนี้เก็บชื่อบริษัทไว้ในเครื่องเท่านั้น · ยังไม่ส่ง IP, Serial, Credential, Meter, ผู้ใช้ หรือเอกสารออกภายนอก": "<b>Safe data boundary:</b> This step stores the company name on this computer only · no IP address, serial number, credential, meter, user, or document data is sent externally.",
    "<b>SETUP LAB</b> · หน้านี้ใช้ Wizard ตัวจริง แต่ใช้ฐานข้อมูลชั่วคราวและ Virtual Printer บน LAN ข้อมูลจะไม่ปนกับโปรแกรมที่ใช้งานอยู่": "<b>SETUP LAB</b> · This is the real Wizard using a temporary database and a Virtual Printer on the LAN. Its data is isolated from the installed application.",
    "สแกน Konica Minolta ในเครือข่าย LAN ที่เชื่อมต่ออยู่": "Scan the connected LAN for Konica Minolta printers",
    "ใช้เมื่อเครื่องพิมพ์อยู่นอกช่วงเครือข่ายที่ค้นหาอัตโนมัติ": "Use this when a printer is outside the automatically detected network range",
    "พร้อมค้นหา · ระบบยังไม่ได้สแกนเครือข่าย": "Ready to search · the network has not been scanned yet",
    "เลือกเครื่อง → ตรวจสอบ → สถานะพร้อมใช้งาน จึงกดถัดไปได้": "Select printers → verify connections → continue when every selected printer is ready",
    "ตรวจสอบ SNMP และ Web ของเครื่องพิมพ์ที่เลือก": "Verify SNMP and Web Connection for the selected printers",
    "<b>พร้อมนำเครื่องพิมพ์เข้าระบบ</b><br>เมื่อกดบันทึก ระบบจะเก็บการตั้งค่าในเครื่องและเริ่มตรวจมิเตอร์ตามรอบที่กำหนด": "<b>Ready to add printers</b><br>Saving stores the configuration on this computer and starts scheduled meter checks.",
    "กำหนดราคาต่อหน้าสำหรับ A4/A3 สีและขาวดำ · ราคา 0.00 หมายถึงไม่คิดค่าใช้จ่าย": "Set per-page prices for A4/A3 Color and B&W · 0.00 means no charge",
    "รายการตั้งแต่วันนี้จะใช้ราคาชุดนี้": "Usage from this date will use this price list",
    "<b>ยังไม่คิดค่าใช้จ่ายในขณะนี้</b><br>ระบบจะบันทึกราคา 0.00 ทุกประเภท และสามารถตั้งราคาจริงภายหลังได้จาก Settings": "<b>No charges for now</b><br>All prices will be saved as 0.00. You can configure actual prices later in Settings.",
    "ราคาสำหรับทุกเครื่อง": "Price list for all printers",
    "หน่วย: บาทต่อหน้าที่พิมพ์ · ใส่ 0.00 สำหรับรายการที่ไม่คิดเงิน": "Unit: THB per printed page · enter 0.00 for items that are not charged",
    "ราคาแยกรายเครื่อง": "Price list by printer",
    "กำหนด 4 ราคาของแต่ละเครื่องแยกกัน · แสดงเฉพาะเครื่องที่เลือกในขั้นแรก": "Configure four prices for each printer · only selected printers are shown",
    "ขนาดกระดาษ": "Paper size",
    "สี (Color)": "Color",
    "ขาวดำ (B&W)": "B&W",
    "บาท/หน้า": "THB/page",
    "รอบบิลและส่วนลด": "Billing cycle and discount",
    "หักเปอร์เซ็นต์นี้ออกจากยอดค่าใช้จ่ายรวม": "Deduct this percentage from the total cost",
    "เดือนที่ไม่มีวันที่เลือก จะใช้วันสุดท้ายของเดือน": "Shorter months use their final day",
    "ค่าเริ่มต้นที่แนะนำ  ·  ส่วนลดกระดาษเสีย 2%  ·  สิ้นสุดรอบบิลวันที่ 31": "Recommended defaults · 2% waste-paper discount · billing cycle ends on day 31",
    "ค่าแนะนำ: กระดาษเสีย 2% · ตัดรอบวันที่ 31": "Recommended: 2% waste paper · billing ends on day 31",
    "ค้นหาเครื่องพิมพ์ →": "Find printers →",
    "ขั้นที่ 1: กรอกชื่อบริษัท · วันที่เริ่มใช้และ Version มาจากระบบอัตโนมัติ": "Step 1: Enter the company name · the start date and version are set automatically",
    "ขั้นที่ 2: ค้นหา เลือก และตรวจสอบเครื่องพิมพ์ก่อนนำเข้าระบบ": "Step 2: Find, select, and verify printers before adding them",
    "ขั้นที่ 3: ตั้งราคาตอนนี้ หรือเลือกตั้งค่าภายหลังอย่างชัดเจน": "Step 3: Configure pricing now or explicitly choose to configure it later",
    "ขั้นที่ 4: ตรวจสอบแต่ละส่วนก่อนนำเครื่องพิมพ์เข้าระบบ": "Step 4: Review every section before adding the printers",
    "✓  องค์กร": "✓  Organization",
    "✓  เครื่องพิมพ์": "✓  Printers",
    "✓  ราคา": "✓  Pricing",
    "✓  รอบบิล": "✓  Billing cycle",
    "✓  ข้อมูลและการทำงานเบื้องหลัง": "✓  Data and background operation",
    "✓  ข้อมูลลงทะเบียน": "✓  Registration data",
    "IP เริ่มต้น": "Start IP",
    "IP สิ้นสุด": "End IP",
    "สแกนได้สูงสุด 1,024 IP ต่อครั้ง": "Scan up to 1,024 IP addresses at a time",
    "เริ่ม Advanced scan": "Start advanced scan",
    "กรอก IP ของเครื่องที่ต้องการตั้งค่าได้สูงสุด 3 เครื่อง · Username ใช้ administrator": "Enter up to three printer IP addresses · the username is administrator",
    "เครื่อง": "Printer",
    "เพิ่มเครื่องที่กรอก": "Add entered printers",
    "กำหนด Slot และจุดติดตั้ง": "Assign Slots and installation points",
    "Slot คือจุดติดตั้งหรือแผนก · เปลี่ยนเครื่องในอนาคตให้ใช้ Slot เดิมเพื่อให้ประวัติต่อเนื่อง": "A Slot represents an installation point or department · keep the same Slot when replacing a printer so its history remains continuous",
    "ชื่อจุดติดตั้ง / แผนก": "Installation point / department",
    "เช่น แผนกบัญชี": "e.g. Accounting department",
    "บันทึกและเปิดโปรแกรม": "Save & open the application",
    "องค์กร  ·  1 / 4": "Organization  ·  1 / 4",
    "เครื่องพิมพ์  ·  2 / 4": "Printers  ·  2 / 4",
    "ราคา  ·  3 / 4": "Pricing  ·  3 / 4",
    "ตรวจสอบ  ·  4 / 4": "Review  ·  4 / 4",
    "ข้อมูลวันนี้": "Today's data",
    "วันที่": "Date",
    "วัน": "days",
    "เดือน": "month",
    "รอบบิล": "Billing cycle",
    "ผู้ใช้งาน": "Users",
    "บัญชี": "Account",
    "จำนวนหน้า": "Page count",
    "ค่าใช้จ่าย": "Cost",
    "กำลังโหลดข้อมูล...": "Loading data...",
    "กำลังสร้างหน้าจอ...": "Building workspace...",
    "กำลังเตรียมฐานข้อมูล...": "Preparing database...",
    "กำลังเริ่มต้นโปรแกรม...": "Starting application...",
    "เกิดข้อผิดพลาด": "An error occurred",
    "บันทึกไม่สำเร็จ": "Could not save",
    "เปิด KOMI Report": "Open KOMI Report",
    "  ▸   ภาพรวม": "  ▸   Overview",
    "  ▸   อุปกรณ์": "  ▸   Devices",
    "  ▸   นำเข้า": "  ▸   Import",
    "  ▸   รายงาน": "  ▸   Reports",
    "  ▸   บันทึกการซิงก์": "  ▸   Sync Log",
    "  ▸   ตั้งค่า": "  ▸   Settings",
    "  ▸   คู่มือ": "  ▸   Manual",
    "ปกติ": "Normal",
    "งานสี": "Color jobs",
    "ยอดใช้งาน": "Usage",
    "ภาพรวมวันนี้": "Today's overview",
    "ดูรายงานฉบับเต็ม": "View full report",
    "ปริมาณหมึก": "Toner levels",
    "✏️  แก้ไข": "✏️  Edit",
    "🗑  ลบที่เลือก": "🗑  Delete selected",
    "📥  นำเข้าไฟล์": "📥  Import file",
    "📥  นำเข้ารีพอร์ต": "📥  Import report",
    "📋  ประวัติการอัพโหลดไฟล์": "📋  Import history",
    "ประเภทงาน": "Job type",
    "ส่งออก PNG": "Export PNG",
    "จัดกราฟพอดี": "Fit chart",
    "ทุกช่วง": "All periods",
    "รอบบิลปีนี้": "This year's billing cycles",
    "มุมมอง:": "View:",
    "ช่วงรอบบิล:": "Billing period:",
    "อุปกรณ์ที่แสดง:": "Displayed printers:",
    "ล้าง Live Log": "Clear live log",
    "อ่านสถานะ Cache / DB": "Read Cache / DB status",
    "เวลาเริ่มงาน": "Workday starts",
    "เวลาเลิกงาน": "Workday ends",
    "รอบ SNMP": "SNMP interval",
    "Web ช่วงปกติ": "Normal Web interval",
    "โหลดเพิ่ม": "Load more",
    "ดูรายละเอียด": "View details",
    "เปลี่ยน path": "Change path",
    "📂  เปิดโฟลเดอร์": "📂  Open folder",
    "การตั้งค่าหลัก": "General settings",
    "📖  คู่มือการใช้งาน": "📖  User manual",
    "หมายเหตุสำคัญ": "Important notes",
    "ขั้นตอนภาพรวม": "Workflow overview",
    "อ่านข้อมูลตอนนี้": "Read data now",
    "รายการที่ปรับได้:": "Configurable items:",
    "การคำนวณค่าใช้จ่าย": "Cost calculation",
    "เปิด Diagram แบบเต็ม": "Open full diagram",
    "แก้ไขภายหลัง": "Can be changed later",
    "1. กฎการ Sync": "1. Sync rules",
    "2. การเก็บข้อมูล": "2. Data storage",
    "A3 สี :": "A3 Color:",
    "A4 สี :": "A4 Color:",
    "A3 ขาวดำ :": "A3 B&W:",
    "A4 ขาวดำ :": "A4 B&W:",
    "เครื่อง 1 :": "Printer 1:",
    "เครื่อง 2 :": "Printer 2:",
    "เครื่อง 3 :": "Printer 3:",
    "⚙️  ตั้งค่า": "⚙️  Settings",
    "% กระดาษเสีย :": "Waste paper %:",
    "วันตัดรอบบิล :": "Billing-cycle end day:",
    "📅  วันตัดรอบบิล": "📅  Billing-cycle end day",
    "บันทึกการตั้งค่า": "Save settings",
    "📥  นำเข้า Parser": "📥  Import parser",
    "2  รอบบิลและรายงาน": "2  Billing & reports",
    "💾  บันทึกวันตัดรอบ": "💾  Save billing day",
    "↺  เริ่มตั้งค่าใหม่": "↺  Start setup again",
    "🔄  รีเซท การตั้งค่า": "🔄  Reset settings",
    "🖨  ชื่อเครื่องพิมพ์": "🖨  Printer names",
    "เปลี่ยนโฟลเดอร์สำรอง": "Change archive folder",
    "⚠️  รีเซท การตั้งค่า": "⚠️  Reset settings",
    "💾  บันทึก Price List": "💾  Save price list",
    "💾  บันทึกชื่อเครื่อง": "💾  Save printer names",
    "Web ช่วงเริ่ม/เลิกงาน": "Web at workday boundaries",
    "เรียกเมื่อ Meter เพิ่ม": "Trigger when Meter increases",
    "💾  บันทึก % กระดาษเสีย": "💾  Save waste-paper %",
    "🗑  ล้างข้อมูลการใช้งาน": "🗑  Clear usage history",
    "🗑  รีเซท Parser ทั้งหมด": "🗑  Reset all parsers",
    "ค่าปัจจุบันถูกบันทึกแล้ว": "Current settings saved",
    "ตรวจสถานะและ Total Meter": "Check status and Total Meter",
    "🔧  เปิดการตั้งค่า Parser": "🔧  Open parser settings",
    "แก้ไขเครื่องและ Pricelist": "Edit printers and price lists",
    "1  เครื่องพิมพ์และ Pricelist": "1  Printers & price lists",
    "เลือก Counter ที่แสดงในรายงาน": "Choose counters shown in reports",
    "📄  % กระดาษเสีย (Waste Paper)": "📄  Waste-paper discount (%)",
    "โฟลเดอร์เก็บไฟล์สำรอง (Imported):": "Imported-file archive folder:",
    "📋  ประวัติการเปลี่ยนแปลงการตั้งค่า": "📋  Configuration change history",
    "⚠️  ล้างข้อมูล หรือเริ่มตั้งค่าใหม่": "⚠️  Clear data or start setup again",
    "💰  ราคาต่อแผ่น (บาท) — แยกแต่ละเครื่อง": "💰  Per-page prices (THB) — by printer",
}


# Ordered longest-first at runtime. These fragments cover formatted/dynamic
# status messages while preserving numbers, printer names and technical terms.
_PHRASES: dict[str, str] = {
    " น.": "",
    "เช่น ": "e.g. ",
    "ค่าเริ่มต้น:": "Default:",
    "ระบบจะค้นหาเฉพาะเครือข่าย LAN ที่เครื่องนี้เชื่อมต่อ": "The system searches only the LAN connected to this computer",
    "เลือกเครื่องพิมพ์ได้สูงสุด": "Select up to",
    "พร้อมนำเข้าระบบ": "Ready to add",
    "ผ่าน SNMP และ Web ครบแล้ว": "all SNMP and Web Connection checks passed",
    "พร้อมใช้งาน · SNMP + Web ผ่าน": "Ready · SNMP + Web passed",
    "บันทึกไว้ · รอตรวจสอบรอบนี้": "Saved · waiting for verification in this session",
    "วันที่ ": "Day ",
    " ของเดือน": " of the month",
    "เริ่มใช้งาน": "Started",
    "พร้อมใช้งาน · Meter": "Ready · Meter",
    "ตั้งค่าภายหลัง": "Configure later",
    "ขณะนี้ราคา 0.00 ทุกประเภทและยังไม่คิดค่าใช้จ่าย": "all prices are currently 0.00 and no charges are calculated",
    "ยังไม่เริ่มคิดค่าใช้จ่าย": "Charges are not being calculated yet",
    "ตั้งราคาและรอบบิลภายหลังได้จาก Settings": "Pricing and billing cycle can be configured later in Settings",
    "เก็บในเครื่อง:": "Stored on this computer:",
    "บริษัท, IP, Serial, Credential, Meter และราคา": "company, IP address, serial number, credential, meter, and pricing",
    "ส่งออกภายนอกตอนนี้:": "Sent externally now:",
    "ไม่มี · ตรวจ Meter ผ่าน SNMP ทุก 5 นาที และอ่านหน้าเครื่องเมื่อ Total Meter เพิ่ม": "none · meters are checked via SNMP every 5 minutes and printer pages are read when Total Meter increases",
    "ซองข้อมูลที่จะส่งเมื่อระบบพร้อม:": "Registration envelope when the service is ready:",
    "รุ่นเครื่อง ": "printer models ",
    "ไม่ส่ง:": "Never sent:",
    "ผู้ใช้ หรือเอกสาร": "users or documents",
    "สถานะ:": "Status:",
    "ยังไม่ส่ง · รอ Registration API และ Privacy Notice": "not sent · waiting for the Registration API and Privacy Notice",
    "จบการทดสอบ": "Finish test",
    "ซ่อน Counter ที่มีค่าเป็น 0": "Hide zero-value counters",
    "ซ่อน Counter ที่เป็น 0": "Hide zero-value counters",
    "User Authentication / Account Track ที่เปิดใช้งาน": "enabled User Authentication / Account Track data",
    "RAM · ดูอย่างเดียว": "RAM · read-only",
    "สถานะระบบและเวลาซิงก์ล่าสุด": "System status and latest sync",
    "สถานะยอดยืนยันและยอดระหว่างวัน": "Confirmed and provisional status",
    "แนวโน้มย้อนหลัง 12 เดือน": "12-month trend",
    "ภาพรวมสถานะและยอดใช้งานวันนี้": "Today's status and usage overview",
    "ภาพรวมการใช้งานและสถานะเครื่องพิมพ์": "Usage and printer status overview",
    "ตัวกรองช่วงเวลา": "Period filter",
    "กราฟแนวโน้มการใช้งานแยกตามเครื่อง": "Usage trend by printer",
    "ยังไม่บันทึกใน Billing Ledger": "not posted to the Billing Ledger",
    "ยอดระหว่างวัน": "Provisional usage",
    "Sync ล่าสุด": "Last sync",
    "หน้าจออัปเดต": "Screen updated",
    "ภาพรวมการใช้งาน ค่าใช้จ่าย และข้อมูลย้อนหลังตามรอบบิล": "Usage, cost and billing-cycle history",
    "ข้อมูลวันนี้เป็นค่าระหว่างวัน ยังไม่ถูกบันทึกลง Billing Ledger": "Today's values are provisional and have not been posted to the Billing Ledger",
    "ไม่พบ User Authentication / Account Track ในรอบบิลนี้": "No User Authentication / Account Track data in this billing cycle",
    "ทุกเครื่องที่เลือกต้องผ่านทั้ง SNMP และ Web Connection ก่อนดำเนินการ": "Every selected printer must pass both SNMP and Web Connection tests before continuing",
    "สแกน Konica Minolta ในเครือข่าย แล้วคลิกแถวเพื่อเลือกได้พร้อมกันสูงสุด 3 เครื่อง": "Scan the network for Konica Minolta printers, then select up to three rows",
    "คลิกแถวเพื่อเลือก/ยกเลิกเลือก": "Click a row to select or deselect",
    "เครื่องที่เลือกต้องผ่าน SNMP และ Web Connection ก่อนดำเนินการ": "Selected printers must pass SNMP and Web Connection tests before continuing",
    "กำหนดราคาต่อหน้าสำหรับ A4/A3 สีและขาวดำ": "Set per-page prices for A4/A3 Color and B&W",
    "ราคา 0.00 หมายถึงไม่คิดค่าใช้จ่าย": "A price of 0.00 means no charge",
    "ใช้ราคาชุดเดียวกันทุกเครื่อง หรือกำหนดราคาให้แต่ละเครื่องแยกกัน": "Use one price list for all printers or configure each printer separately",
    "กำหนดวันสิ้นสุดรอบบิลและส่วนลดกระดาษเสีย": "Set the billing-cycle end day and waste-paper discount",
    "เดือนที่ไม่มีวันที่ 31 ใช้วันสุดท้ายแทน": "Shorter months use their final day",
    "เมื่อกดบันทึก ระบบจะเก็บการตั้งค่า เปิด Background และไปหน้า Import": "Saving stores the configuration, starts background metering and opens Import",
    "ยืนยันแล้วจาก Billing Ledger": "Confirmed from Billing Ledger",
    "วันนี้จาก Daily Cache": "Today from Daily Cache",
    "รวมปัจจุบัน": "Current total",
    "ยอดยืนยันจาก Posted Ledger": "Confirmed usage from Posted Ledger",
    "ค่าใช้จ่ายประมาณการ": "Estimated cost",
    "ยังไม่มี Posted Ledger": "No Posted Ledger yet",
    "ยังไม่มีข้อมูลสำหรับช่วงรายงานนี้": "No data for this report period",
    "ยังไม่ได้ตั้งค่าเครื่องพิมพ์": "No printers configured",
    "ไปที่ Settings เพื่อเพิ่ม": "Go to Settings to add",
    "กำลังสแกน Konica Minolta ใน": "Scanning for Konica Minolta printers in",
    "สแกนเครือข่ายเสร็จแล้ว": "Network scan complete",
    "สแกนอัตโนมัติไม่ได้": "Automatic scan unavailable",
    "เลือกแล้ว": "Selected",
    "ทดสอบการเชื่อมต่อผ่านแล้ว": "Connection test passed",
    "ตั้งชื่อเรียกเครื่องก่อนทำขั้นตอนถัดไป": "Name each printer before continuing",
    "กำลังทดสอบ": "Testing",
    "ไม่สามารถเชื่อมต่อได้": "Could not connect",
    "ยืนยันแล้ว": "Posted",
    "วันนี้ +": "Now +",
    "ประมาณการ": "Estimated",
    "ข้อมูลล่าสุด": "Latest data",
    "ตรวจสอบ Sync Log": "Review Sync Log",
    "ยอดรวม Meter": "Total Meter",
    "รับข้อมูลรายเครื่อง": "Read each printer",
    "ตรวจผลรวม": "Validate totals",
    "ตรงกันทั้งหมด": "all matched",
    "อ่านได้": "Read",
    "ล่าสุด": "latest",
    "รายเครื่อง": "By printer",
    "รายละเอียดวันนี้": "Today's details",
    "รวม Public User": "Include Public User",
    "รอ Scheduler เริ่มรอบแรก": "Waiting for the first scheduler cycle",
    "กำลังเริ่มต้นการอ่าน": "Starting readings for",
    " เครื่องรอ Scheduler หรือกำลังอ่าน Meter": " printers waiting for the scheduler or reading meters",
    "ทุกเครื่องปกติ": "All printers are ready",
    "ต้องตรวจสอบ": "Needs attention:",
    "Web Meter ล่าสุดตามรายการด้านล่าง": "latest Web Meter readings are listed below",
    "Web Meter ล่าสุด": "Latest Web Meter",
    "ดูคำแนะนำในแต่ละรายการด้านล่าง": "review the guidance for each item below",
    "ยังไม่มีการอ่าน Web Meter ที่สำเร็จในรอบนี้": "No successful Web Meter reading in this session",
    "รอรอบแรก": "Waiting for first reading",
    "เชื่อมต่อและอ่านข้อมูลได้": "Connected and reading successfully",
    "เชื่อมต่อแล้ว": "Connected",
    "เปิดหน้าตั้งค่าเครื่อง:": "Open printer settings:",
    "สถานะ ": "Status: ",
    "เลือก ": "Select ",
    "ดูเหตุการณ์ที่อ่านจริงจาก": "View actual read events from",
    "ตลอด 1 วัน": "across the day",
    "วันนี้จะอยู่ใน Cache และแพ็กเป็น Daily Record เมื่อโปรแกรมพบว่าเปลี่ยนวัน": "today remains in Cache and is packed into a Daily Record after the date changes",
    "หักออกจากยอดรวมก่อนเก็บเป็น Ledger": "Deducted from the total before posting to the Ledger",
    "พบ OS registration สำหรับเปิดอัตโนมัติแล้ว": "Auto-start OS registration found",
    "เปิดอัตโนมัติเมื่อ Login และย่อใน System Tray": "Start at login and minimize to the System Tray",
    "ใช้สำหรับหักค่าใช้จ่ายกระดาษเสียในรายงานรายเดือน": "Used to discount waste-paper cost in monthly reports",
    "ตรวจรายชื่อ 1–3 เครื่อง, IP, Serial, Credential และราคาต่อหน้า": "Review 1–3 printers, IPs, serial numbers, credentials and per-page prices",
    "รีเซทค่าตั้งค่า": "Reset configuration",
    "กำลังใช้งาน (อ่านอย่างเดียว)": "Current database (read-only)",
    "เปิดหน้าปรับจูน Parser": "Open parser tuning",
    "เลือกให้ตรงกับสิ่งที่ต้องการ": "Choose the operation carefully",
    "แบ่งตามงานที่มีผลต่อรอบบิลและ Background": "Grouped by billing and background impact",
    "รายการที่บันทึกแล้วมีผลกับ Ledger ใหม่เท่านั้น": "Saved changes affect new Ledger entries only",
    "การย้าย Database path ยังไม่รองรับ": "Moving the Database path is not supported",
    "การย้าย Database path ยังไม่รองรับใน V5 local release": "Moving the database is not supported in the V5 local release",
    "ฐานข้อมูลที่กำลังใช้งาน (อ่านอย่างเดียว):": "Current database (read-only):",
    "ค่าเริ่มต้นยังรอการบันทึก": "Default schedule is ready to save",
    "ตั้งเวลาอ่านข้อมูลไว้": "Reading schedule has",
    "หากไม่แน่ใจ ไม่จำเป็นต้องเปลี่ยนค่ารายละเอียด": "If unsure, keep the recommended schedule.",
    "เครื่องนี้:": "This computer:",
    "เครื่องอื่นใน LAN:": "Other computers on the LAN:",
    "ตั้งรหัสแล้ว · Username:": "Access code set · Username:",
    "ระบบไม่แสดงรหัสปัจจุบัน": "The current code is never displayed",
    "รหัส Web ต้องยาวอย่างน้อย": "The Web access code must contain at least",
    "รหัส Web ต้องไม่เกิน": "The Web access code must not exceed",
    "รหัส Web ต้องอยู่ในบรรทัดเดียว": "The Web access code must be on one line",
    "รหัส Web ต้องไม่มีช่องว่างที่ต้นหรือท้าย": "The Web access code must not start or end with spaces",
    "ยังไม่เคย Sync สำเร็จ": "No successful reading yet",
    "ครอบคลุม": "covering",
    "ตอนนี้อยู่ในช่วง": "Current schedule window:",
    "รายละเอียดแผนงานอยู่ที่แท็บ การทำงานอัตโนมัติ": "See the Automation tab for the schedule.",
    "มีประวัติการแก้ไข": "corrected history:",
    "ข้อมูลเก่าก่อนใช้ Ledger": "legacy records before the Ledger:",
    "ข้อมูลใหม่ที่ควรมี Ledger แต่หาย": "new records missing Ledger evidence:",
    "แสดง": "Showing",
    " จาก ": " of ",
    "V5 แสดง path ที่กำลังใช้งานแบบอ่านอย่างเดียว": "V5 shows the active path as read-only",
    "ในรุ่นนี้": "in this release",
    "เพื่อแก้ Mapping ของไฟล์ .txt": "to edit .txt file mappings",
    "ล้างเฉพาะประวัติ หรือกลับสู่หน้าตั้งค่าเครื่องพิมพ์ครั้งแรก": "clear usage history only, or return to first-time printer setup",
    "ชื่อเครื่อง, ราคา, วันตัดรอบ": "printer names, pricing, and billing cycle",
    "SNMP ทุก": "SNMP every",
    "● พร้อมทำงาน": "● Ready",
    "มีผลต่อยอด": "Effective:",
    "Reversal จับคู่แล้ว": "Paired reversal",
    "Reversal ยังไม่ครบคู่": "Unpaired reversal",
    "Hold แก้แล้ว": "Resolved hold",
    "Hold รอตรวจ": "Hold for review",
    "ถูกแทนที่": "Superseded",
    "มีผล": "Effective",
    "Hold รอตรวจ": "holds for review:",
    "Reversal ยังไม่ครบคู่": "unpaired reversals:",
    "เป็นค่าเริ่มต้น": "to defaults",
    "เหตุการณ์ล่าสุด": "recent events",
    "แถวใหม่อยู่ด้านบน": "newest rows appear first",
    "คลิกแถวเพื่อดูรายละเอียดเทคนิค": "activate a row to view technical details",
    "ตอนนี้": "current time",
    "โหมด": "mode",
    "Web ช่วงปกติทุก": "normal Web interval every",
    "เป็นแผนที่ตั้งไว้": "This is the configured schedule",
    "ผลการอ่านจริงดูได้จากแท็บ ประวัติการอ่าน": "Actual results are available in the Reading history tab",
    "ค่าที่ปิด Ledger แล้วจะไม่ถูกคำนวณย้อนหลัง": "Closed Ledger entries are never recalculated",
}

_MONTHS = {
    "ม.ค.": "Jan", "ก.พ.": "Feb", "มี.ค.": "Mar", "เม.ย.": "Apr",
    "พ.ค.": "May", "มิ.ย.": "Jun", "ก.ค.": "Jul", "ส.ค.": "Aug",
    "ก.ย.": "Sep", "ต.ค.": "Oct", "พ.ย.": "Nov", "ธ.ค.": "Dec",
}


def translate_text(text: str) -> str:
    if _language != ENGLISH or not text:
        return text
    if text in _EN:
        return _EN[text]
    translated = text
    replacements = {**_PHRASES, **_MONTHS}
    for source in sorted(replacements, key=len, reverse=True):
        translated = translated.replace(source, replacements[source])
    # Dynamic overview messages contain changing numbers, so translate their
    # stable grammatical parts without touching printer names or other data.
    translated = re.sub(r"ยืนยันแล้ว(?=\s)", "Confirmed", translated)
    translated = re.sub(r"วันนี้(?=\s*[+~0-9])", "Today", translated)
    translated = re.sub(r"รวม(?=\s*[+~0-9])", "Total", translated)
    translated = re.sub(r"(?<=\d)\s*หน้า\b", " pages", translated)
    translated = re.sub(r"(?<=\d)\s*เครื่อง\b", " printers", translated)
    translated = re.sub(r"(?<=\d)\s*รายการ\b", " items", translated)
    translated = re.sub(r"(?<=\d)\s*จุด\b", " checks", translated)
    translated = re.sub(r"(?<=\d)\s*ช่วง\b", " windows", translated)
    translated = re.sub(r"(?<=\d)\s*วัน\b", " days", translated)
    translated = re.sub(r"(?<=\d)\s*นาที", " minutes", translated)
    translated = translated.replace("แผ่น", "sheets")
    return translated


def _property_source(
    widget: QWidget,
    text: str,
    *,
    source_property: str,
    rendered_property: str,
) -> str:
    saved = widget.property(source_property)
    rendered = widget.property(rendered_property)
    # Capture a newly generated Thai message, but never replace the canonical
    # source with an already translated English rendering. A value different
    # from our last rendering is application-generated dynamic text (for
    # example STEP 2 / 3) and becomes the new canonical source.
    if (
        saved is None
        or (rendered is not None and text != str(rendered))
        or any("\u0e00" <= char <= "\u0e7f" for char in text)
    ):
        widget.setProperty(source_property, text)
        return text
    return str(saved)


def _source(widget: QWidget, text: str) -> str:
    return _property_source(
        widget,
        text,
        source_property="i18n_source_text",
        rendered_property="i18n_rendered_text",
    )


def apply_language(root: QWidget) -> None:
    """Translate existing widgets recursively, including tables and tabs."""
    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        if isinstance(widget, (QLabel, QAbstractButton, QGroupBox)):
            original = _source(widget, widget.text())
            rendered = original if _language == THAI else translate_text(original)
            widget.setText(rendered)
            widget.setProperty("i18n_rendered_text", rendered)

        for source_property, rendered_property, getter, setter in (
            (
                "i18n_accessible_name",
                "i18n_rendered_accessible_name",
                widget.accessibleName,
                widget.setAccessibleName,
            ),
            (
                "i18n_accessible_description",
                "i18n_rendered_accessible_description",
                widget.accessibleDescription,
                widget.setAccessibleDescription,
            ),
            (
                "i18n_tooltip",
                "i18n_rendered_tooltip",
                widget.toolTip,
                widget.setToolTip,
            ),
        ):
            current = getter()
            if not current:
                continue
            original = _property_source(
                widget,
                current,
                source_property=source_property,
                rendered_property=rendered_property,
            )
            rendered = original if _language == THAI else translate_text(original)
            setter(rendered)
            widget.setProperty(rendered_property, rendered)

        if isinstance(widget, QTabWidget):
            for index in range(widget.count()):
                key = f"i18n_tab_{index}"
                original = widget.property(key)
                current = widget.tabText(index)
                if original is None or any("\u0e00" <= char <= "\u0e7f" for char in current):
                    original = current
                    widget.setProperty(key, original)
                widget.setTabText(index, str(original) if _language == THAI else translate_text(str(original)))

        if isinstance(widget, QComboBox):
            for index in range(widget.count()):
                original = widget.itemData(index, _ITEM_SOURCE_ROLE)
                current = widget.itemText(index)
                if original is None or any("\u0e00" <= char <= "\u0e7f" for char in current):
                    original = current
                    widget.setItemData(index, original, _ITEM_SOURCE_ROLE)
                widget.setItemText(index, str(original) if _language == THAI else translate_text(str(original)))

        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            original = widget.property("i18n_spin_suffix")
            current = widget.suffix()
            if original is None or any("\u0e00" <= char <= "\u0e7f" for char in current):
                original = current
                widget.setProperty("i18n_spin_suffix", original)
            widget.setSuffix(str(original) if _language == THAI else translate_text(str(original)))

        if isinstance(widget, (QLineEdit, QPlainTextEdit)):
            original = widget.property("i18n_placeholder")
            current = widget.placeholderText()
            if original is None or any("\u0e00" <= char <= "\u0e7f" for char in current):
                original = current
                widget.setProperty("i18n_placeholder", original)
            widget.setPlaceholderText(
                str(original) if _language == THAI else translate_text(str(original))
            )

        if isinstance(widget, QTableWidget):
            for column in range(widget.columnCount()):
                item = widget.horizontalHeaderItem(column)
                if item is not None:
                    original = item.data(_ITEM_SOURCE_ROLE)
                    if original is None or any("\u0e00" <= char <= "\u0e7f" for char in item.text()):
                        original = item.text()
                        item.setData(_ITEM_SOURCE_ROLE, original)
                    item.setText(str(original) if _language == THAI else translate_text(str(original)))
            for row in range(widget.rowCount()):
                for column in range(widget.columnCount()):
                    item = widget.item(row, column)
                    if item is None:
                        continue
                    original = item.data(_ITEM_SOURCE_ROLE)
                    if original is None or any("\u0e00" <= char <= "\u0e7f" for char in item.text()):
                        original = item.text()
                        item.setData(_ITEM_SOURCE_ROLE, original)
                    item.setText(str(original) if _language == THAI else translate_text(str(original)))

    title = root.windowTitle()
    if title:
        original = root.property("i18n_window_title")
        if original is None or any("\u0e00" <= char <= "\u0e7f" for char in title):
            original = title
            root.setProperty("i18n_window_title", original)
        root.setWindowTitle(str(original) if _language == THAI else translate_text(str(original)))

    for widget in widgets:
        hook = getattr(widget, "_apply_i18n_visibility", None)
        if callable(hook):
            hook(_language)
