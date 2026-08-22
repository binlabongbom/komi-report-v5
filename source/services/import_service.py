import os
from dataclasses import dataclass
from pathlib import Path

from config import SLOT_NAMES
from database import archive_import_file, get_cfg, save_reading
from parser import parse_for_slot


@dataclass(frozen=True)
class ParsedImport:
    parser_name: str
    parsed: dict

    @property
    def is_unknown_parser(self) -> bool:
        return self.parser_name == "Unknown"

    def unknown_machine_name(self, fallback_path: str) -> str:
        return self.parsed.get("machine", "") or Path(fallback_path).name


@dataclass(frozen=True)
class SavedImport:
    reading_id: int
    archived_path: Path | None


def configured_profile_slot(slot: int) -> int | None:
    configured_parser_id = get_cfg(f"parser_{slot}", "")
    try:
        return int(configured_parser_id) if configured_parser_id else None
    except (ValueError, TypeError):
        return None


def parse_import_file(slot: int, path: str) -> ParsedImport:
    profile_slot = configured_profile_slot(slot)
    parser_name, parsed = parse_for_slot(path, profile_slot)
    return ParsedImport(parser_name=parser_name, parsed=parsed)


def save_import(slot: int, parsed: dict, path: str) -> SavedImport:
    reading_id = save_reading(slot, parsed, os.path.basename(path))
    card_name = get_cfg(f"machine_name_{slot}", SLOT_NAMES[slot])
    archived_path = archive_import_file(path, card_name)
    return SavedImport(reading_id=reading_id, archived_path=archived_path)
