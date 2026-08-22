from __future__ import annotations

import tomllib
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]


def test_qt_runtime_floor_is_aligned_across_dependency_authorities() -> None:
    project = tomllib.loads((SOURCE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = set(project["project"]["dependencies"])
    requirements = set((SOURCE_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines())
    lock = tomllib.loads((SOURCE_ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked_versions = {package["name"]: package["version"] for package in lock["package"]}

    assert "PyQt6~=6.11.0" in dependencies
    assert "PyQt6-Charts~=6.11.0" in dependencies
    assert "PyQt6~=6.11.0" in requirements
    assert "PyQt6-Charts~=6.11.0" in requirements
    assert locked_versions["pyqt6"] == "6.11.0"
    assert locked_versions["pyqt6-charts"] == "6.11.0"
    assert locked_versions["pyqt6-qt6"] == "6.11.1"
    assert locked_versions["pyqt6-charts-qt6"] == "6.11.1"
