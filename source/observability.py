"""Small structured logging foundation shared by Desktop and API processes."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from runtime_config import RUNTIME_SETTINGS


class JsonLogFormatter(logging.Formatter):
    """Emit one JSON object per line while retaining ordinary logging calls."""

    _extra_fields = (
        "event",
        "device_slot",
        "operation",
        "duration_ms",
        "request_id",
        "remaining_polls",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self._extra_fields:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(*, log_dir: Path | None = None, console: bool | None = None) -> Path:
    """Configure bounded JSON log files and return their directory.

    This is intentionally idempotent: a second caller in the same process
    reuses the KOMI handler rather than adding duplicate log lines.
    """

    target_dir = log_dir or RUNTIME_SETTINGS.log_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = JsonLogFormatter()
    existing = next(
        (handler for handler in root.handlers if getattr(handler, "_komi_structured", False)),
        None,
    )
    if existing is None:
        log_file = target_dir / f"app-{datetime.now().strftime('%Y%m%d')}.jsonl"
        handler = RotatingFileHandler(
            log_file,
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        handler._komi_structured = True  # type: ignore[attr-defined]
        handler.setFormatter(formatter)
        root.addHandler(handler)
    if console if console is not None else bool(sys.stderr and sys.stderr.isatty()):
        if not any(getattr(handler, "_komi_console", False) for handler in root.handlers):
            stream = logging.StreamHandler(sys.stderr)
            stream._komi_console = True  # type: ignore[attr-defined]
            stream.setFormatter(formatter)
            root.addHandler(stream)
    return target_dir
