# ═══════════════════════════════════════════════════════════
# parser.py — แปลงไฟล์ .txt export จาก Konica Minolta
#
# รองรับ 3 mode:
#   "summary"    — Summary mode (ค่ารวมของเครื่อง)
#   "account"    — User/Account mode (แยกรายบุคคล)
#   "production" — Press machines (C4070, C7090, C12010S, ฯลฯ)
#
# Public API:
#   parse_file(filepath)        → dict  (ข้อมูลที่แปลงแล้ว, มี 'warnings' key)
#   detect_parser(filepath)     → (parser_name: str, parsed: dict)
#   compute_diff(prev, curr)    → dict  (ค่าต่างระหว่าง 2 record)
#   has_warnings(parsed)        → bool
#   format_warnings(parsed)     → str
#   PARSER_REGISTRY             — list ของ parser ทั้งหมด (เพิ่มได้ในอนาคต)
# ═══════════════════════════════════════════════════════════

from parser_profiles import (
    COLS_ACCOUNT,
    COLS_PRODUCTION,
    COLS_SUMMARY,
    COLS_SUMMARY_COMPACT,
    PARSER_REGISTRY,
    find_matching_profile,
)

import json as _json
from pathlib import Path as _Path

_USER_PROFILES_JSON = _Path.home() / "konica_parser_user_profiles.json"


def _find_user_profile(machine_name: str, hdr: list | None = None) -> dict | None:
    """
    โหลด user profiles JSON แล้วหา profile ที่เหมาะสมที่สุด

    ลำดับการตรวจสอบ:
    1. ตรวจสอบ header ของไฟล์ว่าเป็น Account/User mode ไหม
    2. เลือก profile ที่ model match AND types ตรงกับ mode ของไฟล์
    3. ถ้าไม่มี profile ที่ type ตรง → คืน None (ให้ standard parser ทำงาน)
    """
    if not _USER_PROFILES_JSON.exists():
        return None
    try:
        data = _json.loads(_USER_PROFILES_JSON.read_text(encoding="utf-8"))
    except Exception:
        return None

    # ตรวจจับว่าไฟล์นี้เป็น account/user mode จาก header row
    is_account_file = False
    if hdr:
        hdr_joined = " ".join(str(c) for c in hdr).lower()
        is_account_file = "account name" in hdr_joined or "user name" in hdr_joined

    machine_lower = machine_name.lower()
    matched_any = []  # profiles ที่ model match (ไม่สนใจ type)

    for prof in data.get("profiles", []):
        models_str = prof.get("models", "").strip()
        if not models_str:
            continue
        column_map = prof.get("column_map", {})
        if not column_map:
            continue
        model_match = any(
            token and token in machine_lower
            for token in (m.strip().lower() for m in models_str.split(",") if m.strip())
        )
        if not model_match:
            continue

        matched_any.append(prof)
        active_types = prof.get("types", [])
        prof_is_account = "user" in active_types

        # ถ้า type ของ profile ตรงกับ mode ของไฟล์ → คืนทันที (best match)
        if is_account_file and prof_is_account:
            return prof
        if not is_account_file and not prof_is_account:
            return prof

    # ถ้าไม่มี profile ที่ type ตรงกับ file mode → คืน None
    # ให้ standard parser (PARSER_REGISTRY / auto-detect) ทำงานแทน
    return None


def _safe_int(row: list, idx: int) -> int:
    try:
        return int(str(row[idx]).strip()) if idx < len(row) else 0
    except (ValueError, TypeError):
        return 0


def _sum_cols(row: list, val) -> int:
    """บวก column ที่กำหนดใน val (int หรือ list ของ int)"""
    if isinstance(val, list):
        return sum(_safe_int(row, c) for c in val)
    if isinstance(val, int) and val >= 0:
        return _safe_int(row, val)
    return 0


