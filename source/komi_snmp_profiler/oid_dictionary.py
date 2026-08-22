from __future__ import annotations

from dataclasses import dataclass

from .km_counter_profile import KM_COUNTER_DEFINITIONS
from .models import Confidence, InterpretedOid, RawOidValue


@dataclass(frozen=True)
class OidDefinition:
    prefix: str
    canonical_field: str | None
    label: str
    description_th: str
    source: str = "IETF standard MIB"
    confidence: Confidence = Confidence.MAPPED
    exact: bool = False


STANDARD_DEFINITIONS: tuple[OidDefinition, ...] = (
    OidDefinition(
        "1.3.6.1.2.1.1.1.0", "device.description", "System description", "รายละเอียดระบบและรุ่นที่อุปกรณ์ประกาศ", exact=True
    ),
    OidDefinition(
        "1.3.6.1.2.1.1.2.0", "device.object_id", "System object ID", "รหัสชนิดอุปกรณ์ ใช้เลือก Device Profile", exact=True
    ),
    OidDefinition(
        "1.3.6.1.2.1.1.3.0", "device.uptime", "System uptime", "เวลาที่เครื่องทำงานนับจากการเริ่มระบบล่าสุด", exact=True
    ),
    OidDefinition("1.3.6.1.2.1.1.5.0", "device.name", "System name", "ชื่อเครื่องที่กำหนดไว้ในระบบ", exact=True),
    OidDefinition(
        "1.3.6.1.2.1.25.3.2.1.3", "device.model", "Device description", "คำอธิบายหรือรุ่นของอุปกรณ์จาก Host Resources MIB"
    ),
    OidDefinition(
        "1.3.6.1.2.1.43.5.1.1.17", "device.serial_number", "Printer serial number", "หมายเลขประจำเครื่องจาก Printer MIB"
    ),
    OidDefinition(
        "1.3.6.1.2.1.43.10.2.1.4",
        "counter.marker_life",
        "Marker life count",
        "Counter สะสมของชุดพิมพ์ แต่ยังไม่ควรตีความเป็น A4/A3 หรือสีโดยไม่ดู index",
    ),
    OidDefinition(
        "1.3.6.1.2.1.43.10.2.1.5",
        "counter.marker_power_on",
        "Marker power-on count",
        "Counter ของชุดพิมพ์นับตั้งแต่เปิดเครื่องครั้งล่าสุด",
    ),
    OidDefinition(
        "1.3.6.1.2.1.43.11.1.1.6", "supply.description", "Supply description", "ชื่อวัสดุสิ้นเปลือง เช่น toner หรือ drum"
    ),
    OidDefinition("1.3.6.1.2.1.43.11.1.1.8", "supply.capacity", "Supply maximum capacity", "ความจุสูงสุดของวัสดุสิ้นเปลือง"),
    OidDefinition(
        "1.3.6.1.2.1.43.11.1.1.9",
        "supply.level",
        "Supply current level",
        "ระดับวัสดุสิ้นเปลืองปัจจุบัน ต้องจับคู่ index กับชื่อและความจุ",
    ),
    OidDefinition(
        "1.3.6.1.2.1.43.18.1.1.8", "alert.description", "Printer alert", "รายละเอียดคำเตือนหรือข้อผิดพลาดของเครื่อง"
    ),
    OidDefinition("1.3.6.1.2.1.43.8.2.1.12", "tray.media_name", "Input media name", "ชื่อหรือขนาดกระดาษที่กำหนดให้ถาด"),
)

DEFINITIONS = STANDARD_DEFINITIONS + tuple(
    OidDefinition(
        definition.oid,
        definition.canonical_field,
        definition.label,
        definition.description_th,
        source="Bom legacy KM Meter reader profile",
        confidence=Confidence.MAPPED,
        exact=True,
    )
    for definition in KM_COUNTER_DEFINITIONS
)

KM_ENTERPRISE_ROOTS: dict[str, str] = {
    "1.3.6.1.4.1.2590": "Minolta legacy enterprise subtree",
    "1.3.6.1.4.1.9514": "Konica legacy enterprise subtree",
    "1.3.6.1.4.1.18334": "Konica Minolta enterprise subtree",
    "1.3.6.1.4.1.50919": "Konica Minolta current enterprise subtree",
}


def normalize_oid(oid: str) -> str:
    return oid.strip().lstrip(".")


def _matches(oid: str, definition: OidDefinition) -> bool:
    if definition.exact:
        return oid == definition.prefix
    return oid == definition.prefix or oid.startswith(f"{definition.prefix}.")


def interpret(raw: RawOidValue) -> InterpretedOid:
    oid = normalize_oid(raw.oid)
    matching = [definition for definition in DEFINITIONS if _matches(oid, definition)]
    if matching:
        definition = max(matching, key=lambda item: len(item.prefix))
        return InterpretedOid(
            oid=oid,
            value=raw.value,
            data_type=raw.data_type,
            canonical_field=definition.canonical_field,
            label=definition.label,
            description_th=definition.description_th,
            source=definition.source,
            confidence=definition.confidence,
            numeric_value=raw.numeric_value,
        )
    enterprise_source = next(
        (label for root, label in KM_ENTERPRISE_ROOTS.items() if oid == root or oid.startswith(f"{root}.")),
        None,
    )
    if enterprise_source:
        return InterpretedOid(
            oid=oid,
            value=raw.value,
            data_type=raw.data_type,
            canonical_field=None,
            label="Konica Minolta private OID",
            description_th="ค่าเฉพาะผู้ผลิต ยังไม่ระบุความหมายจนกว่าจะมี MIB หรือยืนยันด้วย Calibration",
            source=enterprise_source,
            confidence=Confidence.UNKNOWN,
            numeric_value=raw.numeric_value,
        )
    return InterpretedOid(
        oid=oid,
        value=raw.value,
        data_type=raw.data_type,
        canonical_field=None,
        label="Unknown OID",
        description_th="ยังไม่มีคำอธิบายใน Dictionary",
        source="SNMP walk",
        confidence=Confidence.UNKNOWN,
        numeric_value=raw.numeric_value,
    )


def interpret_all(values: list[RawOidValue]) -> list[InterpretedOid]:
    return [interpret(value) for value in values]
