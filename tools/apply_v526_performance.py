from pathlib import Path

p = Path('source/app.py')
s = p.read_text(encoding='utf-8')

old = '''        self._quitting = False
        self._background_started = False
        self._registration_collection_ready = False
        self._refresh_all()  # ดึงข้อมูลจาก DB แล้วส่งให้ทุกหน้าแสดงผล
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self._refresh_all)
'''
new = '''        self._quitting = False
        self._background_started = False
        self._registration_collection_ready = False
        # V5.2.6 performance: do not block first paint on database aggregation.
        # The same refresh still runs immediately after the event loop gets a
        # chance to present the workspace, preserving data and UI semantics.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self._refresh_all)
        self._startup_refresh_pending = True
'''
assert old in s, 'startup refresh block not found'
s = s.replace(old, new, 1)

old = '''        self._load_deferred_page(idx)

        # รีเซท active state ของทุกปุ่มก่อน แล้วค่อย highlight ปุ่มที่กด
        for b in self.nav_btns:
            b.set_active(False)
        clicked_btn.set_active(True)
        self.stack.setCurrentIndex(idx)  # สลับให้แสดงหน้าตาม index
        if self._ui_ready:
            self._refresh_visible_page()
'''
new = '''        is_deferred = idx in self._deferred_pages

        # Switch to the existing lightweight host first so Qt can paint the
        # navigation response immediately. Expensive page construction then
        # happens on the next event-loop turn instead of freezing the old tab.
        for b in self.nav_btns:
            b.set_active(False)
        clicked_btn.set_active(True)
        self.stack.setCurrentIndex(idx)
        if is_deferred:
            QTimer.singleShot(0, lambda index=idx: self._finish_deferred_navigation(index))
            return
        if self._ui_ready:
            self._refresh_visible_page()

    def _finish_deferred_navigation(self, index: int) -> None:
        self._load_deferred_page(index)
        if self.stack.currentIndex() == index and self._ui_ready:
            self._refresh_visible_page()
'''
assert old in s, 'navigation block not found'
s = s.replace(old, new, 1)

old = '''    def show_configured_application() -> None:
        # The Wizard has already completed mandatory Online Registration or a
        # valid Offline License before this callback can open the workspace.
        win.start_background_services()
        splash.close()
        if "--background" in sys.argv:
            win.hide()
        else:
            win._show_main_window()
'''
new = '''    def show_configured_application() -> None:
        # V5.2.6 performance: first paint wins. Keep the exact same startup
        # services and data refresh, but let Qt present the workspace before
        # synchronous local refresh and service orchestration compete for the
        # UI thread. Background launches remain hidden as before.
        splash.close()
        if "--background" in sys.argv:
            win.hide()
        else:
            win._show_main_window()

        def finish_startup() -> None:
            if getattr(win, "_startup_refresh_pending", False):
                win._startup_refresh_pending = False
                win._refresh_all()
            win.start_background_services()

        QTimer.singleShot(0, finish_startup)
'''
assert old in s, 'configured startup block not found'
s = s.replace(old, new, 1)

p.write_text(s, encoding='utf-8')

v = Path('source/komi_version.py')
vs = v.read_text(encoding='utf-8')
assert 'APP_VERSION = "5.2.5"' in vs
v.write_text(vs.replace('APP_VERSION = "5.2.5"', 'APP_VERSION = "5.2.6"', 1), encoding='utf-8')

# Add focused source-level regression tests. These deliberately avoid timing
# thresholds; native Windows benchmarking belongs to release/UAT, while these
# tests lock the non-blocking startup/navigation contract.
t = Path('source/tests/test_v526_performance_contract.py')
t.write_text('''from pathlib import Path\n\n\ndef _app_source() -> str:\n    return (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")\n\n\ndef test_startup_paints_before_background_services():\n    source = _app_source()\n    body = source.split("def show_configured_application() -> None:", 1)[1].split("def cancel_first_setup()", 1)[0]\n    assert body.index("win._show_main_window()") < body.index("win.start_background_services()")\n    assert "QTimer.singleShot(0, finish_startup)" in body\n\n\ndef test_initial_database_refresh_is_deferred_until_after_first_paint():\n    source = _app_source()\n    constructor = source.split("class MainWindow(QMainWindow):", 1)[1].split("def _build_ui", 1)[0]\n    assert "self._startup_refresh_pending = True" in constructor\n    assert "self._refresh_all()  # ดึงข้อมูลจาก DB" not in constructor\n\n\ndef test_deferred_navigation_switches_host_before_page_construction():\n    source = _app_source()\n    nav = source.split("def _nav(self, clicked_btn: NavButton):", 1)[1].split("def _schedule_refresh_all", 1)[0]\n    assert nav.index("self.stack.setCurrentIndex(idx)") < nav.index("QTimer.singleShot(0")\n    assert "_finish_deferred_navigation" in nav\n''', encoding='utf-8')