def _parse_from_user_profile(lines: list, machine: str, serial: str,
                              date_s: str, user_prof: dict) -> dict:
    """
    แปลงไฟล์โดยใช้ column_map จาก user profile JSON
    รองรับ summary mode (1 data row) และ account mode (หลาย data rows)

    column_map format: {db_field_key: [col_idx, ...]} หรือ {db_field_key: col_idx}
    db_field_keys: grand_total, full_color_total, bw_total,
                   a4_color, a4_bw, a3_color, a3_bw, user
    """
    col_map = user_prof.get("column_map", {})
    active_types = user_prof.get("types", [])
    is_account_mode = "user" in active_types

    # ── label mode: ใช้ _parse_label ──────────────────────────────────
    if "label" in active_types:
        return _parse_label(lines, machine, serial, date_s, user_prof)

    # ── account mode: หาทุก data rows ──────────────────────────────────
    if is_account_mode:
        user_col_val = col_map.get("user")
        user_col = (user_col_val[0] if isinstance(user_col_val, list) and user_col_val
                    else user_col_val if isinstance(user_col_val, int) else 0)

        drs = [r for i, r in enumerate(lines)
               if i >= 7 and r and len(r) > user_col
               and r[user_col].strip()
               and not r[user_col].strip().startswith("-")]

        if not drs:
            # fallback: แถวใดก็ได้ที่ดูเหมือน data
            drs = [r for i, r in enumerate(lines)
                   if i >= 7 and r and r[0].strip()
                   and not r[0].strip().startswith("-")
                   and not r[0].lower().startswith("paper")]

        accs = []
        for r in drs:
            name = r[user_col].strip() if len(r) > user_col else ""
            if not name:
                continue
            accs.append({
                "name":     name,
                "total":    _sum_cols(r, col_map.get("grand_total")),
                "color_a4": _sum_cols(r, col_map.get("a4_color")),
                "bw_a4":    _sum_cols(r, col_map.get("a4_bw")),
                "color_a3": _sum_cols(r, col_map.get("a3_color")),
                "bw_a3":    _sum_cols(r, col_map.get("a3_bw")),
                # copy/print breakdown — col_map ก่อน, fallback ไป COLS_ACCOUNT standard positions
                "copy_total":    _sum_cols(r, col_map.get("copy_total",    COLS_ACCOUNT.get("copy_total"))),
                "copy_color":    _sum_cols(r, col_map.get("copy_color",    COLS_ACCOUNT.get("copy_color"))),
                "copy_bw":       _sum_cols(r, col_map.get("copy_bw",       COLS_ACCOUNT.get("copy_bw"))),
                "copy_a3_color": _sum_cols(r, col_map.get("copy_a3_color", COLS_ACCOUNT.get("copy_a3_color"))),
                "copy_a3_bw":    _sum_cols(r, col_map.get("copy_a3_bw",    COLS_ACCOUNT.get("copy_a3_bw"))),
                "print_total":    _sum_cols(r, col_map.get("print_total",    COLS_ACCOUNT.get("print_total"))),
                "print_color":    _sum_cols(r, col_map.get("print_color",    COLS_ACCOUNT.get("print_color"))),
                "print_bw":       _sum_cols(r, col_map.get("print_bw",       COLS_ACCOUNT.get("print_bw"))),
                "print_a3_color": _sum_cols(r, col_map.get("print_a3_color", COLS_ACCOUNT.get("print_a3_color"))),
                "print_a3_bw":    _sum_cols(r, col_map.get("print_a3_bw",    COLS_ACCOUNT.get("print_a3_bw"))),
            })

        s = lambda k: sum(a.get(k, 0) for a in accs)
        s_copy_c   = s("copy_color")    + s("copy_a3_color")
        s_copy_bw  = s("copy_bw")       + s("copy_a3_bw")
        s_print_c  = s("print_color")   + s("print_a3_color")
        s_print_bw = s("print_bw")      + s("print_a3_bw")
        return {
            "mode":          "account",
            "machine_name":  machine,
            "serial":        serial,
            "date":          date_s,
            "total_counter": s("total"),
            "summary": {
                "total_color": s("color_a4") + s("color_a3"),
                "total_bw":    s("bw_a4")    + s("bw_a3"),
                "total":       s("total"),
            },
            "paper_size": {"a3": 0, "a4": 0, "b4": 0, "b5": 0},
            "paper_color": {
                "a4_color": s("color_a4"), "a4_bw": s("bw_a4"),
                "a3_color": s("color_a3"), "a3_bw": s("bw_a3"),
            },
            "detail": {
                "copy": {
                    "total": s("copy_total"),
                    "color": s_copy_c,
                    "bw":    s_copy_bw,
                    "a4_color": s("copy_color"),    "a4_bw": s("copy_bw"),
                    "a3_color": s("copy_a3_color"), "a3_bw": s("copy_a3_bw"),
                },
                "print": {
                    "total": s("print_total"),
                    "color": s_print_c,
                    "bw":    s_print_bw,
                    "a4_color": s("print_color"),    "a4_bw": s("print_bw"),
                    "a3_color": s("print_a3_color"), "a3_bw": s("print_a3_bw"),
                },
                "originals": 0,
            },
            "accounts": accs,
            "warnings": [],
            "parser_name":    user_prof.get("name", "User Profile"),
            "profile_mode":   "account",
            "parse_strategy": "account",
        }

    # ── summary mode: ดึง 1 data row ────────────────────────────────────
    dr = next((r for i, r in enumerate(lines) if i >= 5 and r and r[0].isdigit()), None)
    if not dr:
        raise ValueError("ไม่พบแถวข้อมูลใน User Profile (summary mode)")

    grand   = _sum_cols(dr, col_map.get("grand_total"))
    fc      = _sum_cols(dr, col_map.get("full_color_total"))
    bw_tot  = _sum_cols(dr, col_map.get("bw_total"))
    a4c     = _sum_cols(dr, col_map.get("a4_color"))
    a4bw    = _sum_cols(dr, col_map.get("a4_bw"))
    a3c     = _sum_cols(dr, col_map.get("a3_color"))
    a3bw    = _sum_cols(dr, col_map.get("a3_bw"))

    # fallback: ถ้าไม่ได้ map full_color_total / bw_total ให้บวกจาก a4+a3
    if fc == 0:
        fc = a4c + a3c
    if bw_tot == 0:
        bw_tot = a4bw + a3bw

    return {
        "mode":          "summary",
        "machine_name":  machine,
        "serial":        serial,
        "date":          date_s,
        "total_counter": grand,
        "summary": {
            "total_color": fc,
            "total_bw":    bw_tot,
            "total":       grand or fc + bw_tot,
        },
        "paper_size": {"a3": a3c + a3bw, "a4": a4c + a4bw, "b4": 0, "b5": 0},
        "paper_color": {
            "a4_color": a4c, "a4_bw": a4bw,
            "a3_color": a3c, "a3_bw": a3bw,
        },
        "detail": {
            "copy":  {"total": 0, "color": 0, "bw": 0},
            "print": {"total": 0, "color": 0, "bw": 0},
            "originals": 0,
        },
        "accounts": None,
        "warnings": [],
        "parser_name":    user_prof.get("name", "User Profile"),
        "profile_mode":   "summary",
        "parse_strategy": "summary",
    }


