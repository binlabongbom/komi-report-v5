"""Protect page ownership, compatibility imports, and optional startup dependencies."""
import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("first", [
    "ui.setup.wizard",
    "ui.settings.page",
    "ui.reports.page",
    "ui.pages.overview",
    "pages",
    "v5_pages",
])
def test_page_import_order_has_no_cycles_or_eager_optional_backends(first):
    script = f"""
import importlib
import sys
importlib.import_module({first!r})
import pages
import v5_pages
from ui.pages.overview import PageOverview, PageOverviewV2
from ui.pages.imports import PageImport
from ui.settings.legacy import PageSettings
from ui.setup.wizard import SetupWizardV5
from ui.settings.page import PageSettingsV5
from ui.reports.page import PageHistoryV5
from ui.reports.legacy import PageHistory
assert pages.PageOverview is PageOverview is PageOverviewV2
assert pages.PageImport is PageImport
assert pages.PageSettings is PageSettings
assert pages.PageHistory is PageHistory
assert v5_pages.SetupWizardV5 is SetupWizardV5
assert v5_pages.PageSettingsV5 is PageSettingsV5
assert v5_pages.PageHistoryV5 is PageHistoryV5
assert issubclass(PageHistoryV5, PageHistory)
assert 'openpyxl' not in sys.modules
assert 'pyqtgraph' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "PYTHONPATH": str(SOURCE), "PYTHONUTF8": "1"},
        capture_output=True, text=True, encoding="utf8", timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_feature_modules_do_not_import_compatibility_facades():
    for folder in ("setup", "settings", "reports", "pages", "components"):
        for path in (SOURCE / "ui" / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf8"))):
                if isinstance(node, ast.Import):
                    imports = [entry.name for entry in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imports = [node.module]
                else:
                    continue
                assert not {"pages", "v5_pages"}.intersection(imports), path
                if {'steps', 'sections'}.intersection(path.parts):
                    assert not {'ui.setup.wizard', 'ui.settings.fleet', 'ui.settings.page'}.intersection(imports), path


def test_shared_components_do_not_depend_on_feature_pages_or_storage():
    forbidden = {"pages", "v5_pages", "app", "database", "services"}
    features = ("ui.pages", "ui.setup", "ui.settings", "ui.reports", "ui.cloud_reports")
    for path in (SOURCE / "ui" / "components").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf8"))):
            if isinstance(node, ast.Import):
                imports = [entry.name for entry in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports = [node.module or ""]
            else:
                continue
            assert not forbidden.intersection(name.split(".")[0] for name in imports), path
            assert not any(name.startswith(features) for name in imports), path
