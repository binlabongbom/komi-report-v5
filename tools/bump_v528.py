from __future__ import annotations

from pathlib import Path

FILES = (
    "docs/CUSTOMER_GUIDE_V5_2.md",
    "docs/CUSTOMER_INSTALL_GUIDE.md",
    "docs/CUSTOMER_RELEASE_NOTES.md",
    "docs/PILOT_RELEASE_CHECKLIST.md",
    "docs/RELEASE_RUNBOOK.md",
    "docs/RELEASE_SUPPORT_AND_RECOVERY.md",
    "packaging/windows/KOMI_Report_V5.iss",
    "source/app.spec",
    "source/komi_version.py",
    "source/pyproject.toml",
    "source/uv.lock",
    "web/package.json",
    "web/package-lock.json",
)


def main() -> None:
    changed = []
    for filename in FILES:
        path = Path(filename)
        text = path.read_text(encoding="utf-8")
        if "5.2.7" not in text and "V5_2_7" not in text:
            raise RuntimeError(f"{filename}: no V5.2.7 version token found")
        updated = text.replace("5.2.7", "5.2.8").replace("V5_2_7", "V5_2_8")
        if filename == "source/app.spec":
            if 'CFBundleVersion": "50207"' not in updated:
                raise RuntimeError("source/app.spec: expected CFBundleVersion 50207")
            updated = updated.replace('CFBundleVersion": "50207"', 'CFBundleVersion": "50208"')
        if updated == text:
            raise RuntimeError(f"{filename}: version bump produced no change")
        path.write_text(updated, encoding="utf-8")
        changed.append(filename)
    print("Bumped V5.2.8 metadata:")
    for filename in changed:
        print(filename)


if __name__ == "__main__":
    main()