# ══════════════════════════════════════════════════════════
# HELPERS — ดึงค่าจากแถวข้อมูลอย่างปลอดภัย
# ══════════════════════════════════════════════════════════

def _gi(row: list, i: int) -> int:
    """ดึงค่า integer จาก row[i] อย่างปลอดภัย (คืน 0 ถ้าผิดพลาด)"""
    try:
        return int(row[i]) if i < len(row) and str(row[i]).strip() else 0
    except (ValueError, IndexError):
        return 0

def _validate_columns(row: list, expected_cols: dict, machine: str) -> list:
    """
    ตรวจสอบว่าคอลัมน์อยู่ในตำแหน่งที่คาดหวัง
    คืนค่า list ของข้อความแจ้งเตือน (ถ้าไม่มีปัญหา จะเป็น list ว่าง)

    Args:
        row: แถวข้อมูลจากไฟล์
        expected_cols: dict {col_name: col_index} เช่น {'Total': 0, 'Originals': 2}
        machine: ชื่อเครื่อง (สำหรับข้อความแจ้งเตือน)
    """
    warnings = []
    num_cols = len(row)
    for col_name, expected_idx in expected_cols.items():
        if expected_idx >= num_cols:
            warnings.append(
                f"⚠ {machine}: ไม่พบคอลัมน์ '{col_name}' ที่ตำแหน่ง {expected_idx} "
                f"(มีเฉพาะ {num_cols} คอลัมน์)"
            )
    return warnings


# ══════════════════════════════════════════════════════════
# PARSE: LABEL MODE (Label 230, hierarchical format)
# ══════════════════════════════════════════════════════════

def _parse_label(lines: list, machine: str, serial: str, date_s: str,
                user_prof: dict = None) -> dict:
    """
    แปลงไฟล์ Label mode (Label 230 - hierarchical format)
    
    ฟอร์แมต (tab-separated with hierarchical structure):
    Row 0: ['Total Counter', '', '', '', '86138', '']
    Row 1: ['Copy', 'Total', '', '', '735', '']
    Row 2: ['', '', 'Full Color', '', '719', '']
    Row 3: ['', '', 'Black', '', '16', '']
    
    Column layout:
    - col[0]: Category (Copy, Printer, Color)
    - col[1]: Type 1 (Total, Full Color, Black)
    - col[2]: Type 2 (continuation if col[1] is empty)
    - col[4]: Value (numeric)
    
    รองรับ column mapping:
        - total_meter: รวม total ทุก category
        - color_meter: Full Color entries
        - bw_meter: Black entries
        - user: category name
    """
    col_map = user_prof.get("column_map", {}) if user_prof else {}
    
    # ── หา data rows (มี value ที่เป็นตัวเลขในคอลัมน์ 4) ───
    # ข้ามแถวแรก 5 แถว (header info)
    drs = []
    for i, row in enumerate(lines):
        if i < 5:  # skip header rows
            continue
        if not row or len(row) < 5:
            continue
        
        val_str = str(row[4]).strip() if len(row) > 4 else ""
        if not val_str or not val_str.isdigit():
            continue
        
        drs.append(row)
    
    if not drs:
        raise ValueError("ไม่พบข้อมูลในไฟล์ label mode")
    
    # ── แยกข้อมูลตามประเภท ───
    meters = {
        "total_meter": 0,
        "color_meter": 0,
        "bw_meter": 0,
    }
    categories = []
    last_category = ""
    
    for row in drs:
        if len(row) < 5:
            continue
        
        # ดึงข้อมูลจากคอลัมน์
        col0 = str(row[0]).strip() if len(row) > 0 else ""
        col1 = str(row[1]).strip() if len(row) > 1 else ""
        col2 = str(row[2]).strip() if len(row) > 2 else ""
        val_str = str(row[4]).strip() if len(row) > 4 else "0"
        
        try:
            value = int(val_str)
        except ValueError:
            continue
        
        # ตรวจสอบการศักตรูกหมวด
        category = col0 if col0 else last_category
        if col0:
            last_category = col0
        
        # ─── แยก Grand Total จากแถว "Total Counter" เท่านั้น ───
        if "total counter" in col0.lower() and not col1 and not col2:
            meters["total_meter"] = value   # ตั้งค่าตรง ๆ ไม่บวกทับ
            last_category = col0

        # ─── Color/BW totals: แถวหลักของ "Color › Total" ───
        elif col0.lower() == "color" and col1.lower() == "total":
            last_category = "color_total_section"   # ทำเครื่องหมายว่าอยู่ใน Color section
            if col2 and "full color" in col2.lower():
                meters["color_meter"] = value
            elif col2 and "black" in col2.lower():
                meters["bw_meter"] = value

        # ─── Sub-rows (col0="" col1="" col2=type) ───
        elif not col0 and not col1 and col2:
            if last_category == "color_total_section":
                # ใต้ "Color › Total" = ยอดรวมของทั้งเครื่อง → OVERRIDE ค่าที่สะสมมา
                if "full color" in col2.lower():
                    meters["color_meter"] = value
                elif "black" in col2.lower() or "bw" in col2.lower():
                    meters["bw_meter"] = value
            # แถวอื่น ๆ (ใต้ Copy/Printer ฯลฯ) ข้ามไป — Color Total จะเป็น source of truth

        type_name = col1 if col1 else col2
        
        categories.append({
            "category": category,
            "type": type_name,
            "value": value,
        })
    
    # ─── ใช้ column mapping ถ้ามี ───
    if col_map:
        mapped_data = {}
        for db_key, col_val in col_map.items():
            if db_key in meters:
                # column_val อาจเป็น int หรือ list ของ int (index ของ data row)
                if isinstance(col_val, (int, list)):
                    # สำหรับ label format ให้ใช้ meters value โดยตรง
                    mapped_data[db_key] = meters[db_key]
        meters.update(mapped_data)
    
    return {
        "mode":          "label",
        "machine_name":  machine,
        "serial":        serial,
        "date":          date_s,
        "total_counter": meters.get("total_meter", 0),
        "summary": {
            "total_color": meters.get("color_meter", 0),
            "total_bw":    meters.get("bw_meter", 0),
            "total":       meters.get("total_meter", 0),
        },
        "paper_size": {"a3": 0, "a4": 0, "b4": 0, "b5": 0},
        "paper_color": {
            "a4_color": 0, "a4_bw": 0,
            "a3_color": 0, "a3_bw": 0,
        },
        "detail": {
            "copy":  {"total": 0, "color": 0, "bw": 0},
            "print": {"total": 0, "color": 0, "bw": 0},
            "originals": 0,
        },
        "accounts": None,
        "meters": meters,  # เพิ่มเติม: meter values สำหรับ Label format
        "categories": categories,  # เพิ่มเติม: categorical breakdown
        "warnings": [],
        "parser_name":    user_prof.get("name", "User Profile - Label") if user_prof else "Auto - Label",
        "profile_mode":   "label",
        "parse_strategy": "label",
    }


