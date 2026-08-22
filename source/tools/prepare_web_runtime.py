from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

try:
    from .init_web_access import ensure_web_access
except ImportError:  # Direct script execution from source/tools.
    from init_web_access import ensure_web_access


EXCLUDED_DIRS = {".next", "node_modules", "__pycache__"}
SOURCE_MANIFEST = ".komi-web-source-files.json"
DEPENDENCY_STAMP = ".komi-web-dependencies.sha256"
BUILD_STAMP = ".komi-web-build.sha256"


def _is_authored_file(path: Path, web_source: Path) -> bool:
    relative = path.relative_to(web_source)
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return False
    if path.name.startswith(".env") and path.name.endswith(".local"):
        return False
    return not path.name.endswith(".tsbuildinfo")


def authored_files(web_source: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            (path for path in web_source.rglob("*") if path.is_file() and _is_authored_file(path, web_source)),
            key=lambda path: path.relative_to(web_source).as_posix(),
        )
    )


def source_hash(web_source: Path) -> str:
    digest = hashlib.sha256()
    for path in authored_files(web_source):
        relative = path.relative_to(web_source).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def sync_web_source(web_source: Path, web_runtime: Path) -> tuple[str, ...]:
    """Mirror authored Web files while preserving local builds, dependencies and secrets."""

    web_source = web_source.resolve()
    web_runtime.mkdir(parents=True, exist_ok=True)
    manifest_path = web_runtime / SOURCE_MANIFEST
    previous: set[str] = set()
    if manifest_path.is_file():
        try:
            previous = set(json.loads(manifest_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError):
            previous = set()

    current: list[str] = []
    for source_path in authored_files(web_source):
        relative = source_path.relative_to(web_source).as_posix()
        destination = web_runtime / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        current.append(relative)

    for relative in previous.difference(current):
        stale = web_runtime / relative
        if stale.is_file():
            stale.unlink()

    manifest_path.write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return tuple(current)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _npm_command() -> str:
    command = shutil.which("npm.cmd") or shutil.which("npm")
    if command is None:
        raise RuntimeError("ไม่พบ Node.js/npm กรุณาติดตั้ง Node.js LTS ก่อน")
    return command


def prepare(web_source: Path, web_runtime: Path, legacy_env: Path | None = None) -> None:
    web_source = web_source.resolve()
    web_runtime = web_runtime.expanduser().resolve()
    if not (web_source / "package-lock.json").is_file():
        raise FileNotFoundError(f"ไม่พบ Web source กลาง: {web_source}")

    sync_web_source(web_source, web_runtime)
    values = ensure_web_access(web_runtime / ".env.local", migrate_from=legacy_env)
    print(f"Web Login: {values['KOMI_WEB_USER']}")
    print("Access Code: จัดการจาก Desktop Settings (ไม่แสดงรหัสใน Log)")

    npm = _npm_command()
    dependency_hash = _sha256(web_source / "package-lock.json")
    dependency_stamp = web_runtime / DEPENDENCY_STAMP
    installed_hash = dependency_stamp.read_text(encoding="utf-8").strip() if dependency_stamp.is_file() else ""
    if not (web_runtime / "node_modules").is_dir() or installed_hash != dependency_hash:
        print("กำลังติดตั้ง Web dependencies ใน runtime ของเครื่องนี้...")
        subprocess.run([npm, "ci"], cwd=web_runtime, check=True)
        dependency_stamp.write_text(dependency_hash + "\n", encoding="utf-8")

    current_source_hash = source_hash(web_source)
    build_stamp = web_runtime / BUILD_STAMP
    built_hash = build_stamp.read_text(encoding="utf-8").strip() if build_stamp.is_file() else ""
    if not (web_runtime / ".next" / "BUILD_ID").is_file() or built_hash != current_source_hash:
        print("กำลัง Build หน้าเว็บจาก source กลาง...")
        subprocess.run([npm, "run", "build"], cwd=web_runtime, check=True)
        build_stamp.write_text(current_source_hash + "\n", encoding="utf-8")

    print(f"Web runtime พร้อม: {web_runtime}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a machine-local KOMI Web runtime.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--legacy-env", type=Path)
    args = parser.parse_args()
    prepare(args.source, args.runtime, args.legacy_env)


if __name__ == "__main__":
    main()
