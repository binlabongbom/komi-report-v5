from __future__ import annotations

import pytest

import database
from komi_snmp_profiler.credential_store import SessionCredentialStore
from services import device_config

_qt_app_keepalive = None


@pytest.fixture(autouse=True)
def cleanup_qt_widgets():
    """Keep one QApplication alive and deliver deferred deletes between tests.

    Individual UI tests commonly create ``QApplication([])`` in a local
    variable.  On Windows the wrapper can otherwise be destroyed between
    tests, making the next QApplication reuse stale Qt chart/table state.
    """
    global _qt_app_keepalive
    yield
    try:
        from PyQt6.QtCore import QCoreApplication, QEvent
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    _qt_app_keepalive = app
    for widget in list(app.topLevelWidgets()):
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            continue
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Give every test a complete database without touching the user's DB.

    A few UI/API tests only read configuration and previously depended on the
    order of another test creating the schema first.  Starting every test from
    a fresh schema makes the suite deterministic and keeps clean-install runs
    inside pytest's temporary directory.
    """
    vault = SessionCredentialStore()
    monkeypatch.setattr(device_config, "platform_credential_store", lambda: vault)
    original_path = database.get_db_path()
    database.set_db_path(tmp_path / "komi-report-v5-test.sqlite3")
    database.init_db()
    try:
        yield
    finally:
        database.set_db_path(original_path)