# ══════════════════════════════════════════════════════════
# PARSE: SUMMARY MODE
# ══════════════════════════════════════════════════════════

def _parse_summary(lines: list, machine: str, serial: str, date_s: str) -> dict:
    """
    แปลงไฟล์ Summary Mode
    รองรับ 3 รูปแบบ:
    1. Press files (27-31 cols): Compact format, Normal + Large Size
    2. Summary (47+ cols): Detailed with explicit A3/A4 separation
    3. Unknown format: fallback with warnings
    """
    dr = next((r for i, r in enumerate(lines) if i >= 5 and r and r[0].isdigit()), None)
    if not dr:
        raise ValueError("ไม่พบแถวข้อมูลใน Summary mode")

    g = lambda i: _gi(dr, i)
    num_cols = len(dr)

    # ─── Press compact format (25-35 cols) ─────────────────────────────
    if 25 <= num_cols <= 35:
        c = COLS_SUMMARY_COMPACT
        warnings = _validate_columns(dr, {
            'Total Counter':    c["total_counter"],
            'No. of Originals': c["originals"],
            'No. of Prints':    c["prints"],
            'Copy Total':       c["copy_total"],
            'Copy Color':       c["copy_color_a4"],
        }, machine)

        copy_color_a4  = g(c["copy_color_a4"])
        copy_bw_a4     = g(c["copy_bw_a4"])
        copy_color_a3  = g(c["copy_color_a3"])  if num_cols > c["copy_color_a3"]  else 0
        copy_bw_a3     = g(c["copy_bw_a3"])     if num_cols > c["copy_bw_a3"]     else 0
        print_color_a4 = g(c["print_color_a4"]) if num_cols > c["print_color_a4"] else 0
        print_bw_a4    = g(c["print_bw_a4"])    if num_cols > c["print_bw_a4"]    else 0
        print_color_a3 = g(c["print_color_a3"]) if num_cols > c["print_color_a3"] else 0
        print_bw_a3    = g(c["print_bw_a3"])    if num_cols > c["print_bw_a3"]    else 0

        return {
            "mode":          "summary",
            "machine_name":  machine,
            "serial":        serial,
            "date":          date_s,
            "total_counter": g(c["total_counter"]),
            "summary": {
                "total_color": copy_color_a4 + print_color_a4 + copy_color_a3 + print_color_a3,
                "total_bw":   copy_bw_a4 + print_bw_a4 + copy_bw_a3 + print_bw_a3,
                "total":      g(c["grand_total"]),
            },
            "paper_size": {
                "a3": copy_color_a3 + copy_bw_a3 + print_color_a3 + print_bw_a3,
                "a4": copy_color_a4 + copy_bw_a4 + print_color_a4 + print_bw_a4,
                "b4": 0, "b5": 0,
            },
            "paper_color": {
                "a4_color": copy_color_a4 + print_color_a4,
                "a4_bw":    copy_bw_a4    + print_bw_a4,
                "a3_color": copy_color_a3 + print_color_a3,
                "a3_bw":    copy_bw_a3    + print_bw_a3,
            },
            "detail": {
                "copy": {
                    "total": g(c["copy_total"]),
                    "color": copy_color_a4 + copy_color_a3,
                    "bw":    copy_bw_a4    + copy_bw_a3,
                    "a4_color": copy_color_a4, "a4_bw": copy_bw_a4,
                    "a3_color": copy_color_a3, "a3_bw": copy_bw_a3,
                },
                "print": {
                    "total": g(c["prints"]),
                    "color": print_color_a4 + print_color_a3,
                    "bw":    print_bw_a4    + print_bw_a3,
                    "a4_color": print_color_a4, "a4_bw": print_bw_a4,
                    "a3_color": print_color_a3, "a3_bw": print_bw_a3,
                },
                "originals": g(c["originals"]),
            },
            "accounts": None,
            "warnings": warnings,
        }

    # ─── Summary (47+ cols) ────────────────────────────────────────────────
    elif num_cols >= 47:
        c = COLS_SUMMARY
        warnings = _validate_columns(dr, {
            'Total Counter':    c["total_counter"],
            'No. of Originals': c["originals"],
            'No. of Prints':    c["prints"],
            'A4 Color':         c["color_a4"],
            'A4 BW':            c["bw_a4"],
        }, machine)

        c_a4   = g(c["color_a4"])   if num_cols > c["color_a4"]   else 0
        bw_a4  = g(c["bw_a4"])      if num_cols > c["bw_a4"]      else 0
        c_a3   = g(c["color_a3"])   if num_cols > c["color_a3"]   else 0
        bw_a3  = g(c["bw_a3"])      if num_cols > c["bw_a3"]      else 0
        print_c  = g(c["print_color"]) if num_cols > c["print_color"] else 0
        print_bw = g(c["print_bw"])    if num_cols > c["print_bw"]    else 0

        return {
            "mode":          "summary",
            "machine_name":  machine,
            "serial":        serial,
            "date":          date_s,
            "total_counter": g(c["total_counter"]),
            "summary": {
                "total_color": c_a3 + c_a4,
                "total_bw":    bw_a3 + bw_a4,
                "total":       c_a3 + c_a4 + bw_a3 + bw_a4,
            },
            "paper_size": {
                "a3": g(c["a3_size"]) if num_cols > c["a3_size"] else 0,
                "a4": g(c["a4_size"]) if num_cols > c["a4_size"] else 0,
                "b4": g(c["b4_size"]) if num_cols > c["b4_size"] else 0,
                "b5": g(c["b5_size"]) if num_cols > c["b5_size"] else 0,
            },
            "paper_color": {
                "a4_color": c_a4,  "a4_bw": bw_a4,
                "a3_color": c_a3,  "a3_bw": bw_a3,
            },
            "detail": {
                "copy":  {"total": g(c["copy_total"])  if num_cols > c["copy_total"]  else 0,
                          "color": c_a3 + c_a4, "bw": bw_a3 + bw_a4},
                "print": {"total": g(c["print_total"]) if num_cols > c["print_total"] else 0,
                          "color": print_c, "bw": print_bw},
                "originals": g(c["originals"]),
            },
            "accounts": None,
            "warnings": warnings,
        }

    # ─── Unknown format — fallback ─────────────────────────────────────
    else:
        warnings = [
            f"⚠ {machine}: รูปแบบไฟล์ไม่เป็นที่รู้จัก! มี {num_cols} คอลัมน์ "
            f"(ต้องการ 25-35 สำหรับ Press หรือ 47+ สำหรับ Summary mode)"
        ]
        return {
            "mode":          "summary",
            "machine_name":  machine,
            "serial":        serial,
            "date":          date_s,
            "total_counter": g(0),
            "summary": {"total_color": 0, "total_bw": 0, "total": 0},
            "paper_size": {"a3": 0, "a4": 0, "b4": 0, "b5": 0},
            "paper_color": {"a4_color": 0, "a4_bw": 0, "a3_color": 0, "a3_bw": 0},
            "detail": {
                "copy":  {"total": 0, "color": 0, "bw": 0},
                "print": {"total": 0, "color": 0, "bw": 0},
            },
            "accounts": None,
            "warnings": warnings,
        }


