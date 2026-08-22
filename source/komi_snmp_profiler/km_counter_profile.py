from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KmCounterDefinition:
    oid: str
    canonical_field: str
    label: str
    description_th: str


# OIDs recovered from Bom's legacy KM Meter reader project. They are probed
# directly because some bizhub agents answer GET but omit these objects from GETNEXT/GETBULK walks.
KM_COUNTER_DEFINITIONS: tuple[KmCounterDefinition, ...] = (
    KmCounterDefinition(
        "1.3.6.1.4.1.18334.1.1.1.5.7.2.1.1.0",
        "counter.total",
        "Total counter",
        "ปริมาณรวมของเครื่องจาก KM private MIB; ต้องเทียบหน้า Counter ของแต่ละรุ่น",
    ),
    KmCounterDefinition(
        "1.3.6.1.4.1.18334.1.1.1.5.7.2.1.3.0",
        "counter.duplex.total",
        "Total duplex counter",
        "จำนวนกระดาษที่พิมพ์สองหน้ารวม ตรงกับหน้า Total Counter ของ Web Connection",
    ),
    KmCounterDefinition(
        "1.3.6.1.4.1.18334.1.1.1.5.7.2.1.8.0",
        "counter.originals.total",
        "No. of originals",
        "จำนวนต้นฉบับรวม ตรงกับหน้า Total Counter ของ Web Connection",
    ),
    KmCounterDefinition(
        "1.3.6.1.4.1.18334.1.1.1.5.7.2.1.9.0",
        "counter.paper.total",
        "Paper counter",
        "จำนวนแผ่นกระดาษรวม ตรงกับหน้า Total Counter ของ Web Connection",
    ),
    KmCounterDefinition(
        "1.3.6.1.4.1.18334.1.1.1.5.7.2.1.10.0",
        "counter.output_pages.total",
        "No. of total pages output",
        "จำนวนหน้าที่ส่งออกทั้งหมด ตรงกับหน้า Total Counter ของ Web Connection",
    ),
    KmCounterDefinition(
        "1.3.6.1.4.1.18334.1.1.1.5.7.2.2.1.5.1.1",
        "counter.copy.black",
        "Copy Black counter",
        "ปริมาณ Copy ขาวดำจาก profile รุ่นเดิมของ KM Meter reader",
    ),
    KmCounterDefinition(
        "1.3.6.1.4.1.18334.1.1.1.5.7.2.2.1.5.1.2",
        "counter.print.black",
        "Print Black counter",
        "ปริมาณ Print ขาวดำจาก profile รุ่นเดิมของ KM Meter reader",
    ),
    KmCounterDefinition(
        "1.3.6.1.4.1.18334.1.1.1.5.7.2.2.1.5.2.1",
        "counter.copy.color",
        "Copy Color counter",
        "ปริมาณ Copy สีจาก profile รุ่นเดิมของ KM Meter reader",
    ),
    KmCounterDefinition(
        "1.3.6.1.4.1.18334.1.1.1.5.7.2.2.1.5.2.2",
        "counter.print.color",
        "Print Color counter",
        "ปริมาณ Print สีจาก profile รุ่นเดิมของ KM Meter reader",
    ),
    KmCounterDefinition(
        "1.3.6.1.4.1.18334.1.1.1.5.7.2.1.5.0",
        "counter.scan.total",
        "Scan counter",
        "ปริมาณ Scan รวมจาก profile รุ่นเดิมของ KM Meter reader",
    ),
)

KM_COUNTER_BY_OID = {definition.oid: definition for definition in KM_COUNTER_DEFINITIONS}
