"""Deterministic evidence and fail-closed contracts for Phase 4 artifacts."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from tools.release_safety import ReleaseSafetyError, scan_files

WINDOWS_X64_MACHINES = frozenset({"amd64", "x86_64"})
UPDATE_RUNTIME_PATH_TOKENS = frozenset(
    {
        "signed_manifest",
        "update_client",
        "update_manifest",
        "update_service",
        "updater",
    }
)
UPDATE_RUNTIME_CODE_MARKERS = (
    "KOMI_UPDATE_",
    "/api/v1/update",
    '"forced_update"',
    '"remote_update"',
    '"silent_update"',
    '"update_check"',
    '"update_event"',
)
REQUIREMENT_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")
NATIVE_DEPENDENCY_ROOTS = (
    "node-runtime/node_modules/",
    "web-runtime-seed/.next/",
    "web-runtime-seed/node_modules/",
)


class ReleaseContractError(RuntimeError):
    """A release condition is missing; never downgrade this to a warning."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_windows_x64(
    *,
    platform_name: str | None = None,
    machine: str | None = None,
) -> dict[str, str]:
    platform_name = platform_name or sys.platform
    machine = (machine or platform.machine()).strip().casefold()
    if platform_name != "win32" or machine not in WINDOWS_X64_MACHINES:
        raise ReleaseContractError(
            f"Windows x64 target-native build required; got platform={platform_name}, machine={machine or 'unknown'}"
        )
    return {"platform": platform_name, "machine": machine, "evidence_level": "target-native-build"}


def build_environment_label(*, platform_name: str, machine: str, virtualized: bool) -> str:
    machine = machine.strip().casefold()
    if platform_name == "win32" and machine in WINDOWS_X64_MACHINES and not virtualized:
        return "windows-x64-native"
    if platform_name == "win32" and machine in WINDOWS_X64_MACHINES:
        return "windows-x64-vm-preflight"
    if platform_name == "win32":
        return f"windows-{machine or 'unknown'}-vm-preflight"
    return f"{platform_name}-{machine or 'unknown'}-local-preflight"


def _runtime_text_files(root: Path) -> Iterable[Path]:
    allowed = {".cmd", ".js", ".mjs", ".ps1", ".py", ".ts", ".tsx"}
    return (path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() in allowed)


def assert_no_update_runtime_paths(root: Path) -> None:
    """Reject Phase 3 code/config in the installed runtime payload.

    Ordinary business uses of words such as ``updated_at`` remain valid.  The
    gate targets only explicit update-service modules, commands, endpoints and
    environment controls.
    """

    findings: list[str] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        normalized_parts = {
            re.sub(r"[^a-z0-9_]+", "_", part.casefold()).strip("_")
            for part in path.parts
        }
        if normalized_parts.intersection(UPDATE_RUNTIME_PATH_TOKENS):
            findings.append(relative)
    for path in _runtime_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(marker in text for marker in UPDATE_RUNTIME_CODE_MARKERS):
            findings.append(path.relative_to(root).as_posix())
    if findings:
        raise ReleaseContractError(
            "Phase 3 Update runtime path found: " + ", ".join(sorted(set(findings))[:20])
        )


def assert_registration_fail_closed_payload(root: Path) -> None:
    forbidden_names = {
        "registration-policy.json",
        "registration_policy.json",
        "registration-bootstrap.json",
        "registration_bootstrap.json",
    }
    findings = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name.casefold() in forbidden_names
    ]
    if findings:
        raise ReleaseContractError(
            "Release payload must not enable Registration: " + ", ".join(sorted(findings))
        )


def assert_native_payload_safe(root: Path) -> None:
    """Reuse Phase 0 scanning while allowing only bundled production dependencies.

    ``node_modules`` and generated ``dist`` directories are forbidden in source
    artifacts. A self-contained native runtime needs its traced production Node
    dependencies, so only ``forbidden-path`` findings below the two explicit
    runtime roots are filtered. Credential files, forbidden file types and
    secret patterns remain blocking everywhere.
    """

    files = [path for path in root.rglob("*") if path.is_file()]
    findings = scan_files(files, root=root)
    blocking = [
        finding
        for finding in findings
        if not (
            finding.category == "forbidden-path"
            and finding.path.startswith(NATIVE_DEPENDENCY_ROOTS)
        )
    ]
    if blocking:
        raise ReleaseSafetyError(blocking)


