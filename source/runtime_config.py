"""Typed runtime configuration with predictable local deployment defaults.

This module deliberately manages operational values only.  Product/UI tokens
remain in :mod:`config`, and user-editable settings (for example price lists)
remain in SQLite.  The precedence is:

``environment > optional local TOML > safe application defaults``.
"""

from __future__ import annotations

import os
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - guarded by project metadata
    tomllib = None  # type: ignore[assignment]


APP_DIRECTORY_NAME = "KOMI Report V5"
CONFIG_FILE_NAME = "runtime.toml"


@dataclass(frozen=True)
class RuntimeSettings:
    """Deployment-owned settings; never store user workflow data here."""

    app_home: Path
    db_path: Path
    log_dir: Path
    api_host: str
    api_port: int
    config_path: Path


def _toml_values(path: Path) -> dict[str, object]:
    if not path.is_file() or tomllib is None:
        return {}
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    runtime = payload.get("runtime", {})
    return dict(runtime) if isinstance(runtime, dict) else {}


def _value(
    name: str,
    *,
    env: Mapping[str, str],
    toml: Mapping[str, object],
    default: str,
) -> str:
    env_value = env.get(f"KOMI_{name}")
    if env_value is not None and env_value.strip():
        return env_value.strip()
    toml_value = toml.get(name.lower())
    if toml_value is not None and str(toml_value).strip():
        return str(toml_value).strip()
    return default


def _positive_int(value: str, *, fallback: int) -> int:
    try:
        return max(1, min(65535, int(value)))
    except ValueError:
        return fallback


def load_runtime_settings(
    environ: Mapping[str, str] | None = None,
    *,
    config_path: Path | None = None,
) -> RuntimeSettings:
    """Load settings without creating files or directories.

    Keeping this function side-effect free makes it safe for tests, packaging
    inspection and API imports.  Directories are created only by the database
    or logging components that actually need them.
    """

    env = os.environ if environ is None else environ
    default_home = Path.home() / APP_DIRECTORY_NAME
    selected_config = config_path or Path(
        env.get("KOMI_RUNTIME_CONFIG", default_home / CONFIG_FILE_NAME)
    )
    toml = _toml_values(selected_config)
    app_home = Path(_value("APP_HOME", env=env, toml=toml, default=str(default_home))).expanduser()
    db_path = Path(
        _value(
            "DB_PATH",
            env=env,
            toml=toml,
            default=str(app_home / "KOMI_Report_V5.db"),
        )
    ).expanduser()
    log_dir = Path(
        _value("LOG_DIR", env=env, toml=toml, default=str(app_home / "logs"))
    ).expanduser()
    return RuntimeSettings(
        app_home=app_home,
        db_path=db_path,
        log_dir=log_dir,
        api_host=_value("API_HOST", env=env, toml=toml, default="127.0.0.1"),
        api_port=_positive_int(
            _value("API_PORT", env=env, toml=toml, default="8766"), fallback=8766
        ),
        config_path=selected_config,
    )


RUNTIME_SETTINGS = load_runtime_settings()


def save_runtime_database_path(path: Path, *, config_path: Path | None = None) -> Path:
    """Persist the database selected during first-run setup without losing other TOML keys."""
    destination = Path(path).expanduser().resolve(strict=False)
    selected_config = Path(config_path or RUNTIME_SETTINGS.config_path)
    selected_config.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = selected_config.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""

    assignment = f"db_path = {json.dumps(str(destination), ensure_ascii=False)}"
    runtime_match = re.search(r"(?ms)^\[runtime\]\s*$.*?(?=^\[|\Z)", current)
    if runtime_match:
        block = runtime_match.group(0)
        if re.search(r"(?m)^\s*db_path\s*=.*$", block):
            updated_block = re.sub(
                r"(?m)^\s*db_path\s*=.*$", assignment, block, count=1
            )
        else:
            updated_block = block.rstrip() + f"\n{assignment}\n"
        updated = current[: runtime_match.start()] + updated_block + current[runtime_match.end() :]
    else:
        separator = "" if not current or current.endswith("\n") else "\n"
        updated = f"{current}{separator}[runtime]\n{assignment}\n"

    temporary = selected_config.with_name(f".{selected_config.name}.tmp")
    temporary.write_text(updated, encoding="utf-8")
    temporary.replace(selected_config)
    return selected_config
