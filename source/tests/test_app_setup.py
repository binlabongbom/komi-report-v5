from __future__ import annotations

import inspect

from PyQt6.QtWidgets import QDialog

import app


class _CompletedRepository:
    def setup_complete(self) -> bool:
        return True


class _Signal:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:
        self.callback = callback

    def emit(self, value: int) -> None:
        assert self.callback is not None
        self.callback(value)


class _AcceptedWizard:
    constructed_parent = object()

    def __init__(self, parent) -> None:
        type(self).constructed_parent = parent
        self.finished = _Signal()
        self.opened = False
        self.window_modality = None

    def setWindowModality(self, modality) -> None:
        self.window_modality = modality

    def open(self) -> None:
        self.opened = True
        self.finished.emit(int(QDialog.DialogCode.Accepted))

    def raise_(self) -> None:
        pass

    def activateWindow(self) -> None:
        pass

def test_first_setup_registers_default_background_autostart(monkeypatch):
    repository = _CompletedRepository()
    calls: list[tuple[bool, bool]] = []
    monkeypatch.setattr(app, "DeviceConfigRepository", lambda: repository)
    monkeypatch.setattr(app, "SetupWizardV5", _AcceptedWizard)
    monkeypatch.setattr(app, "configure_autostart", lambda enabled, *, apply: calls.append((enabled, apply)))
    shortcut_calls = []
    saved_cfg: list[tuple[str, str]] = []

    class ShortcutResult:
        created_paths = ()

    monkeypatch.setattr(app, "create_desktop_shortcuts", lambda: shortcut_calls.append(True) or ShortcutResult())
    monkeypatch.setattr(app, "get_cfg", lambda key, default="": "บริษัท ทดสอบ จำกัด" if key == "company_name" else default)
    monkeypatch.setattr(app, "set_cfg", lambda key, value: saved_cfg.append((key, value)))

    completed = []
    cancelled = []
    dialog = app._open_v5_setup(
        None,
        on_complete=lambda: completed.append(True),
        on_cancel=lambda: cancelled.append(True),
    )

    assert dialog.opened is True
    assert _AcceptedWizard.constructed_parent is None
    assert dialog.window_modality == app.Qt.WindowModality.ApplicationModal
    assert completed == [True]
    assert cancelled == []
    assert calls == [(True, True)]
    assert shortcut_calls == [True]
    assert ("web_service_enabled", "1") in saved_cfg


def test_first_setup_uses_async_open_without_nested_dialog_exec():
    source = inspect.getsource(app._open_v5_setup)
    assert "dialog.open()" in source
    assert ".exec(" not in source


def test_existing_setup_does_not_rewrite_autostart(monkeypatch):
    class ExistingRepository:
        @staticmethod
        def setup_complete() -> bool:
            return True

    calls: list[tuple[bool, bool]] = []
    monkeypatch.setattr(app, "DeviceConfigRepository", ExistingRepository)
    monkeypatch.setattr(app, "configure_autostart", lambda enabled, *, apply: calls.append((enabled, apply)))
    monkeypatch.setattr(app, "get_cfg", lambda key, default="": "บริษัท ทดสอบ จำกัด" if key == "company_name" else default)

    assert app._check_v5_setup(None) is True
    assert calls == []