# ══════════════════════════════════════════════════════════
# PARSE: PRODUCTION MODE — Press machines
# ══════════════════════════════════════════════════════════

def _parse_production(lines: list, machine: str, serial: str, date_s: str) -> dict:
    """
    แปลงไฟล์ Production mode (Press: C4070, C7090, C12010S, ฯลฯ)

    Column layout (27-31 cols):
      Col 0:  Total Counter
      Col 1:  Total Duplex Counter
      Col 2:  No. of Originals Counter
      Col 3:  No. of Prints Counter
      Col 9:  Copy Total
      Col 10: Copy Color (A4)     Col 11: Copy BW (A4)
      Col 14: Copy Large Color (A3)  Col 15: Copy Large BW (A3)
      Col 18: Printer Total
      Col 19: Print Color (A4)    Col 20: Print BW (A4)
      Col 23: Print Large Color (A3) Col 24: Print Large BW (A3)
      Col 27: Scan Total Color    Col 28: Scan Total BW
    """
    dr = next((r for i, r in enumerate(lines) if i >= 5 and r and r[0].isdigit()), None)
    if not dr:
        raise ValueError("ไม่พบแถวข้อมูลใน Production mode")

    g = lambda i: _gi(dr, i)
    num_cols = len(dr)
    c = COLS_PRODUCTION

    warnings = _validate_columns(dr, {
        'Total Counter':    c["total_counter"],
        'Duplex Counter':   c["duplex"],
        'No. of Originals': c["originals"],
        'No. of Prints':    c["prints"],
        'Copy Total':       c["copy_total"],
    }, machine)

    total_counter   = g(c["total_counter"])
    duplex_counter  = g(c["duplex"])
    originals       = g(c["originals"])
    no_prints       = g(c["prints"])

    copy_total      = g(c["copy_total"])
    copy_color_a4   = g(c["copy_color_a4"])
    copy_bw_a4      = g(c["copy_bw_a4"])
    copy_color_a3   = g(c["copy_color_a3"])  if num_cols > c["copy_color_a3"]  else 0
    copy_bw_a3      = g(c["copy_bw_a3"])     if num_cols > c["copy_bw_a3"]     else 0

    printer_total   = g(c["print_total"])    if num_cols > c["print_total"]    else 0
    print_color_a4  = g(c["print_color_a4"]) if num_cols > c["print_color_a4"] else 0
    print_bw_a4     = g(c["print_bw_a4"])    if num_cols > c["print_bw_a4"]    else 0
    print_color_a3  = g(c["print_color_a3"]) if num_cols > c["print_color_a3"] else 0
    print_bw_a3     = g(c["print_bw_a3"])    if num_cols > c["print_bw_a3"]    else 0

    scan_color      = g(c["scan_color"]) if num_cols > c["scan_color"] else 0
    scan_bw         = g(c["scan_bw"])    if num_cols > c["scan_bw"]    else 0

    return {
        "mode":          "production",
        "machine_name":  machine,
        "serial":        serial,
        "date":          date_s,
        "total_counter": total_counter,
        "summary": {
            "total_color": copy_color_a4 + copy_color_a3 + print_color_a4 + print_color_a3 + scan_color,
            "total_bw":    copy_bw_a4    + copy_bw_a3    + print_bw_a4    + print_bw_a3    + scan_bw,
            "total":       copy_total + printer_total + scan_color + scan_bw,
        },
        "paper_size": {
            "a3": copy_color_a3 + copy_bw_a3 + print_color_a3 + print_bw_a3,
            "a4": copy_color_a4 + copy_bw_a4 + print_color_a4 + print_bw_a4,
            "b4": 0, "b5": 0,
        },
        "paper_color": {
            "a4_color": copy_color_a4 + print_color_a4,
            "a4_bw":    copy_bw_a4    + print_bw_a4,
            "a3_color": copy_color_a3 + print_color_a3,
            "a3_bw":    copy_bw_a3    + print_bw_a3,
        },
        "detail": {
            "copy": {
                "total": copy_total,
                "color": copy_color_a4 + copy_color_a3,
                "bw":    copy_bw_a4    + copy_bw_a3,
                "a4_color": copy_color_a4, "a4_bw": copy_bw_a4,
                "a3_color": copy_color_a3, "a3_bw": copy_bw_a3,
            },
            "print": {
                "total": printer_total,
                "color": print_color_a4 + print_color_a3,
                "bw":    print_bw_a4    + print_bw_a3,
                "a4_color": print_color_a4, "a4_bw": print_bw_a4,
                "a3_color": print_color_a3, "a3_bw": print_bw_a3,
            },
            "originals": originals,
            "duplex": duplex_counter,
            "scan": {"total_color": scan_color, "total_bw": scan_bw},
        },
        "accounts": None,
        "warnings": warnings,
    }


