from __future__ import annotations

import inspect
from types import SimpleNamespace

from PyQt6.QtWidgets import QDialog

import app


class _CompletedRepository:
    def setup_complete(self) -> bool:
        return True


class _EligibleRuntime:
    def usage_eligibility(self) -> tuple[bool, str]:
        return True, "registered"


class _IneligibleRuntime:
    def usage_eligibility(self) -> tuple[bool, str]:
        return False, "offline_license_expired"


class _MutableRuntime:
    def __init__(self, eligible: bool, reason: str) -> None:
        self.eligible = eligible
        self.reason = reason

    def usage_eligibility(self) -> tuple[bool, str]:
        return self.eligible, self.reason


class _PollingGate:
    def __init__(self) -> None:
        self.paused: list[str] = []
        self.resume_count = 0
        self.manual_polls: list[int | None] = []

    def pause(self, reason: str) -> None:
        self.paused.append(reason)

    def resume(self) -> None:
        self.resume_count += 1

    def poll_now(self, slot: int | None = None) -> None:
        self.manual_polls.append(slot)


class _TextTarget:
    def __init__(self) -> None:
        self.text = ""
        self.tooltip = ""

    def setText(self, value: str) -> None:
        self.text = value

    def setToolTip(self, value: str) -> None:
        self.tooltip = value


class _ActionTarget:
    def __init__(self) -> None:
        self.enabled = True

    def setEnabled(self, value: bool) -> None:
        self.enabled = value


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

    def __init__(self, parent, **_kwargs) -> None:
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
    parent = SimpleNamespace(registration=_EligibleRuntime())
    dialog = app._open_v5_setup(
        parent,
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

    parent = SimpleNamespace(registration=_EligibleRuntime())
    assert app._check_v5_setup(parent) is True
    assert calls == []


def test_existing_setup_opens_workspace_when_registration_is_ineligible(monkeypatch):
    monkeypatch.setattr(app, "DeviceConfigRepository", _CompletedRepository)
    monkeypatch.setattr(
        app,
        "get_cfg",
        lambda key, default="": "บริษัท ทดสอบ จำกัด"
        if key == "company_name"
        else default,
    )

    assert app._check_v5_setup(None) is True
    assert app._check_v5_setup(
        SimpleNamespace(registration=_IneligibleRuntime())
    ) is True


def test_deactivated_registration_pauses_collection_and_reactivation_resumes_it():
    runtime = _MutableRuntime(False, "deactivated")
    polling = _PollingGate()
    status = _TextTarget()
    read_action = _ActionTarget()
    window = SimpleNamespace(
        registration=runtime,
        polling=polling,
        status_lbl=status,
        _tray_read_action=read_action,
    )
    window._registration_usage_eligibility = runtime.usage_eligibility
    window._apply_registration_collection_gate = lambda: app.MainWindow._apply_registration_collection_gate(window)

    app.MainWindow._apply_registration_collection_gate(window)

    assert polling.paused == ["deactivated"]
    assert read_action.enabled is False
    assert "ดูประวัติได้" in status.text
    app.MainWindow._request_manual_poll(window, 1)
    assert polling.manual_polls == []

    runtime.eligible, runtime.reason = True, "registered"
    app.MainWindow._apply_registration_collection_gate(window)
    app.MainWindow._request_manual_poll(window, 1)

    assert polling.resume_count == 1
    assert read_action.enabled is True
    assert polling.manual_polls == [1]
