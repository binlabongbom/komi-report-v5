from __future__ import annotations

import copy
import json
from pathlib import Path


PROFILES_PATH = Path(__file__)

MODE_LABELS = {
    "summary": "Summary mode",
    "user": "User mode",
    "label": "Label mode",
}

REPORT_TYPE_LABELS = {
    "office_print": "Office print",
    "production_print": "Production print",
    "label_print": "Label print",
}

MODE_OPTIONS = ["summary", "user", "label"]
REPORT_TYPE_OPTIONS = ["office_print", "production_print", "label_print"]


def normalize_models(models: list[str]) -> list[str]:
    return [model.strip().lower() for model in models if model and model.strip()]


def _user_header_expr(prefix: str = "hdr") -> str:
    return (
        f"(bool({prefix}) and {prefix}[0] and ("
        f'"account name" in {prefix}[0].lower() or "user name" in {prefix}[0].lower()))'
    )


def _model_expr(models_json: str, machine_var: str = "machine") -> str:
    return f"(bool({machine_var}) and any(m in {machine_var}.lower() for m in {models_json}))"


def make_detector(
    mode: str,
    report_type: str,
    models: list[str],
    col_dict_name: str,
    parse_strategy: str | None = None,
):
    norm_models = normalize_models(models)
    machine_matches = lambda machine: bool(machine) and any(model in machine.lower() for model in norm_models)
    user_header = lambda hdr: bool(hdr) and hdr[0] and (
        "account name" in hdr[0].lower() or "user name" in hdr[0].lower()
    )

    if mode == "user" or parse_strategy == "account":
        return lambda machine, serial, hdr, ncols: user_header(hdr) and (
            machine_matches(machine) if norm_models else True
        )

    if mode == "label" or parse_strategy == "label":
        # Label mode: ไม่มี user header, เพียงแค่ match models (ถ้ามี) และมี >= 2 columns
        return lambda machine, serial, hdr, ncols: (
            (machine_matches(machine) if norm_models else True) and ncols >= 2 and not user_header(hdr)
        )

    if report_type == "production_print" or parse_strategy == "production":
        return lambda machine, serial, hdr, ncols: machine_matches(machine) if norm_models else bool(machine)

    def summary_detector(machine, serial, hdr, ncols):
        machine_ok = machine_matches(machine) if norm_models else True
        if col_dict_name == "COLS_SUMMARY_COMPACT":
            col_ok = 25 <= ncols <= 39
        else:
            col_ok = ncols >= 40
        return machine_ok and col_ok and not user_header(hdr)

    return summary_detector


def make_detect_source(
    mode: str,
    report_type: str,
    models: list[str],
    col_dict_name: str,
    parse_strategy: str | None = None,
) -> str:
    norm_models = normalize_models(models)
    models_json = json.dumps(norm_models, ensure_ascii=False)
    machine_match = _model_expr(models_json)
    user_header = _user_header_expr()

    if mode == "user" or parse_strategy == "account":
        machine_clause = machine_match if norm_models else "True"
        return (
            "lambda machine, serial, hdr, ncols: "
            f"({user_header} and {machine_clause})"
        )

    if mode == "label" or parse_strategy == "label":
        machine_clause = machine_match if norm_models else "True"
        return (
            "lambda machine, serial, hdr, ncols: "
            f"({machine_clause} and ncols >= 2 and not {user_header})"
        )

    if report_type == "production_print" or parse_strategy == "production":
        machine_clause = machine_match if norm_models else "bool(machine)"
        return f"lambda machine, serial, hdr, ncols: {machine_clause}"

    machine_clause = machine_match if norm_models else "True"
    cols_clause = "25 <= ncols <= 39" if col_dict_name == "COLS_SUMMARY_COMPACT" else "ncols >= 40"
    return (
        "lambda machine, serial, hdr, ncols: "
        f"({machine_clause} and {cols_clause} and not {user_header})"
    )


def apply_profile_defaults(entry: dict) -> dict:
    mode = entry.get("mode", "summary")
    if mode == "account":
        mode = "user"
    if mode not in MODE_OPTIONS:
        mode = "summary"

    report_type = entry.get("report_type", "office_print")
    if report_type not in REPORT_TYPE_OPTIONS:
        report_type = "office_print"

    entry["mode"] = mode
    entry["report_type"] = report_type

    if mode == "user":
        entry["parse_strategy"] = "account"
        entry["col_dict_name"] = "COLS_ACCOUNT"
    elif mode == "label":
        entry["parse_strategy"] = "label"
        entry["col_dict_name"] = "COLS_LABEL"
    elif report_type == "production_print":
        entry["mode"] = "summary"
        entry["parse_strategy"] = "production"
        entry["col_dict_name"] = "COLS_PRODUCTION"
    else:
        entry["parse_strategy"] = "summary"
        if entry.get("col_dict_name") not in {"COLS_SUMMARY", "COLS_SUMMARY_COMPACT"}:
            entry["col_dict_name"] = "COLS_SUMMARY"

    entry["models"] = normalize_models(entry.get("models", []))
    entry["detect"] = make_detector(
        entry["mode"],
        entry["report_type"],
        entry["models"],
        entry["col_dict_name"],
        entry.get("parse_strategy"),
    )
    return entry


