from __future__ import annotations

import os
import sys
import pytest

import database
from komi_snmp_profiler.credential_store import SessionCredentialStore
from services import device_config

_qt_app_keepalive = None


@pytest.fixture(autouse=True)
def isolated_ui_language():
    """Each synthetic database starts in Thai; do not leak a prior UI locale."""
    from i18n import set_language
    set_language("th")
    yield
    set_language("th")


@pytest.fixture(scope="session", autouse=True)
def native_offscreen_application():
    """Provide QApplication before any offscreen widget test on every platform."""
    global _qt_app_keepalive
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        from PyQt6.QtWidgets import QApplication

        _qt_app_keepalive = QApplication.instance() or QApplication([])
        if sys.platform == "win32":
            from qt_render_environment import configure_offscreen_fonts

            configure_offscreen_fonts(_qt_app_keepalive)


@pytest.fixture(autouse=True)
def cleanup_qt_widgets(isolated_database):
    """Keep one QApplication alive and close top-level widgets between tests.

    Individual UI tests commonly create ``QApplication([])`` in a local
    variable.  On Windows the wrapper can otherwise be destroyed between
    tests, making the next QApplication reuse stale Qt chart/table state.
    Depend on the database fixture so closeEvent still sees its initialized
    test database; restoring the bootstrap path first can abort inside Qt.
    Native deferred-delete dispatch is intentionally left to Qt: forcing it
    from fixture teardown can abort while accessibility/chart events still
    reference a window that was just closed.
    """
    global _qt_app_keepalive
    yield
    try:
        from PyQt6 import sip
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    _qt_app_keepalive = app
    for widget in list(app.topLevelWidgets()):
        try:
            # Qt-owned popups (calendar menus, tooltips, chart helpers) also
            # appear here. Their owning widget controls their lifetime;
            # deleting them independently can leave native Qt pointers stale.
            if not sip.ispyowned(widget):
                continue
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            continue


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Give every test a complete database without touching the user's DB.

    A few UI/API tests only read configuration and previously depended on the
    order of another test creating the schema first.  Starting every test from
    a fresh schema makes the suite deterministic and keeps clean-install runs
    inside pytest's temporary directory.
    """
    # Tests use synthetic databases and must never advertise them on real LAN.
    monkeypatch.setenv("KOMI_DISCOVERY_DISABLED", "1")
    vault = SessionCredentialStore()
    monkeypatch.setattr(device_config, "platform_credential_store", lambda: vault)
    original_path = database.get_db_path()
    database.set_db_path(tmp_path / "komi-report-v5-test.sqlite3")
    database.init_db()
    try:
        yield
    finally:
        database.set_db_path(original_path)
