from __future__ import annotations

from dataclasses import dataclass

from .models import DecodedEntity, RawOidValue


@dataclass(frozen=True)
class TableDefinition:
    category: str
    prefix: str
    columns: dict[str, str]
    name_field: str


TABLES: tuple[TableDefinition, ...] = (
    TableDefinition(
        "Supply",
        "1.3.6.1.2.1.43.11.1.1",
        {"6": "description", "7": "unit", "8": "capacity", "9": "level"},
        "description",
    ),
    TableDefinition(
        "Input tray",
        "1.3.6.1.2.1.43.8.2.1",
        {
            "9": "capacity",
            "10": "level",
            "12": "media_name",
            "13": "name",
            "14": "vendor",
            "15": "model",
            "17": "serial_number",
            "18": "description",
        },
        "name",
    ),
    TableDefinition(
        "Marker counter",
        "1.3.6.1.2.1.43.10.2.1",
        {
            "2": "mark_technology",
            "3": "counter_unit",
            "4": "life_count",
            "5": "power_on_count",
            "6": "process_colorants",
            "7": "spot_colorants",
        },
        "marker_name",
    ),
    TableDefinition(
        "Printer alert",
        "1.3.6.1.2.1.43.18.1.1",
        {"2": "severity", "4": "training_level", "8": "description"},
        "description",
    ),
)


def decode_tables(values: list[RawOidValue]) -> list[DecodedEntity]:
    decoded: list[DecodedEntity] = []
    for table in TABLES:
        rows: dict[str, dict[str, tuple[str, str]]] = {}
        for item in values:
            marker = f"{table.prefix}."
            if not item.oid.startswith(marker):
                continue
            remainder = item.oid[len(marker) :]
            column, separator, index = remainder.partition(".")
            field_name = table.columns.get(column)
            if not separator or not index or not field_name:
                continue
            rows.setdefault(index, {})[field_name] = (item.value, item.oid)

        for index, row in sorted(rows.items()):
            fields = tuple(sorted((name, value) for name, (value, _oid) in row.items()))
            source_oids = tuple(sorted(oid for _value, oid in row.values()))
            name = row.get(table.name_field, (f"{table.category} {index}", ""))[0]
            decoded.append(
                DecodedEntity(
                    category=table.category,
                    index=index,
                    name=name,
                    fields=fields,
                    source_oids=source_oids,
                )
            )
    return decoded
