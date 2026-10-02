"""Validated public HTTPS listener port shared by Desktop and Web workers."""

from pathlib import Path

from services.web_access import read_web_runtime_values

DEFAULT_WEB_PORT = 3000
WEB_PORT_KEY = "KOMI_WEB_PORT"


def validate_web_port(value: str | int) -> int:
    text = str(value).strip()
    if not text.isascii() or not text.isdecimal():
        raise ValueError("Web port ต้องเป็นตัวเลข 1024–65535")
    port = int(text)
    if not 1024 <= port <= 65535 or port in {3001, 8766}:
        raise ValueError("Web port ต้องอยู่ระหว่าง 1024–65535 และไม่ใช่ 3001 หรือ 8766")
    return port


def read_web_port(env_path: Path) -> int:
    value = read_web_runtime_values(env_path).get(WEB_PORT_KEY, str(DEFAULT_WEB_PORT))
    return validate_web_port(value)
