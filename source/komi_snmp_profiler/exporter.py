from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import DeviceSnapshot, MeterReading


def export_json(snapshot: DeviceSnapshot, destination: str | Path) -> Path:
    path = Path(destination)
    path.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def export_csv(snapshot: DeviceSnapshot, destination: str | Path) -> Path:
    path = Path(destination)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "host",
                "collected_at",
                "oid",
                "value",
                "data_type",
                "canonical_field",
                "label",
                "description_th",
                "source",
                "confidence",
            ]
        )
        for item in snapshot.values:
            writer.writerow(
                [
                    snapshot.host,
                    snapshot.collected_at,
                    item.oid,
                    item.value,
                    item.data_type,
                    item.canonical_field or "",
                    item.label,
                    item.description_th,
                    item.source,
                    item.confidence.value,
                ]
            )
        for item in snapshot.web_counters:
            writer.writerow(
                [
                    snapshot.host,
                    snapshot.collected_at,
                    f"WEB:{item.source_path}",
                    item.count,
                    "Counter",
                    item.canonical_field,
                    item.label,
                    "ค่าจาก Web Connection JSON API",
                    "web_connection",
                    item.confidence.value,
                ]
            )
    return path


def export_decoded_csv(snapshot: DeviceSnapshot, destination: str | Path) -> Path:
    path = Path(destination)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["host", "collected_at", "category", "index", "name", "fields_json", "source_oids", "confidence"]
        )
        for entity in snapshot.entities:
            writer.writerow(
                [
                    snapshot.host,
                    snapshot.collected_at,
                    entity.category,
                    entity.index,
                    entity.name,
                    json.dumps(dict(entity.fields), ensure_ascii=False, sort_keys=True),
                    " | ".join(entity.source_oids),
                    entity.confidence.value,
                ]
            )
    return path


def export_counter_candidates_csv(snapshot: DeviceSnapshot, destination: str | Path) -> Path:
    path = Path(destination)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["host", "collected_at", "oid", "value", "unit", "label", "reason", "confidence"])
        for item in snapshot.counter_candidates:
            writer.writerow(
                [
                    snapshot.host,
                    snapshot.collected_at,
                    item.oid,
                    item.value,
                    item.unit,
                    item.label,
                    item.reason,
                    item.confidence.value,
                ]
            )
    return path


def export_meter_json(reading: MeterReading, destination: str | Path) -> Path:
    path = Path(destination)
    path.write_text(json.dumps(reading.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def export_meter_csv(reading: MeterReading, destination: str | Path) -> Path:
    path = Path(destination)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "schema_version",
                "host",
                "collected_at",
                "canonical_field",
                "label",
                "count",
                "category",
                "source",
                "auth_state",
                "source_path",
                "subject_type",
                "subject_id",
                "subject_name",
                "confidence",
            ]
        )
        for item in reading.counters:
            writer.writerow(
                [
                    reading.schema_version,
                    reading.host,
                    reading.collected_at,
                    item.canonical_field,
                    item.label,
                    item.count,
                    item.category,
                    reading.source,
                    reading.auth_state.value,
                    item.source_path,
                    item.subject_type or "",
                    item.subject_id or "",
                    item.subject_name or "",
                    item.confidence.value,
                ]
            )
    return path
