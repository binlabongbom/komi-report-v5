"""Profile source-only navigation on an isolated database copy, without network."""
import argparse
import cProfile
import json
import os
from pathlib import Path
import pstats
import sys
import tempfile
import time
import sqlite3
from contextlib import closing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--synthetic-db', type=Path)
    parser.add_argument('--database-copy', type=Path,
                        help='Open this database read-only and profile a temporary copy; never migrate the original')
    args = parser.parse_args()
    root = args.source_root.resolve()
    sys.path[:0] = [str(root / 'source'), str(root / 'source/tests')]
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.environ['KOMI_DISCOVERY_DISABLED'] = '1'
    def guard(event, values):
        if event in ('socket.connect', 'socket.sendto', 'socket.bind', 'subprocess.Popen', 'os.system'):
            raise PermissionError('Navigation profile forbids external operations')
    sys.addaudithook(guard)
    imported_at = time.perf_counter()
    from PyQt6.QtCore import QObject, QEvent
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtTest import QTest
    from qt_render_environment import configure_offscreen_fonts
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    configure_offscreen_fonts(app)
    import database
    import_setup_seconds = time.perf_counter() - imported_at
    with tempfile.TemporaryDirectory(prefix='komi-navigation-profile-') as folder:
        database.set_db_path(Path(folder) / 'fixture.sqlite3')
        copy_started = time.perf_counter()
        source_path = args.synthetic_db or args.database_copy
        if source_path:
            with closing(sqlite3.connect(source_path.resolve().as_uri() + '?mode=ro', uri=True)) as source:
                if args.synthetic_db:
                    assert source.execute('SELECT slot,serial,host FROM devices ORDER BY slot').fetchall() == [(i,f'FIXTURE-{i}',f'192.0.2.{i+10}') for i in range(3)]
                with closing(sqlite3.connect(database.get_db_path())) as target:
                    source.backup(target)
        copy_seconds = time.perf_counter() - copy_started
        migrate_started = time.perf_counter()
        database.init_db()
        database.set_cfg('web_service_enabled', '0')
        migration_seconds = time.perf_counter() - migrate_started
        main_import_started = time.perf_counter()
        from app import MainWindow
        main_import_seconds = time.perf_counter() - main_import_started
        from ui_consistency import install_button_system
        install_button_system(app)
        MainWindow._fit_to_available_screen = lambda self, **kw: self.resize(1440, 900)
        results = {'source': str(root), 'fixture': str(source_path) if source_path else 'empty synthetic DB', 'scope': 'real fonts/QSS/images; isolated copy; source only; cProfile overhead included; process-cold, OS caches uncontrolled',
            'import_qt_fonts_database_seconds': import_setup_seconds, 'import_main_module_seconds': main_import_seconds,
            'database_copy_seconds': copy_seconds, 'database_migration_seconds': migration_seconds, 'steps': [], 'snapshot_reads': []}
        from services.report_snapshot import SnapshotDataCache
        original_read = SnapshotDataCache.read
        def profiled_read(self, key, loader, cancelled):
            def load():
                started = time.perf_counter()
                value = loader()
                results['snapshot_reads'].append({'component': str(key[1:]),
                    'seconds': time.perf_counter()-started})
                return value
            return original_read(self, key, load, cancelled)
        SnapshotDataCache.read = profiled_read
        paint_times = []
        class PaintProbe(QObject):
            def eventFilter(self, watched, event):
                if event.type() == QEvent.Type.Paint and not paint_times:
                    paint_times.append(time.perf_counter())
                return False
        probe = PaintProbe(app)
        app.installEventFilter(probe)
        def measure(name, action, ready=None):
            profiler = cProfile.Profile()
            started = time.perf_counter()
            paint_times.clear()
            profiler.enable()
            action()
            action_seconds = time.perf_counter() - started
            QTest.qWait(100)
            while ready is not None and not ready():
                if time.perf_counter() - started > 180:
                    raise TimeoutError(name)
                QTest.qWait(10)
            profiler.disable()
            stats = pstats.Stats(profiler)
            rows = [{'file': k[0], 'line': k[1], 'function': k[2], 'calls': v[1], 'own': v[2], 'cumulative': v[3]}
                    for k, v in stats.stats.items()]
            results['steps'].append(dict(name=name, seconds=time.perf_counter()-started, action_seconds=action_seconds,
                first_paint_seconds=paint_times[0]-started if paint_times else None,
                top_cumulative=sorted(rows, key=lambda row: row['cumulative'], reverse=True)[:45],
                top_own=sorted(rows, key=lambda row: row['own'], reverse=True)[:20]))
            window = holder.get('window')
            if window is not None and hasattr(window.pg_history, '_snapshot_cache'):
                results['report_error'] = window.pg_history.report_center.error_label.text()
                results['report_cache_entries'] = len(window.pg_history._snapshot_cache)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
            print(name, results['steps'][-1]['seconds'], flush=True)
        holder = {}
        def create():
            started = time.perf_counter()
            holder['window'] = MainWindow()
            results['main_constructor_seconds'] = time.perf_counter()-started
            holder['window']._startup_refresh_pending = False
            holder['window'].show()
        measure('main', create)
        window = holder['window']
        def reports_ready():
            page = window.pg_history
            if not hasattr(page, '_snapshot_jobs'):
                return False
            center = page.report_center
            return (not page._snapshot_jobs and not page._report_refresh_timer.isActive()
                    and not center._loading and not center._pending_render_tail
                    and not center._render_tail_timer.isActive() and not center._layout_timer.isActive())

        for index, name in ((1, 'devices'), (2, 'reports'), (3, 'settings')):
            window._dirty_pages.add(index)
            measure(name, lambda i=index: window._nav(window.nav_btns[i]), reports_ready if index == 2 else None)
        measure('warm_devices', lambda: window._nav(window.nav_btns[1]))
        measure('warm_reports', lambda: window._nav(window.nav_btns[2]), reports_ready)
        center = window.pg_history.report_center
        for cycle in ('first', 'warm'):
            for index in range(5):
                measure(f'{cycle}_reports_{index}', lambda i=index: center.tabs.setCurrentIndex(i), reports_ready)
        measure('warm_settings', lambda: window._nav(window.nav_btns[3]))
        for index in range(1, 6):
            measure(f'settings_tab_{index}', lambda i=index: window.pg_settings.section_tabs.setCurrentIndex(i))
        window._quitting = True
        window.close()
        window.deleteLater()
        QTest.qWait(50)


if __name__ == '__main__':
    main()
