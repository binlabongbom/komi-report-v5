"""Cleanup must preserve runnable reports and optional runtime helpers."""
import os
import subprocess
import sys
from pathlib import Path

from tools.build_windows_rc import remove_dependency_test_suites


def test_packaging_removes_only_reviewed_dependency_suites(tmp_path):
    removed = ('numpy/tests/test_a.py', 'numpy/_core/tests/test_b.py',
               'pyqtgraph/tests/test_plot.py')
    kept = ('numpy/testing/__init__.py', 'numpy/_core/runtime.pyd',
            'PyQt6/Qt6/plugins/platforms/qwindows.dll', 'other/tests/runtime.py')
    for name in removed + kept:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'test')
    assert remove_dependency_test_suites(tmp_path) == {'files': 3, 'bytes': 12}
    assert all(not (tmp_path / name).exists() for name in removed)
    assert all((tmp_path / name).exists() for name in kept)
    assert remove_dependency_test_suites(tmp_path) == {'files': 0, 'bytes': 0}


def test_startup_defers_plotting_but_reports_can_load_it(tmp_path):
    source = Path(__file__).parents[1]
    env = dict(os.environ, PYTHONPATH=str(source), QT_QPA_PLATFORM='offscreen',
               KOMI_APP_HOME=str(tmp_path), KOMI_RUNTIME_CONFIG=str(tmp_path / 'runtime.toml'),
               KOMI_DB_PATH=str(tmp_path / 'qa.db'), KOMI_LOG_DIR=str(tmp_path / 'logs'))
    result = subprocess.run([sys.executable, '-c', '''
import os, sys
sys.path.insert(0, os.getcwd())
import app
assert 'pyqtgraph' not in sys.modules
assert 'numpy' not in sys.modules
import pages
pages._load_pyqtgraph()
assert pages._PQG_OK
assert callable(pages.pg.PlotWidget)
first = pages.pg
pages._load_pyqtgraph()
assert pages.pg is first
'''], cwd=source, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