def file_inventory(root: Path) -> list[dict[str, object]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    ]


def _python_components(requirements_lock: Path) -> list[dict[str, str]]:
    components: dict[str, dict[str, str]] = {}
    for line in requirements_lock.read_text(encoding="utf-8").splitlines():
        match = REQUIREMENT_RE.match(line.strip())
        if not match:
            continue
        name, version = match.groups()
        normalized = name.replace("_", "-").casefold()
        components[normalized] = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{normalized}@{version}",
        }
    return [components[name] for name in sorted(components)]


def _node_components(package_lock: Path) -> list[dict[str, str]]:
    payload = json.loads(package_lock.read_text(encoding="utf-8"))
    components: dict[str, dict[str, str]] = {}
    for package_path, metadata in payload.get("packages", {}).items():
        if not package_path.startswith("node_modules/") or not isinstance(metadata, dict):
            continue
        name = package_path.removeprefix("node_modules/")
        version = str(metadata.get("version", "")).strip()
        if not name or not version:
            continue
        components[name] = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:npm/{name.replace('@', '%40')}@{version}",
        }
    return [components[name] for name in sorted(components)]


def cyclonedx_sbom(
    *,
    version: str,
    source_commit: str,
    requirements_lock: Path,
    package_lock: Path,
) -> dict[str, object]:
    components = _python_components(requirements_lock) + _node_components(package_lock)
    components.sort(key=lambda item: (str(item["type"]), str(item["name"]), str(item["version"])))
    serial_seed = f"komi-report-v5:{version}:{source_commit}"
    serial = hashlib.sha256(serial_seed.encode("utf-8")).hexdigest()
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial[:8]}-{serial[8:12]}-{serial[12:16]}-{serial[16:20]}-{serial[20:32]}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "KOMI Report V5",
                "version": version,
                "properties": [{"name": "source_commit", "value": source_commit}],
            }
        },
        "components": components,
    }


def write_release_evidence(
    *,
    artifact: Path,
    payload_root: Path,
    output_dir: Path,
    version: str,
    source_commit: str,
    source_state: str,
    target: str,
    build_environment: str,
    signing: str,
    requirements_lock: Path,
    package_lock: Path,
) -> dict[str, object]:
    assert_native_payload_safe(payload_root)
    assert_no_update_runtime_paths(payload_root)
    assert_registration_fail_closed_payload(payload_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    inventory = file_inventory(payload_root)
    inventory_path = output_dir / "FILE_INVENTORY.json"
    inventory_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")

    sbom = cyclonedx_sbom(
        version=version,
        source_commit=source_commit,
        requirements_lock=requirements_lock,
        package_lock=package_lock,
    )
    sbom_path = output_dir / "SBOM.cdx.json"
    sbom_path.write_text(json.dumps(sbom, indent=2) + "\n", encoding="utf-8")

    artifact_sha256 = sha256_file(artifact)
    checksums_path = output_dir / "CHECKSUMS.sha256"
    checksums_path.write_text(f"{artifact_sha256}  {artifact.name}\n", encoding="ascii")

    manifest = {
        "schema_version": 1,
        "product": "KOMI Report V5",
        "version": version,
        "artifact": artifact.name,
        "artifact_identity": f"komi-report-v5-windows-x64-rc-{version}-{source_commit[:12]}",
        "artifact_sha256": artifact_sha256,
        "source_commit": source_commit,
        "source_state": source_state,
        "target": target,
        "build_environment": build_environment,
        "signing": signing,
        "file_count": len(inventory),
        "file_inventory": inventory_path.name,
        "sbom": sbom_path.name,
        "registration_runtime": "fail-closed-no-policy-artefact",
        "update_runtime": "absent-phase-3-deferred",
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "production_go": False,
    }
    (output_dir / "RC_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