# ══════════════════════════════════════════════════════════
# PARSE: USER MODE — User/Account
# ══════════════════════════════════════════════════════════

def _parse_account(lines: list, machine: str, serial: str, date_s: str) -> dict:
    """
    แปลงไฟล์ User mode — แยกข้อมูลรายบุคคล
    data rows เริ่มที่แถว 7 ขึ้นไป

    Column layout (กำหนดว่าแต่ละค่าต้องแก้ตรงไหนถ้าไม่ตรง):
      Col 0:  User Name                  Col 1:  Total Counter
      Col 8:  A3 Paper Size              Col 9:  A4 Paper Size
      Col 22: Copy Total                 Col 23: Copy Color (A4)         Col 24: Copy BW (A4)
      Col 28: Copy A3 Color              Col 29: Copy A3 BW
      Col 36: Printer Total              Col 37: Print Color (A4)        Col 38: Print BW (A4)
      Col 41: Print A3 Color             Col 42: Print A3 BW
      Col 48: Color A4 (Full)            Col 49: Color A4 BW
      Col 52: Color A3 (Full)            Col 53: Color A3 BW
    """
    c = COLS_ACCOUNT

    drs = [r for i, r in enumerate(lines)
           if i >= 7 and r and r[0]
           and not r[0].startswith("-")
           and not r[0].lower().startswith("paper")]

    warnings = _validate_columns(drs[0], {
        'User Name':     c["name"],
        'Total Counter': c["total"],
        'A3 Size':       c["a3_size"],
        'A4 Size':       c["a4_size"],
        'Copy Total':    c["copy_total"],
        'Copy Color':    c["copy_color"],
    }, machine) if drs else []

    if not drs:
        warnings.append(f"⚠ {machine}: ไม่พบแถวข้อมูลผู้ใช้ (User) ในไฟล์!")

    accs = [{
        "name":       r[c["name"]],
        "total":      _gi(r, c["total"]),
        "originals":  _gi(r, c["originals"]) if len(r) > c["originals"] else 0,
        "a3":         _gi(r, c["a3_size"]),
        "a4":         _gi(r, c["a4_size"]),
        "copy_total":    _gi(r, c["copy_total"]),
        "copy_color":    _gi(r, c["copy_color"]),
        "copy_bw":       _gi(r, c["copy_bw"]),
        "copy_a3_color": _gi(r, c["copy_a3_color"]) if len(r) > c["copy_a3_color"] else 0,
        "copy_a3_bw":    _gi(r, c["copy_a3_bw"])    if len(r) > c["copy_a3_bw"]    else 0,
        "print_total":    _gi(r, c["print_total"]),
        "print_color":    _gi(r, c["print_color"]),
        "print_bw":       _gi(r, c["print_bw"]),
        "print_a3_color": _gi(r, c["print_a3_color"]) if len(r) > c["print_a3_color"] else 0,
        "print_a3_bw":    _gi(r, c["print_a3_bw"])    if len(r) > c["print_a3_bw"]    else 0,
        "color_a4": _gi(r, c["color_a4"]) if len(r) > c["color_a4"] else 0,
        "bw_a4":    _gi(r, c["bw_a4"])    if len(r) > c["bw_a4"]    else 0,
        "color_a3": _gi(r, c["color_a3"]) if len(r) > c["color_a3"] else 0,
        "bw_a3":    _gi(r, c["bw_a3"])    if len(r) > c["bw_a3"]    else 0,
    } for r in drs]

    s = lambda k: sum(a.get(k, 0) for a in accs)

    return {
        "mode":          "account",
        "machine_name":  machine,
        "serial":        serial,
        "date":          date_s,
        "total_counter": s("total"),
        "summary": {
            "total_color": s("color_a4") + s("color_a3"),
            "total_bw":    s("bw_a4")    + s("bw_a3"),
            "total":       s("total"),
        },
        "paper_size": {"a3": s("a3"), "a4": s("a4"), "b4": 0, "b5": 0},
        "paper_color": {
            "a4_color": s("color_a4"), "a4_bw": s("bw_a4"),
            "a3_color": s("color_a3"), "a3_bw": s("bw_a3"),
        },
        "detail": {
            "copy": {
                "total": s("copy_total"),
                "color": s("copy_color") + s("copy_a3_color"),
                "bw":    s("copy_bw")    + s("copy_a3_bw"),
                "a4_color": s("copy_color"),    "a4_bw": s("copy_bw"),
                "a3_color": s("copy_a3_color"), "a3_bw": s("copy_a3_bw"),
            },
            "print": {
                "total": s("print_total"),
                "color": s("print_color") + s("print_a3_color"),
                "bw":    s("print_bw")    + s("print_a3_bw"),
                "a4_color": s("print_color"),    "a4_bw": s("print_bw"),
                "a3_color": s("print_a3_color"), "a3_bw": s("print_a3_bw"),
            },
            "originals": s("originals"),
        },
        "accounts": accs,
        "warnings": warnings,
    }


