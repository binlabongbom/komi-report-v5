"""
build.py — Build script พร้อม versioning อัตโนมัติ และ Release Notes

วิธีใช้:
    python build.py

ระบบเวอร์ชัน:
    Patch  — แก้ไขเล็กน้อย (bug fix)      เช่น 4.20 → 4.21
    Minor  — ปรับปรุงฟีเจอร์ระดับกลาง     เช่น 4.20 → 4.30
    Major  — เปลี่ยนแปลงใหญ่ ผู้ใช้ต้องเรียนรู้ใหม่  เช่น 4.x  → 5.0
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR      = Path(__file__).parent
CONFIG_FILE   = BASE_DIR / "config.py"
PYPROJECT_FILE = BASE_DIR / "pyproject.toml"
WEB_PACKAGE_FILE = BASE_DIR.parent / "web" / "package.json"
WEB_LOCK_FILE = BASE_DIR.parent / "web" / "package-lock.json"
SPEC_FILE     = BASE_DIR / "app.spec"
RELEASE_NOTES = BASE_DIR / "RELEASE_NOTES.txt"
DIST_DIR      = BASE_DIR / "dist"

# โฟลเดอร์ระดับบนของ V5 สำหรับ deploy
UPLOAD_PARENT    = BASE_DIR.parent
PARSER_SRC_DIR   = BASE_DIR / "tools"
UPLOAD_BASE_NAME = "KOMI Report V5 Distribution"

# ─────────────────────────────────────────────────────────
# VERSION HELPERS
# ─────────────────────────────────────────────────────────

def read_version() -> str:
    text = PYPROJECT_FILE.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', text, flags=re.MULTILINE)
    if not m:
        raise ValueError("ไม่พบ project.version ใน pyproject.toml")
    return m.group(1)


def write_version(ver: str):
    text = CONFIG_FILE.read_text(encoding="utf-8")
    for key in ("APP_VER", "PACKAGE_VERSION"):
        text = re.sub(
            rf'({key}\s*=\s*)["\'][^"\']+["\']',
            f'\\g<1>"{ver}"',
            text,
        )
    CONFIG_FILE.write_text(text, encoding="utf-8")

    project_text = PYPROJECT_FILE.read_text(encoding="utf-8")
    project_text = re.sub(
        r'(^version\s*=\s*)["\'][^"\']+["\']',
        f'\\g<1>"{ver}"',
        project_text,
        count=1,
        flags=re.MULTILINE,
    )
    PYPROJECT_FILE.write_text(project_text, encoding="utf-8")

    for path in (WEB_PACKAGE_FILE, WEB_LOCK_FILE):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["version"] = ver
        if path == WEB_LOCK_FILE:
            payload["packages"][""]["version"] = ver
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_spec_name(ver: str):
    """อัปเดต name= ใน app.spec ให้ตรงกับเวอร์ชัน"""
    text = SPEC_FILE.read_text(encoding="utf-8")
    text = re.sub(
        r"(name\s*=\s*')[^']*(')",
        f"\\g<1>KOMI Report V{ver}\\2",
        text
    )
    text = re.sub(
        r'(name\s*=\s*")[^"]*(")',
        f'\\g<1>KOMI Report V{ver}\\2',
        text
    )
    major, minor, patch = parse_version(ver)
    bundle_version = str(major * 10_000 + minor * 100 + patch)
    text = re.sub(
        r'("CFBundleDisplayName"\s*:\s*)"[^"]+"',
        f'\\g<1>"KOMI Report V{ver}"',
        text,
    )
    text = re.sub(
        r'("CFBundleShortVersionString"\s*:\s*)"[^"]+"',
        f'\\g<1>"{ver}"',
        text,
    )
    text = re.sub(
        r'("CFBundleVersion"\s*:\s*)"[^"]+"',
        f'\\g<1>"{bundle_version}"',
        text,
    )
    SPEC_FILE.write_text(text, encoding="utf-8")


def parse_version(ver: str) -> tuple[int, int, int]:
    """Parse canonical semantic version ``major.minor.patch``."""
    parts = ver.strip().split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"เวอร์ชันต้องเป็น SemVer major.minor.patch: {ver}")
    return tuple(int(part) for part in parts)


def format_version(major: int, minor: int, patch: int) -> str:
    return f"{major}.{minor}.{patch}"


def bump(ver: str, kind: str) -> str:
    """คำนวณเวอร์ชันถัดไป"""
    major, minor, patch = parse_version(ver)
    if kind == "patch":
        patch += 1
    elif kind == "minor":
        minor += 1
        patch = 0
    else:  # major
        major, minor, patch = major + 1, 0, 0
    return format_version(major, minor, patch)


# ─────────────────────────────────────────────────────────
# RELEASE NOTES
# ─────────────────────────────────────────────────────────

def prepend_release_notes(old: str, new: str, kind: str, changes: list[str]):
    """เพิ่มบันทึกเวอร์ชันใหม่ไว้ด้านบนของไฟล์"""
    now   = datetime.now().strftime("%Y-%m-%d %H:%M")
    label = {
        "patch": "Patch Fix",
        "minor": "Minor Update",
        "major": "Major Release"
    }[kind]
    sep   = "=" * 60
    body  = "\n".join(f"  • {c}" for c in changes)
    entry = (
        f"{sep}\n"
        f"Version {new}  [{label}]  —  {now}\n"
        f"{sep}\n"
        f"อัปเกรด: v{old} → v{new}\n\n"
        f"{body}\n\n"
    )
    old_content = RELEASE_NOTES.read_text(encoding="utf-8") if RELEASE_NOTES.exists() else ""
    RELEASE_NOTES.write_text(entry + old_content, encoding="utf-8")


# ─────────────────────────────────────────────────────────
# DEPLOY (ก๊อปปี้ไฟล์ไป Komi Report for Upload + rename ใส่เวอร์ชัน)
# ─────────────────────────────────────────────────────────

def _force_rmtree(path: Path):
    """rmtree ที่เคลียร์ read-only ก่อนลบ (กัน OneDrive/Windows read-only attribute)"""

    def _onexc(func, p, exc):
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            func(p)
        except Exception:
            raise

    shutil.rmtree(path, onexc=_onexc)


def find_upload_dir() -> Path | None:
    """หา folder Komi Report for Upload ที่มีอยู่ (รองรับชื่อมีเวอร์ชันต่อท้าย)"""
    candidates = [
        p for p in UPLOAD_PARENT.glob(f"{UPLOAD_BASE_NAME}*") if p.is_dir()
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def deploy_to_upload(new_ver: str) -> Path | None:
    """ก๊อปปี้ EXE / Release Notes / Paser ไป Komi Report for Upload และ rename ให้มีเวอร์ชันต่อท้าย"""
    exe_src = DIST_DIR / f"KOMI Report V{new_ver}.exe"
    if not exe_src.exists():
        print(f"⚠ ไม่พบ EXE ที่ {exe_src} — ข้าม deploy")
        return None

    upload_dir = find_upload_dir()
    if upload_dir is None:
        upload_dir = UPLOAD_PARENT / UPLOAD_BASE_NAME
        upload_dir.mkdir(parents=True, exist_ok=True)
        print(f"→ สร้างโฟลเดอร์ใหม่: {upload_dir.name}")

    print(f"\n→ Deploy ไปยัง: {upload_dir.name}")

    # ลบ EXE เก่าใน upload folder (กันชนกัน/รก)
    for old_exe in upload_dir.glob("KOMI Report V*.exe"):
        try:
            old_exe.unlink()
            print(f"   - ลบ EXE เก่า  : {old_exe.name}")
        except Exception as e:
            print(f"   ⚠ ลบ {old_exe.name} ไม่สำเร็จ: {e}")

    # คัดลอก EXE
    shutil.copy2(exe_src, upload_dir / exe_src.name)
    print(f"   ✓ คัดลอก EXE   : {exe_src.name}")

    # คัดลอก Release Notes
    if RELEASE_NOTES.exists():
        shutil.copy2(RELEASE_NOTES, upload_dir / RELEASE_NOTES.name)
        print(f"   ✓ คัดลอก Notes : {RELEASE_NOTES.name}")
    else:
        print(f"   ⚠ ไม่พบ {RELEASE_NOTES.name}")

    # คัดลอก Paser folder (ลบของเดิมก่อน)
    if PARSER_SRC_DIR.exists():
        dst_parser = upload_dir / PARSER_SRC_DIR.name
        if dst_parser.exists():
            _force_rmtree(dst_parser)
        shutil.copytree(PARSER_SRC_DIR, dst_parser)
        n_files = sum(1 for _ in dst_parser.iterdir())
        print(f"   ✓ คัดลอก Paser : {PARSER_SRC_DIR.name}/ ({n_files} ไฟล์)")
    else:
        print(f"   ⚠ ไม่พบ Paser source ที่ {PARSER_SRC_DIR}")

    # rename folder ให้มี version ต่อท้าย
    target_name = f"{UPLOAD_BASE_NAME} V{new_ver}"
    if upload_dir.name != target_name:
        new_path = UPLOAD_PARENT / target_name
        if new_path.exists():
            print(f"   ⚠ มี {target_name} อยู่แล้ว — ลบของเดิมก่อน")
            _force_rmtree(new_path)
        upload_dir.rename(new_path)
        print(f"   ✓ เปลี่ยนชื่อ   : {upload_dir.name} → {target_name}")
        upload_dir = new_path

    return upload_dir


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("   KOMI Report — Build & Release Script")
    print("=" * 55)

    cur = read_version()
    print(f"\nเวอร์ชันปัจจุบัน : v{cur}")

    ver_patch = bump(cur, "patch")
    ver_minor = bump(cur, "minor")
    ver_major = bump(cur, "major")

    print("\nประเภทการเปลี่ยนแปลง:")
    print(f"  1) Patch  — แก้ไขเล็กน้อย (bug fix)         v{cur} → v{ver_patch}")
    print(f"  2) Minor  — เพิ่ม/ปรับฟีเจอร์ระดับกลาง      v{cur} → v{ver_minor}")
    print(f"  3) Major  — เปลี่ยนใหญ่ ต้องเรียนรู้ใหม่    v{cur} → v{ver_major}")
    print(f"  4) Build  — สร้าง EXE ใหม่โดยไม่เปลี่ยนเวอร์ชัน  v{cur}")
    print("  0) ยกเลิก")

    choice = input("\nเลือก (0/1/2/3/4): ").strip()
    kind_map = {"1": "patch", "2": "minor", "3": "major", "4": "build"}
    if choice not in kind_map:
        print("ยกเลิก build")
        return

    kind = kind_map[choice]

    if kind == "build":
        new_ver = cur
        changes = []
        print(f"\nBuild EXE เวอร์ชันเดิม: v{new_ver} (ไม่เปลี่ยน Release Notes)")
    else:
        new_ver = {"patch": ver_patch, "minor": ver_minor, "major": ver_major}[kind]
        print(f"\nเวอร์ชันใหม่: v{new_ver}")

        print("\nระบุรายการแก้ไข/เพิ่มเติม (กด Enter บรรทัดว่างเมื่อเสร็จ):")
        changes = []
        while True:
            line = input("  • ").strip()
            if not line:
                break
            changes.append(line)

        if not changes:
            changes = ["(ไม่ได้ระบุรายละเอียด)"]

    # ── อัปเดตไฟล์ก่อน build ───────────────────────────
    if kind != "build":
        print(f"\n→ อัปเดต config.py   v{cur} → v{new_ver}")
        write_version(new_ver)

        print(f"→ อัปเดต app.spec   name = 'KOMI Report V{new_ver}'")
        update_spec_name(new_ver)
    else:
        print(f"\n→ ใช้ config.py เดิม v{cur} (ไม่แก้ไข)")
        print(f"→ ตรวจสอบ app.spec   name = 'KOMI Report V{new_ver}'")
        update_spec_name(new_ver)

    print("→ กำลัง build EXE ...\n")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(SPEC_FILE)],
        cwd=BASE_DIR
    )

    if result.returncode != 0:
        print("\n✗ Build ล้มเหลว — ย้อนกลับเวอร์ชัน ...")
        if kind != "build":
            write_version(cur)
            update_spec_name(cur)
        sys.exit(1)

    # ── บันทึก release notes หลัง build สำเร็จ ─────────
    if kind != "build":
        prepend_release_notes(cur, new_ver, kind, changes)

    exe_path = DIST_DIR / f"KOMI Report V{new_ver}.exe"

    # ── deploy ไป Komi Report for Upload + rename ─────
    deployed = deploy_to_upload(new_ver)

    print(f"\n{'='*55}")
    print("  Build สำเร็จ!")
    print(f"  EXE    : {exe_path}")
    print(f"  Notes  : {RELEASE_NOTES}")
    if deployed:
        print(f"  Upload : {deployed}")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
