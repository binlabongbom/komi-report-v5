from __future__ import annotations

import asyncio
import csv
import json

from komi_snmp_profiler.exporter import export_counter_candidates_csv, export_csv, export_decoded_csv, export_json
from komi_snmp_profiler.models import Confidence, ConnectionSettings, DecodedEntity, DeviceSnapshot, RawOidValue
from komi_snmp_profiler.service import ProfilerService


class FakeCollector:
    async def collect(self, settings: ConnectionSettings):
        return [
            RawOidValue("1.3.6.1.2.1.1.5.0", "bizhub-lab", "OctetString"),
            RawOidValue("1.3.6.1.4.1.18334.1.2.3", "10", "Counter32", 10),
        ], []


def test_service_and_export_do_not_include_community(tmp_path) -> None:
    settings = ConnectionSettings(host="10.0.0.5", community="secret-community")
    snapshot = asyncio.run(ProfilerService(FakeCollector()).scan(settings))

    json_path = export_json(snapshot, tmp_path / "snapshot.json")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["host"] == "10.0.0.5"
    assert payload["scan_mode"] == "quick"
    assert len(payload["entities"]) == 0
    assert len(payload["counter_candidates"]) == 1
    assert "secret-community" not in json_path.read_text(encoding="utf-8")

    csv_path = export_csv(snapshot, tmp_path / "snapshot.csv")
    with csv_path.open(encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][0:3] == ["host", "collected_at", "oid"]
    assert len(rows) == 3

    counter_path = export_counter_candidates_csv(snapshot, tmp_path / "counters.csv")
    counter_text = counter_path.read_text(encoding="utf-8-sig")
    assert "1.3.6.1.4.1.18334.1.2.3" in counter_text
    assert "SNMP Counter" in counter_text


def test_decoded_csv_preserves_fields_and_source_oids(tmp_path) -> None:
    snapshot = DeviceSnapshot.create(
        "10.0.0.5",
        [],
        entities=[
            DecodedEntity(
                category="Supply",
                index="1.1",
                name="Black Toner",
                fields=(("level", "64"),),
                source_oids=("1.3.6.1.2.1.43.11.1.1.9.1.1",),
                confidence=Confidence.MAPPED,
            )
        ],
    )
    path = export_decoded_csv(snapshot, tmp_path / "decoded.csv")
    text = path.read_text(encoding="utf-8-sig")
    assert "Black Toner" in text
    assert '""level"": ""64""' in text