def _get_data_row_ncols(lines: list) -> tuple[list | None, int]:
    """ดึงแถวข้อมูลแรกและนับจำนวนคอลัมน์ (ใช้ใน detect)"""
    for i, r in enumerate(lines):
        if i >= 5 and r and r[0].isdigit():
            return r, len(r)
    return None, 0


def _load_export_file(filepath: str) -> tuple[list[list[str]], str, str, str, list[str], int]:
    with open(filepath, "rb") as f:
        raw = f.read()

    # [V4.5] เพิ่ม utf-8-sig + cp874 ใน fallback; strip BOM ออก
    text = None
    for enc in ("utf-16", "utf-16-le", "utf-16-be", "utf-8-sig", "utf-8", "cp874"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        raise ValueError("อ่านไฟล์ไม่ได้ — encoding ไม่รองรับ")
    # ตัด BOM ที่อาจติดต้นบรรทัดแรก
    text = text.lstrip("﻿")

    lines = [[c.strip() for c in ln.split("\t")]
             for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]

    def meta(kw: str) -> str:
        """[V4.5] exact match บนคอลัมน์แรก — ไม่ partial match
        (เดิม 'Date' จะ collide กับ 'Print Date', 'Read Date')"""
        kw_low = kw.strip().lower()
        for row in lines:
            if not row:
                continue
            label = row[0].strip().lower().rstrip(":")
            if label == kw_low:
                for v in row[1:]:
                    if v:
                        return v
        return ""

    machine = meta("Machine Name")
    serial = meta("Serial No")
    date_s = meta("Date")
    hdr = lines[3] if len(lines) > 3 else []
    _, ncols = _get_data_row_ncols(lines)
    return lines, machine, serial, date_s, hdr, ncols


def _parse_with_strategy(strategy: str, lines: list, machine: str, serial: str, date_s: str) -> dict:
    if strategy == "production":
        return _parse_production(lines, machine, serial, date_s)
    if strategy == "account":
        return _parse_account(lines, machine, serial, date_s)
    if strategy == "label":
        return _parse_label(lines, machine, serial, date_s)
    return _parse_summary(lines, machine, serial, date_s)


def _decorate_result(parsed: dict, profile: dict | None) -> dict:
    if not profile:
        return parsed

    parsed["parser_name"] = profile.get("name", "Unknown")
    parsed["profile_mode"] = profile.get("mode", "summary")
    parsed["report_type"] = profile.get("report_type", "office_print")
    parsed["parse_strategy"] = profile.get("parse_strategy", "summary")
    return parsed


def detect_parser(filepath: str) -> tuple[str, dict]:
    """
    อ่านไฟล์ ตรวจจับชนิดไฟล์ แล้วเรียก parser ที่เหมาะสม

    Returns:
        (parser_name, parsed_dict)
        parser_name — ชื่อ parser จาก PARSER_REGISTRY เช่น "Summary - C450i"
        parsed_dict — dict ข้อมูลครบถ้วน (เหมือน parse_file)

    หากไม่มี parser ตรงกัน จะ fallback ไปใช้ parse_file ปกติ
    และตั้งชื่อเป็น "Unknown"
    """
    lines, machine, serial, date_s, hdr, ncols = _load_export_file(filepath)

    # ── User Profile (check_parser.py config) มีความสำคัญสูงสุด ──────────
    user_prof = _find_user_profile(machine, hdr)
    if user_prof:
        parsed = _parse_from_user_profile(lines, machine, serial, date_s, user_prof)
        return parsed.get("parser_name", user_prof.get("name", "User Profile")), parsed

    profile = find_matching_profile(machine, serial, hdr, ncols)
    if profile:
        parsed = _decorate_result(
            _parse_with_strategy(profile.get("parse_strategy", "summary"), lines, machine, serial, date_s),
            profile,
        )
        return profile.get("name", "Unknown"), parsed

    parsed = parse_file(filepath)
    parsed.setdefault("parser_name", "Unknown")
    return parsed.get("parser_name", "Unknown"), parsed


def parse_for_slot(filepath: str, profile_slot: "int | None") -> "tuple[str, dict]":
    """
    Parse ไฟล์โดยใช้ Parser Profile ที่กำหนดไว้สำหรับ slot นี้
    profile_slot คือหมายเลข slot ของ Profile (จาก get_cfg("parser_N"))
    ถ้า profile_slot เป็น None หรือไม่พบ Profile → fallback ไปใช้ detect_parser
    """
    if profile_slot is not None:
        try:
            from tools.check_parser import load_profiles
            profiles = load_profiles()
            user_prof = next((p for p in profiles if p.get("slot") == profile_slot), None)
            if user_prof and user_prof.get("column_map"):
                lines, machine, serial, date_s, hdr, ncols = _load_export_file(filepath)
                parsed = _parse_from_user_profile(lines, machine, serial, date_s, user_prof)
                return parsed.get("parser_name", user_prof.get("name", "User Profile")), parsed
        except Exception:
            pass
    return detect_parser(filepath)


# ══════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════

def parse_file(filepath: str) -> dict:
    """
    อ่านและแปลงไฟล์ export จาก Konica Minolta
    รองรับ encoding: UTF-16, UTF-16-LE, UTF-8

    Returns:
        dict ที่มีข้อมูลครบถ้วน พร้อม 'warnings' key (list, ว่างถ้าไม่มีปัญหา)
    """
    lines, machine, serial, date_s, hdr, ncols = _load_export_file(filepath)

    # ── User Profile (check_parser.py config) มีความสำคัญสูงสุด ──────────
    user_prof = _find_user_profile(machine, hdr)
    if user_prof:
        return _parse_from_user_profile(lines, machine, serial, date_s, user_prof)

    profile = find_matching_profile(machine, serial, hdr, ncols)
    if profile:
        return _decorate_result(
            _parse_with_strategy(profile.get("parse_strategy", "summary"), lines, machine, serial, date_s),
            profile,
        )

    # ── Label format detection ─────────────────────────────────────────
    is_label = bool(machine) and "label" in machine.lower()
    if is_label:
        return _decorate_result(_parse_label(lines, machine, serial, date_s), {
            "name": "Fallback - Label mode",
            "mode": "label",
            "report_type": "label_print",
            "parse_strategy": "label",
        })

    is_press = bool(machine) and "press" in machine.lower()
    if is_press:
        return _decorate_result(_parse_production(lines, machine, serial, date_s), {
            "name": "Fallback - Production print",
            "mode": "summary",
            "report_type": "production_print",
            "parse_strategy": "production",
        })

    is_acc = bool(hdr) and (
        "account name" in hdr[0].lower() or
        "user name" in hdr[0].lower()
    )
    if is_acc:
        return _decorate_result(_parse_account(lines, machine, serial, date_s), {
            "name": "Fallback - Office print user",
            "mode": "user",
            "report_type": "office_print",
            "parse_strategy": "account",
        })
    return _decorate_result(_parse_summary(lines, machine, serial, date_s), {
        "name": "Fallback - Office print summary",
        "mode": "summary",
        "report_type": "office_print",
        "parse_strategy": "summary",
    })


def compute_diff(prev: dict, curr: dict) -> dict:
    """
    คำนวณส่วนต่างระหว่างข้อมูล 2 ชุด
    ค่าที่ได้ = max(0, ปัจจุบัน - ก่อนหน้า)
    """
    # [V4.5] ใช้ .get(k, 0) ทุกที่ ป้องกัน KeyError จาก profile ที่มี schema ไม่ครบ
    if not prev or not curr:
        return None

    def d(a, b):
        return None if a is None else max(0, (b or 0) - (a or 0))

    ps = prev.get("summary", {}) or {}
    cs = curr.get("summary", {}) or {}
    result = {k: d(ps.get(k, 0), cs.get(k, 0))
              for k in ("total_color", "total_bw", "total")}

    pp = prev.get("paper_color", {}) or {}
    cp = curr.get("paper_color", {}) or {}
    for k in ("a4_color", "a4_bw", "a3_color", "a3_bw"):
        result[k] = d(pp.get(k, 0), cp.get(k, 0))

    if curr.get("accounts") and prev.get("accounts"):
        adiffs = []
        for a in curr["accounts"]:
            name = a.get("name", "")
            p = next((x for x in prev["accounts"] if x.get("name") == name), None)
            adiffs.append({
                "name":     name,
                "total":    d(p.get("total")    if p else None, a.get("total", 0)),
                "color_a4": d(p.get("color_a4") if p else None, a.get("color_a4", 0)),
                "bw_a4":    d(p.get("bw_a4")    if p else None, a.get("bw_a4", 0)),
                "color_a3": d(p.get("color_a3") if p else None, a.get("color_a3", 0)),
                "bw_a3":    d(p.get("bw_a3")    if p else None, a.get("bw_a3", 0)),
            })
        result["accounts"] = adiffs
    return result


def has_warnings(parsed_data: dict) -> bool:
    """คืน True ถ้าผลการแยกไฟล์มีข้อความแจ้งเตือน"""
    return bool(parsed_data.get("warnings", []))


def format_warnings(parsed_data: dict) -> str:
    """จัดรูปแบบข้อความแจ้งเตือนจาก parse_file() เป็น string"""
    return "\n".join(parsed_data.get("warnings", []))
