import json
import logging

from observability import JsonLogFormatter


def test_json_log_formatter_keeps_operational_context():
    record = logging.LogRecord(
        name="komi.polling",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="poll completed: %s",
        args=("printer-1",),
        exc_info=None,
    )
    record.event = "poll_completed"
    record.device_slot = 0
    record.duration_ms = 123
    record.remaining_polls = 1

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["event"] == "poll_completed"
    assert payload["device_slot"] == 0
    assert payload["duration_ms"] == 123
    assert payload["remaining_polls"] == 1
    assert payload["message"] == "poll completed: printer-1"