def duplicate_profile(entry: dict | None = None) -> dict:
    if entry is None:
        duplicated = {
            "name": "New Parser Profile",
            "description": "",
            "mode": "summary",
            "report_type": "office_print",
            "parse_strategy": "summary",
            "models": [],
            "col_dict_name": "COLS_SUMMARY",
            "color": "#2563EB",
        }
    else:
        duplicated = copy.deepcopy(entry)
        duplicated["name"] = f"{entry.get('name', 'Parser Profile')} Copy"

    return apply_profile_defaults(duplicated)


def render_registry_entry(entry: dict) -> str:
    rendered = copy.deepcopy(entry)
    apply_profile_defaults(rendered)
    detect = make_detect_source(
        rendered["mode"],
        rendered["report_type"],
        rendered["models"],
        rendered["col_dict_name"],
        rendered.get("parse_strategy"),
    )

    return "\n".join([
        "    {",
        f'        "name":          {json.dumps(rendered.get("name", ""), ensure_ascii=False)},',
        f'        "description":   {json.dumps(rendered.get("description", ""), ensure_ascii=False)},',
        f'        "mode":          {json.dumps(rendered.get("mode", "summary"), ensure_ascii=False)},',
        f'        "report_type":   {json.dumps(rendered.get("report_type", "office_print"), ensure_ascii=False)},',
        f'        "parse_strategy": {json.dumps(rendered.get("parse_strategy", "summary"), ensure_ascii=False)},',
        f'        "models":        {json.dumps(rendered.get("models", []), ensure_ascii=False)},',
        f'        "detect":        {detect},',
        f'        "col_dict_name": {json.dumps(rendered.get("col_dict_name", "COLS_SUMMARY"), ensure_ascii=False)},',
        f'        "color":         {json.dumps(rendered.get("color", "#6B7280"), ensure_ascii=False)},',
        "    }",
    ])


def render_registry(entries: list[dict]) -> str:
    body = ",\n".join(render_registry_entry(entry) for entry in entries)
    return f"PARSER_REGISTRY: list[dict] = [\n{body}\n]"


def replace_registry_block(content: str, entries: list[dict]) -> str:
    start = content.find("PARSER_REGISTRY: list[dict] = [")
    if start < 0:
        raise ValueError("ไม่พบ PARSER_REGISTRY ใน parser_profiles.py")

    end_marker = "# END PARSER_REGISTRY"
    end = content.find(end_marker, start)
    if end < 0:
        raise ValueError("ไม่พบจุดสิ้นสุดของ PARSER_REGISTRY ใน parser_profiles.py")

    return content[:start] + render_registry(entries) + "\n\n" + content[end:]



def find_matching_profile(machine: str, serial: str, hdr: list[str], ncols: int) -> dict | None:
    for entry in PARSER_REGISTRY:
        try:
            if entry["detect"](machine, serial, hdr, ncols):
                return entry
        except Exception:
            continue
    return None


# Summary mode (47+ cols)
COLS_SUMMARY = {
    "total_counter": 0,
    "originals": 2,
    "prints": 3,
    "a3_size": 6,
    "a4_size": 7,
    "b4_size": 8,
    "b5_size": 9,
    "copy_total": 24,
    "print_total": 34,
    "print_color": 60,
    "print_bw": 61,
    "color_a3": 63,
    "color_a4": 64,
    "bw_a3": 73,
    "bw_a4": 74,
}

# Summary compact / Office print compact format (25-39 cols)
COLS_SUMMARY_COMPACT = {
    "total_counter": 0,
    "originals": 2,
    "prints": 3,
    "copy_total": 8,
    "copy_color_a4": 9,
    "copy_bw_a4": 10,
    "copy_color_a3": 13,
    "copy_bw_a3": 14,
    "grand_total": 16,
    "print_color_a4": 17,
    "print_bw_a4": 18,
    "print_color_a3": 20,
    "print_bw_a3": 21,
}

