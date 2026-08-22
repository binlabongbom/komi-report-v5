from v5_pages import _flatten_ram


def test_flatten_ram_preserves_nested_meter_reading_fields():
    rows = _flatten_ram(
        {
            "host": "192.0.2.10",
            "counters": [
                {"canonical_field": "counter.total.total", "count": 123},
            ],
        }
    )

    assert ("host", "192.0.2.10") in rows
    assert ("counters[0].canonical_field", "counter.total.total") in rows
    assert ("counters[0].count", "123") in rows
