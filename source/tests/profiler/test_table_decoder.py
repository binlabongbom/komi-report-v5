from __future__ import annotations

from komi_snmp_profiler.models import RawOidValue
from komi_snmp_profiler.table_decoder import decode_tables


def raw(oid: str, value: str) -> RawOidValue:
    return RawOidValue(oid, value, "OctetString")


def test_decodes_supply_columns_by_shared_index() -> None:
    values = [
        raw("1.3.6.1.2.1.43.11.1.1.6.1.1", "Black Toner"),
        raw("1.3.6.1.2.1.43.11.1.1.8.1.1", "100"),
        raw("1.3.6.1.2.1.43.11.1.1.9.1.1", "64"),
    ]
    entities = decode_tables(values)
    assert len(entities) == 1
    assert entities[0].category == "Supply"
    assert entities[0].index == "1.1"
    assert entities[0].name == "Black Toner"
    assert dict(entities[0].fields) == {"capacity": "100", "description": "Black Toner", "level": "64"}


def test_decodes_tray_and_marker_as_separate_entities() -> None:
    values = [
        raw("1.3.6.1.2.1.43.8.2.1.13.1.2", "Tray 2"),
        raw("1.3.6.1.2.1.43.8.2.1.12.1.2", "A3"),
        raw("1.3.6.1.2.1.43.10.2.1.4.1.1", "1200"),
    ]
    entities = decode_tables(values)
    assert [(entity.category, entity.name) for entity in entities] == [
        ("Input tray", "Tray 2"),
        ("Marker counter", "Marker counter 1.1"),
    ]