# User mode
COLS_ACCOUNT = {
    "name": 0,
    "total": 1,
    "originals": 3,
    "a3_size": 8,
    "a4_size": 9,
    "copy_total": 22,
    "copy_color": 23,
    "copy_bw": 24,
    "copy_a3_color": 28,
    "copy_a3_bw": 29,
    "print_total": 36,
    "print_color": 37,
    "print_bw": 38,
    "print_a3_color": 41,
    "print_a3_bw": 42,
    "color_a4": 48,
    "bw_a4": 49,
    "color_a3": 52,
    "bw_a3": 53,
}

# Production print summary mode
COLS_PRODUCTION = {
    "total_counter": 0,
    "duplex": 1,
    "originals": 2,
    "prints": 3,
    "copy_total": 9,
    "copy_color_a4": 10,
    "copy_bw_a4": 11,
    "copy_color_a3": 14,
    "copy_bw_a3": 15,
    "print_total": 18,
    "print_color_a4": 19,
    "print_bw_a4": 20,
    "print_color_a3": 23,
    "print_bw_a3": 24,
    "scan_color": 27,
    "scan_bw": 28,
}

# Label mode — หน่วยวัดเป็นเมตร ไม่มี A3/A4 แยก
COLS_LABEL = {
    "total_counter": 0,
    "color_meter": 1,      # จำนวนเมตรสี
    "bw_meter": 2,         # จำนวนเมตรขาวดำ
}


PARSER_REGISTRY: list[dict] = [
    {
        "name":          "Production print - Summary mode",
        "description":   "Production print summary สำหรับ AccurioPress / Press family",
        "mode":          "summary",
        "report_type":   "production_print",
        "parse_strategy": "production",
        "models":        ["c12010", "c4070", "c7090", "c6100", "c3070", "c2060", "accuriopress", "press"],
        "detect":        lambda machine, serial, hdr, ncols: (bool(machine) and any(m in machine.lower() for m in ["c12010", "c4070", "c7090", "c6100", "c3070", "c2060", "accuriopress", "press"])),
        "col_dict_name": "COLS_PRODUCTION",
        "color":         "#7C3AED",
    },
    {
        "name":          "Office print - Summary mode",
        "description":   "Office print summary สำหรับ bizhub/ineo ซีรีส์มาตรฐาน",
        "mode":          "summary",
        "report_type":   "office_print",
        "parse_strategy": "summary",
        "models":        ["c250i", "c300i", "c360i", "c450i", "c550i", "c650i", "c750i", "bizhub", "ineo"],
        "detect":        lambda machine, serial, hdr, ncols: ((bool(machine) and any(m in machine.lower() for m in ["c250i", "c300i", "c360i", "c450i", "c550i", "c650i", "c750i", "bizhub", "ineo"])) and ncols >= 40 and not (bool(hdr) and hdr[0] and ("account name" in hdr[0].lower() or "user name" in hdr[0].lower()))),
        "col_dict_name": "COLS_SUMMARY",
        "color":         "#2563EB",
    },
    {
        "name":          "Office print - Summary mode (Compact)",
        "description":   "Office print summary แบบ compact สำหรับไฟล์ 25-39 คอลัมน์",
        "mode":          "summary",
        "report_type":   "office_print",
        "parse_strategy": "summary",
        "models":        ["c650i", "c750i", "bizhub", "ineo"],
        "detect":        lambda machine, serial, hdr, ncols: ((bool(machine) and any(m in machine.lower() for m in ["c650i", "c750i", "bizhub", "ineo"])) and 25 <= ncols <= 39 and not (bool(hdr) and hdr[0] and ("account name" in hdr[0].lower() or "user name" in hdr[0].lower()))),
        "col_dict_name": "COLS_SUMMARY_COMPACT",
        "color":         "#0EA5E9",
    },
    {
        "name":          "Office print - User mode",
        "description":   "Office print user/account report สำหรับ bizhub/ineo",
        "mode":          "user",
        "report_type":   "office_print",
        "parse_strategy": "account",
        "models":        ["c250i", "c300i", "c360i", "c450i", "c550i", "c650i", "c750i", "bizhub", "ineo"],
        "detect":        lambda machine, serial, hdr, ncols: ((bool(hdr) and hdr[0] and ("account name" in hdr[0].lower() or "user name" in hdr[0].lower())) and (bool(machine) and any(m in machine.lower() for m in ["c250i", "c300i", "c360i", "c450i", "c550i", "c650i", "c750i", "bizhub", "ineo"]))),
        "col_dict_name": "COLS_ACCOUNT",
        "color":         "#059669",
    }
]

# END PARSER_REGISTRY


for _entry in PARSER_REGISTRY:
    apply_profile_defaults(_entry)