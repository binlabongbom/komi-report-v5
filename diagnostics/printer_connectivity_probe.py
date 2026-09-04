from __future__ import annotations

import json
import os
import socket
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOSTS = ("10.244.116.8", "10.244.116.6")


class ReadOnlyInstalledStore:
    def __init__(self, db_path: Path, tls_policy_type, vault_factory) -> None:
        self.db_path = db_path.expanduser().resolve(strict=False)
        self.tls_policy_type = tls_policy_type
        self.errors: dict[str, str] = {}
        try:
            self.vault = vault_factory()
            self.vault_error = ""
        except Exception as exc:
            self.vault = None
            self.vault_error = f"{type(exc).__name__}: {exc}"

    def _row(self, host: str) -> dict[str, object] | None:
        if not self.db_path.is_file():
            return None
        with sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """SELECT slot,name,host,model,serial,credential_ref,tls_mode,tls_fingerprint,
                          connection_status,last_success_at,last_error
                   FROM devices WHERE host=? LIMIT 1""",
                (host,),
            ).fetchone()
        return dict(row) if row is not None else None

    def device_info(self, host: str) -> dict[str, object] | None:
        try:
            return self._row(host)
        except Exception as exc:
            self.errors[host] = f"DB lookup failed: {type(exc).__name__}: {exc}"
            return None

    def load(self, host: str):
        row = self.device_info(host) or {}
        reference = str(row.get("credential_ref") or "")
        if not reference or self.vault is None:
            return None
        try:
            return self.vault.load(reference)
        except Exception as exc:
            self.errors[host] = f"Vault read failed: {type(exc).__name__}: {exc}"
            return None

    def tls_policy(self, host: str):
        row = self.device_info(host) or {}
        try:
            return self.tls_policy_type(
                mode=str(row.get("tls_mode") or "system"),
                fingerprint_sha256=str(row.get("tls_fingerprint") or ""),
            )
        except Exception as exc:
            self.errors[host] = f"TLS policy invalid: {type(exc).__name__}: {exc}"
            return self.tls_policy_type()

    def save(self, _host: str, _credential) -> None:
        raise RuntimeError("diagnostic credential store is read-only")

    def delete(self, _host: str) -> None:
        raise RuntimeError("diagnostic credential store is read-only")


def tcp_probe(host: str, port: int) -> dict[str, object]:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=4):
            pass
        return {"reachable": True, "elapsed_ms": round((time.perf_counter() - started) * 1000), "error": ""}
    except Exception as exc:
        return {
            "reachable": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


def http_probe(host: str, scheme: str) -> dict[str, object]:
    started = time.perf_counter()
    request = urllib.request.Request(
        f"{scheme}://{host}/",
        headers={"User-Agent": "KOMI-Report-V5.2.7-diagnostic"},
        method="GET",
    )
    context = ssl._create_unverified_context() if scheme == "https" else None
    try:
        with urllib.request.urlopen(request, timeout=6, context=context) as response:
            return {
                "reachable": True,
                "status": int(response.status),
                "final_url": response.geturl(),
                "server": response.headers.get("Server", ""),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "error": "",
            }
    except urllib.error.HTTPError as exc:
        return {
            "reachable": True,
            "status": int(exc.code),
            "final_url": exc.geturl(),
            "server": exc.headers.get("Server", "") if exc.headers else "",
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "error": f"HTTPError: {exc}",
        }
    except Exception as exc:
        return {
            "reachable": False,
            "status": None,
            "final_url": "",
            "server": "",
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: printer_connectivity_probe.py OUTPUT.json")

    install_root = Path(os.environ["KOMI_INSTALL"])
    sys.path.insert(0, str(install_root / "source"))

    from komi_snmp_profiler.connectors import TlsPolicy
    from komi_snmp_profiler.credential_store import platform_credential_store
    from komi_snmp_profiler.meter import MeterReader
    from runtime_config import load_runtime_settings
    from services.snmp_probe import SnmpTotalProbe

    settings = load_runtime_settings()
    store = ReadOnlyInstalledStore(settings.db_path, TlsPolicy, platform_credential_store)
    reader = MeterReader(store, allow_implicit_name_export=True, public_factory_credentials=())

    results: dict[str, object] = {
        "diagnostic_mode": "read-only; no counter/history writes; no default-password attempts",
        "computer": os.environ.get("COMPUTERNAME", ""),
        "runner_user": os.environ.get("USERNAME", ""),
        "installed_version": "5.2.7",
        "database_path": str(store.db_path),
        "database_exists": store.db_path.is_file(),
        "vault_init_error": store.vault_error,
        "targets": {},
    }

    for host in HOSTS:
        target: dict[str, object] = {
            "tcp": {"80": tcp_probe(host, 80), "443": tcp_probe(host, 443)},
            "http": http_probe(host, "http"),
            "https": http_probe(host, "https"),
        }
        device = store.device_info(host)
        credential = store.load(host)
        target["configured_device"] = device or {}
        target["credential_available"] = credential is not None
        target["credential_error"] = store.errors.get(host, "")

        model_hint = str((device or {}).get("model") or "")
        try:
            snmp = SnmpTotalProbe(timeout=1.5, retries=0).read(host)
            target["snmp"] = {
                "success": True,
                "total": snmp.total,
                "total_oid": snmp.total_oid,
                "model": snmp.model,
                "serial": snmp.serial,
                "toner": dict(snmp.toner),
                "paper_tray_count": len(snmp.paper_trays),
                "error": "",
            }
            model_hint = model_hint or snmp.model
        except Exception as exc:
            target["snmp"] = {"success": False, "error": f"{type(exc).__name__}: {exc}"}

        try:
            reading = reader.read(host, model=model_hint)
            subjects = [counter for counter in reading.counters if counter.subject_type]
            resolved = [counter for counter in subjects if str(counter.subject_name or "").strip()]
            unresolved = [
                counter
                for counter in subjects
                if str(counter.subject_id or "").strip() and not str(counter.subject_name or "").strip()
            ]
            samples: list[dict[str, object]] = []
            seen: set[tuple[str, str, str]] = set()
            for counter in subjects:
                key = (
                    str(counter.subject_type or ""),
                    str(counter.subject_id or ""),
                    str(counter.subject_name or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                samples.append(
                    {
                        "type": counter.subject_type,
                        "id": counter.subject_id,
                        "name": counter.subject_name,
                        "canonical_field": counter.canonical_field,
                        "count": counter.count,
                    }
                )
                if len(samples) >= 30:
                    break
            target["web_meter"] = {
                "success": True,
                "source": reading.source,
                "auth_state": getattr(reading.auth_state, "value", str(reading.auth_state)),
                "counter_count": len(reading.counters),
                "subject_counter_count": len(subjects),
                "resolved_subject_counter_count": len(resolved),
                "unresolved_subject_counter_count": len(unresolved),
                "resolved_names": sorted({str(item.subject_name).strip() for item in resolved})[:30],
                "unresolved_ids": sorted({str(item.subject_id).strip() for item in unresolved})[:30],
                "subject_samples": samples,
                "warnings": list(reading.warnings),
                "error": "",
            }
        except Exception as exc:
            target["web_meter"] = {
                "success": False,
                "source": "",
                "auth_state": "",
                "counter_count": 0,
                "subject_counter_count": 0,
                "resolved_subject_counter_count": 0,
                "unresolved_subject_counter_count": 0,
                "resolved_names": [],
                "unresolved_ids": [],
                "subject_samples": [],
                "warnings": [],
                "error": f"{type(exc).__name__}: {exc}",
            }

        results["targets"][host] = target

    output = Path(sys.argv[1])
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
