"""Promote reviewed synthetic audit captures to the shared guide image pool."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))
from ui.manual_screens import manual_screen_path

PAGES = {
    5: "overview", 6: "devices", 7: "reports", 8: "reports-tab-3",
    9: "reports-tab-4", 10: "settings", 11: "settings-network-bottom",
    12: "settings-tab-3", 13: "manual",
}
WIZARD = {1: "wizard-company", 2: "wizard-devices", 3: "wizard-prices", 4: "wizard-review"}


def main():
    manifest = []
    for language in ("th", "en"):
        for index in range(1, 14):
            if index in WIZARD:
                source = ROOT / f"outputs/ui-ux-audit/wizard-1100x760-{language}/{WIZARD[index]}.png"
            else:
                source = ROOT / f"outputs/ui-ux-audit/pages-1440x900-{language}/{PAGES[index]}.png"
            if not source.is_file():
                raise FileNotFoundError(source)
            target = ROOT / "docs" / manual_screen_path(index, english=language == "en")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            manifest.append({"source": source.relative_to(ROOT).as_posix(),
                             "asset": target.relative_to(ROOT).as_posix(),
                             "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    (ROOT / "docs/customer-guide/assets-v5.2.12-source/ui-manifest.json").write_text(
        json.dumps({"fixture": "synthetic; networking blocked; source UI", "images": manifest}, indent=2), encoding="utf-8")
    print(f"Updated {len(manifest)} guide screenshots")


if __name__ == "__main__":
    main()
