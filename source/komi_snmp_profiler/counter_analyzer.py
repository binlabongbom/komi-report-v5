from __future__ import annotations

from .km_counter_profile import KM_COUNTER_BY_OID
from .models import Confidence, CounterCandidate, RawOidValue
from .oid_dictionary import KM_ENTERPRISE_ROOTS

MARKER_ENTRY = "1.3.6.1.2.1.43.10.2.1"
COUNTER_UNITS = {
    3: "0.0001 inch",
    4: "micrometers",
    5: "characters",
    6: "lines",
    7: "impressions",
    8: "sheets",
    9: "dot rows",
    11: "hours",
    16: "feet",
    17: "meters",
}
COUNTER_TYPES = {"Counter32", "Counter64"}


def _is_km_private(oid: str) -> bool:
    return any(oid == root or oid.startswith(f"{root}.") for root in KM_ENTERPRISE_ROOTS)


def _integer(value: int | float | None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    integer = int(value)
    return integer if integer == value else None


def analyze_counter_candidates(values: list[RawOidValue]) -> list[CounterCandidate]:
    by_oid = {item.oid: item for item in values}
    candidates: list[CounterCandidate] = []
    consumed: set[str] = set()

    for item in values:
        definition = KM_COUNTER_BY_OID.get(item.oid)
        if not definition or item.numeric_value is None:
            continue
        candidates.append(
            CounterCandidate(
                oid=item.oid,
                value=item.value,
                numeric_value=item.numeric_value,
                label=definition.label,
                unit="device counter units",
                reason="Targeted KM profile; ต้องเทียบหน้า Counter ของรุ่นเครื่องเพื่อยืนยันหน่วยและความหมาย",
                confidence=Confidence.MAPPED,
            )
        )
        consumed.add(item.oid)

    for item in values:
        for column, label, reason in (
            ("4", "ปริมาณสะสมตลอดอายุเครื่อง", "Printer MIB prtMarkerLifeCount"),
            ("5", "ปริมาณตั้งแต่เปิดเครื่องล่าสุด", "Printer MIB prtMarkerPowerOnCount"),
        ):
            prefix = f"{MARKER_ENTRY}.{column}."
            if not item.oid.startswith(prefix) or item.numeric_value is None:
                continue
            index = item.oid[len(prefix) :]
            unit_item = by_oid.get(f"{MARKER_ENTRY}.3.{index}")
            unit_number = _integer(unit_item.numeric_value) if unit_item else None
            candidates.append(
                CounterCandidate(
                    oid=item.oid,
                    value=item.value,
                    numeric_value=item.numeric_value,
                    label=label,
                    unit=COUNTER_UNITS.get(unit_number, f"unknown ({unit_number})" if unit_number else "unknown"),
                    reason=reason,
                    confidence=Confidence.MAPPED,
                )
            )
            consumed.add(item.oid)

    for item in values:
        integer = _integer(item.numeric_value)
        if item.oid in consumed or integer is None or integer < 0:
            continue
        if item.data_type in COUNTER_TYPES:
            candidates.append(
                CounterCandidate(
                    oid=item.oid,
                    value=item.value,
                    numeric_value=integer,
                    label="SNMP Counter ที่อาจเป็นปริมาณการใช้งาน",
                    unit="unknown",
                    reason=f"ชนิดข้อมูล {item.data_type}; ต้องพิมพ์ทดสอบเพื่อยืนยัน",
                    confidence=Confidence.INFERRED,
                )
            )
        elif _is_km_private(item.oid) and integer > 0:
            candidates.append(
                CounterCandidate(
                    oid=item.oid,
                    value=item.value,
                    numeric_value=integer,
                    label="Konica Minolta numeric candidate",
                    unit="unknown",
                    reason="Private OID ตัวเลข; ยังระบุว่าเป็น Counter ไม่ได้จนกว่า Calibration จะพบ delta",
                    confidence=Confidence.UNKNOWN,
                )
            )

    return sorted(
        candidates,
        key=lambda item: (
            0 if item.confidence == Confidence.MAPPED else 1 if item.confidence == Confidence.INFERRED else 2,
            tuple(int(part) for part in item.oid.split(".")),
        ),
    )
