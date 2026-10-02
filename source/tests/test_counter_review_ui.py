import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QDialog

from services.device_config import DeviceConfigRepository
from ui.counter_review import CounterReviewPanel
from test_counter_review import pending, STAMP, KEY
from test_daily_cache import _reading


def test_subject_and_raw_reviews_use_their_own_store(tmp_path):
    from services.daily_cache import DailyCacheStore
    from test_subject_counter_review import pending as subject_pending
    from test_raw_counter_review import pending as raw_pending
    app = QApplication.instance() or QApplication([])
    subjects = subject_pending(tmp_path)
    _, raw, _ = raw_pending()
    widget = CounterReviewPanel(DeviceConfigRepository(), DailyCacheStore(tmp_path / "empty"),
        subject_cache=subjects, raw_cache=raw, clock=lambda: STAMP.replace(hour=12))
    try:
        assert widget.items.count() == 2
        for expected_store in (subjects, raw):
            widget.open_review()
            dialog = widget._dialog
            assert dialog.cache is expected_store
            dialog.reason.setText("Verified matching counter")
            dialog.verified.setChecked(True)
            dialog.confirm.click()
            assert dialog.result() == QDialog.DialogCode.Accepted
        assert widget.items.count() == 0
    finally:
        widget.close()
        app.processEvents()


def panel(tmp_path):
    app = QApplication.instance() or QApplication([])
    cache = pending(tmp_path)
    widget = CounterReviewPanel(DeviceConfigRepository(), cache, clock=lambda: STAMP.replace(hour=12))
    return app, cache, widget


def test_cancel_does_not_modify_counter_and_requires_reason_and_verification(tmp_path):
    app, cache, widget = panel(tmp_path)
    before = cache.path(0, STAMP.date()).read_bytes()
    try:
        assert widget.items.count() == 1
        widget.open_review()
        dialog = widget._dialog
        assert not dialog.confirm.isEnabled()
        dialog.reason.setText("Checked on printer")
        assert not dialog.confirm.isEnabled()
        dialog.verified.setChecked(True)
        assert dialog.confirm.isEnabled()
        dialog.reject()
        assert cache.path(0, STAMP.date()).read_bytes() == before
        assert widget.items.count() == 1
    finally:
        widget.close()
        app.processEvents()


def test_confirmation_clears_row_and_writes_audit(tmp_path):
    app, cache, widget = panel(tmp_path)
    try:
        widget.open_review()
        dialog = widget._dialog
        dialog.reason.setText("Verified replacement counter module")
        dialog.verified.setChecked(True)
        dialog.confirm.click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert widget.items.count() == 0
        state = cache.load(0, STAMP.date())
        assert not state["counter_review"]
        assert state["counter_resolutions"][0]["baseline"] == 12
        assert state["counter_resolutions"][0]["actor"]
    finally:
        widget.close()
        app.processEvents()


def test_new_reading_while_dialog_open_rejects_stale_confirmation(tmp_path):
    app, cache, widget = panel(tmp_path)
    try:
        widget.open_review()
        dialog = widget._dialog
        later = STAMP.replace(hour=11, minute=30)
        cache.update_reading(0, _reading(14, later), at=later)
        dialog.reason.setText("Checked")
        dialog.verified.setChecked(True)
        dialog.confirm.click()
        assert dialog.error.text()
        assert not dialog.confirm.isEnabled()
        assert KEY in cache.load(0, STAMP.date())["counter_review"]
        dialog.reject()
        widget.open_review()
        assert widget._dialog.preview["baseline"] == 14
        widget._dialog.reject()
    finally:
        widget.close()
        app.processEvents()
