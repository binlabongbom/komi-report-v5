"""Render and inventory the local Qt UI with synthetic data and blocked network.

Audit evidence only: never launches background services or changes production data.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import date
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'source'), str(ROOT/'source/tests')]
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['KOMI_DISCOVERY_DISABLED'] = '1'
parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=('pages', 'dialogs', 'wizard', 'controls', 'evidence'), default='pages')
parser.add_argument('--width', type=int, default=1024)
parser.add_argument('--height', type=int, default=640)
parser.add_argument('--language', default='th')
parser.add_argument('--only', default='')
args = parser.parse_args()
selection_suffix='-'+re.sub(r'[^a-zA-Z0-9_-]+','-',args.only) if args.only else ''
out = ROOT/'outputs/ui-ux-audit'/(f'{args.mode}-{args.width}x{args.height}-{args.language}' + selection_suffix)
out.mkdir(parents=True, exist_ok=True)
network_attempts = []
def no_network(event, values):
    if event in ('socket.connect', 'socket.sendto', 'socket.bind'):
        network_attempts.append(event)
        raise PermissionError('UI audit blocks network operations')
sys.addaudithook(no_network)

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtWidgets import (QApplication, QWidget, QLabel, QPushButton, QAbstractButton,
    QScrollArea, QTabWidget, QLineEdit, QComboBox, QDateEdit, QTableWidget)
from PyQt6.QtTest import QTest
from qt_render_environment import configure_offscreen_fonts
import database
import pages
import v5_pages
from app import MainWindow
from config import build_qss
from ui_consistency import install_button_system
from i18n import apply_language, set_language
from services.device_config import DeviceConfigRepository, DeviceConfig
from services import web_service
from render_ui_matrix_v5 import _overview_summary, _seed_billing_audit
from excel_export_fixture import report_for

app = QApplication([])
configure_offscreen_fonts(app)
install_button_system(app)
temp = tempfile.TemporaryDirectory(prefix='komi-ux-audit-')
database.set_db_path(Path(temp.name)/'synthetic.db')
database.init_db()
database.set_cfg('ui_language', args.language)
set_language(args.language)
database.set_cfg('company_name', 'บริษัท ตัวอย่างสำหรับตรวจหน้าจอ จำกัด')
database.set_cfg('db_path', str(database.get_db_path()))
database.set_cfg('billing_day', '1')
devices = [DeviceConfig(i, f'เครื่องพิมพ์ฝ่าย {i+1}', f'192.0.2.{i+10}', serial=f'QA-{i}',
    model='bizhub C450i', connection_status='online', last_total=12000) for i in range(3)]
DeviceConfigRepository().replace_all(devices)
_seed_billing_audit()
web_service._port_open = lambda _port: False
web_service._lan_ip = lambda: '127.0.0.1'
v5_pages.configure_autostart = lambda *_a, **_kw: Path(temp.name)/'autostart'
pages.build_overview_summary = lambda *_a, **_kw: _overview_summary(3)
v5_pages.latest_counters = lambda slot: {'counter.total.total': 12000, 'counter.print.black_total': 4000}
results, errors = [], []

def settle(ms=50):
    app.processEvents()
    QTest.qWait(ms)
    app.processEvents()

def capture(name, root):
    settle()
    if isinstance(root, MainWindow) and (root.width() > args.width or root.height() > args.height):
        errors.append({'screen': name, 'error': f'Window expanded to {root.width()}x{root.height()} from {args.width}x{args.height}'})
    slug = re.sub(r'[^a-zA-Z0-9_-]+', '-', name)
    assert root.grab().save(str(out/f'{slug}.png'))
    widgets = []
    for w in root.findChildren(QWidget):
        if not w.isVisibleTo(root) or w.visibleRegion().isEmpty():
            continue
        if not isinstance(w, (QLabel,QAbstractButton,QLineEdit,QComboBox,QTableWidget,QDateEdit)):
            continue
        text = w.text() if isinstance(w, (QLabel,QAbstractButton,QLineEdit)) else ''
        record = {'type':type(w).__name__, 'name':w.objectName(), 'text':text[:500],
            'size':[w.width(),w.height()], 'hint':[w.sizeHint().width(),w.sizeHint().height()],
            'font_pt':w.font().pointSizeF(), 'font_px':w.font().pixelSize(),
            'enabled':w.isEnabled(), 'focus':w.focusPolicy().value,
            'accessible':w.accessibleName(), 'tooltip':w.toolTip()[:300],
            'qss':w.styleSheet()[:700]}
        if isinstance(w,QLabel):
            record['wrap'] = w.wordWrap()
        if isinstance(w,QComboBox):
            record['items'] = [w.itemText(i) for i in range(w.count())]
        if isinstance(w,QDateEdit):
            record['date_format'] = w.displayFormat()
        if isinstance(w,QTableWidget):
            record['rows'] = w.rowCount()
            record['headers'] = [w.horizontalHeaderItem(i).text() if w.horizontalHeaderItem(i) else '' for i in range(w.columnCount())]
            record['column_widths'] = [w.columnWidth(i) for i in range(w.columnCount())]
        widgets.append(record)
    result = {'screen':slug,'actual_size':[root.width(),root.height()], 'widgets':widgets,
              'tabs':[[t.tabText(i) for i in range(t.count())] for t in root.findChildren(QTabWidget)],
              'scrolls': [{'width':s.viewport().width(),'height':s.viewport().height(),
                          'horizontal':s.horizontalScrollBar().maximum(),'vertical':s.verticalScrollBar().maximum()}
                         for s in root.findChildren(QScrollArea) if s.isVisibleTo(root)]}
    results.append(result)
    save()
    print(slug, flush=True)

def save():
    (out/'inventory.json').write_text(json.dumps({'mode':args.mode,'language':args.language,
        'requested_size':[args.width,args.height],'scale_factor':os.environ.get('QT_SCALE_FACTOR','1'),
        'screens':results,'errors':errors,
        'network_attempts':network_attempts,'synthetic':True,
        'platform':'Qt offscreen; configured Windows fonts',
        'window_fit_override':args.mode=='pages',
        'background_services_started':False}, ensure_ascii=False, indent=2),encoding='utf-8')

def guarded(name, action):
    try:
        action()
    except Exception as exc:
        errors.append({'screen':name,'error':repr(exc)})
        save()
        print('ERROR',name,repr(exc),flush=True)

def scroll_bottoms(prefix, content, root):
    for i,s in enumerate(content.findChildren(QScrollArea)):
        if s.isVisibleTo(root) and s.verticalScrollBar().maximum() > 50:
            old=s.verticalScrollBar().value()
            s.verticalScrollBar().setValue(s.verticalScrollBar().maximum())
            capture(f'{prefix}-bottom-{i}',root)
            s.verticalScrollBar().setValue(old)

def walk_tabs(prefix, content, root, seen=()):
    visible=[t for t in content.findChildren(QTabWidget) if t not in seen and t.isVisibleTo(root)]
    if not visible:
        scroll_bottoms(prefix,content,root)
        return
    tab=visible[0]
    original=tab.currentIndex()
    for i in range(tab.count()):
        tab.setCurrentIndex(i)
        settle()
        capture(f'{prefix}-tab-{i}',root)
        walk_tabs(f'{prefix}-tab-{i}',content,root,(*seen,tab))
    tab.setCurrentIndex(original)

def main_pages():
    # Only bypass offscreen's artificial 800x800 display clamp. Keep layout minima.
    def viewport(self, *, initial=False):
        self.setMinimumSize(0,0)
        if initial:
            self.resize(args.width,args.height)
    MainWindow._fit_to_available_screen=viewport
    window=MainWindow()
    window.resize(args.width,args.height)
    window.show()
    window._startup_refresh_pending=False
    window._refresh_timer.stop()
    report=report_for(users=90,days=2)
    for index,name in enumerate(('overview','devices','reports','settings','manual')):
        if args.only and name not in args.only.split(','):
            continue
        def visit(index=index,name=name):
            window._nav(window.nav_btns[index])
            deadline=monotonic()+10
            while type(window._page_widgets[index]).__name__=='_DeferredPage' and monotonic()<deadline:
                settle()
            content=window._page_widgets[index]
            if name=='overview': content.refresh()
            if name=='reports':
                content.shutdown_report_loading()
                cloud=content.report_center
                cloud.set_periods((report.period,),report.period)
                cloud.set_data(records=report.selected_records,daily_records=report.selected_daily_records,
                    usage_daily_records=report.usage_daily_records,monthly_records=report.selected_records,
                    subjects=report.subjects,devices=report.devices,period=report.period,
                    last_sync_at='2026-07-02T17:00:00+07:00',raw_counter_records=report.raw_counter_records)
            apply_language(content)
            capture(name,window)
            walk_tabs(name,content,window)
            if name=='reports' and args.only:
                cloud.tabs.setCurrentIndex(0)
                cloud.set_loading(True)
                capture('reports-loading',window)
                cloud.show_error('ตัวอย่าง: อ่านรายงานไม่สำเร็จ')
                capture('reports-error',window)
                cloud.set_data(records=(),daily_records=(),subjects=(),devices=(),period=report.period,last_sync_at=None)
                capture('reports-empty',window)
            if name=='manual':
                for i in range(5):
                    content._scroll_to_manual_section(i)
                    capture(f'manual-section-{i}',window)
            if name=='settings':
                content.show_audit()
                capture('billing-audit',window)
                content.show_main()
                content.show_schedule()
                capture('settings-schedule-expanded',window)
                scroll_bottoms('settings-schedule-expanded',content,window)
                content.show_advanced()
                content.fleet_content._set_active_editor('web',force=True)
                content.advanced_page.ensureWidgetVisible(content.fleet_content.web_service_enabled,0,10)
                capture('settings-network',window)
                content.fleet_content.web_advanced_toggle.setChecked(True)
                capture('settings-network-port',window)
                content.advanced_page.ensureWidgetVisible(content.fleet_content.web_save_button,0,10)
                capture('settings-network-bottom',window)
                content.fleet_content._show_registration_privacy()
                notice=content.fleet_content._registration_privacy_dialog
                capture('registration-notice',notice)
                notice.reject()
        guarded(name,visit)
    window._quitting=True
    window.close()
    settle()

def show_dialog(name, factory):
    dialog=factory()
    dialog.show()
    apply_language(dialog)
    capture(name,dialog)
    dialog.resize(min(dialog.width(),args.width),min(dialog.height(),args.height))
    capture(name+'-compact',dialog)
    if hasattr(dialog,'finish') and type(dialog).__name__=='ExportProgressDialog': dialog.finish()
    else: dialog.close()
    if getattr(dialog,'pool',None) is not None: dialog.pool.shutdown(wait=True,cancel_futures=True)
    settle()

def main_dialogs():
    from types import SimpleNamespace
    from ui.common_dialogs import AllCountersDialog, PinnedCountersDialog
    from ui.parser_mapping_inspector import ParserMappingInspector
    from ui.report_export import ExportProgressDialog
    from ui.slot_baseline_review import SlotBaselineDialog
    from ui.shared_settings_history import SharedSettingsHistoryDialog
    from ui.shared_settings_confirmation import SharedSettingsConfirmation
    from ui.web_evidence_report import WebEvidenceDialog
    from ui.billing_repricing_batch import BatchRepricingDialog
    from ui.billing_manual_review import BillingManualReviewDialog
    from ui.billing_repricing import BillingRepricingDialog
    from ui.billing_web_amendment import BillingWebAmendmentDialog
    from ui.report_detail_amendment import ReportDetailAmendmentDialog
    from ui.counter_review import CounterReviewDialog
    from ui.archive_settings import ArchiveSettingsPanel
    parent=QWidget()
    parent.setStyleSheet(build_qss())
    parent.resize(args.width,args.height)
    parent.show()
    with database._open(commit=False) as conn:
        ledger_id=conn.execute('SELECT id FROM billing_ledger ORDER BY id DESC LIMIT 1').fetchone()[0]
    preview={'device_identity':{'name':'เครื่องพิมพ์แผนกบัญชี','serial':'QA-001'},'before':20000,
        'baseline':5000,'observed_at':'2026-07-02T12:00:00+07:00','preserved_delta':80,'revision':1}
    registry={
        'export-period':lambda:v5_pages.ReportExportPeriodDialog(date(2026,7,1),date(2026,7,31),parent=parent),
        'export-progress':lambda:ExportProgressDialog(parent),
        'web-access':lambda:v5_pages.WebAccessCodeDialog(parent),
        'legacy-import':lambda:v5_pages.LegacyHistoryImportDialog(parent),
        'all-counters':lambda:AllCountersDialog('Counter ทั้งหมด',{'counter.total.total':12000},parent),
        'pinned-counters':lambda:PinnedCountersDialog(DeviceConfigRepository(),parent),
        'parser-mapping':lambda:ParserMappingInspector(parent),
        'slot-baseline':lambda:SlotBaselineDialog(devices,parent),
        'shared-history':lambda:SharedSettingsHistoryDialog(parent),
        'shared-confirmation':lambda:SharedSettingsConfirmation(SimpleNamespace(changes={'billing_day':('1','25')},remote_head=None),parent),
        'web-evidence':lambda:WebEvidenceDialog(devices,parent,today=date(2026,7,20)),
        'batch-repricing':lambda:BatchRepricingDialog(parent,today=date(2026,7,20)),
        'manual-billing':lambda:BillingManualReviewDialog(ledger_id,parent),
        'repricing':lambda:BillingRepricingDialog(ledger_id,parent),
        'web-amendment':lambda:BillingWebAmendmentDialog((0,'fixture',date(2026,7,1),date(2026,7,2),'counter.total.total'),parent),
        'detail-amendment':lambda:ReportDetailAmendmentDialog((0,'fixture',date(2026,7,1),date(2026,7,2),SimpleNamespace(field='counter.total.total',subject_id='')),parent),
        'counter-review':lambda:CounterReviewDialog(None,0,date(2026,7,2),'counter.total.total',preview,parent),
        'archive':lambda:ArchiveSettingsPanel(parent),
    }
    from services.billing_ledger import list_audit_rows
    registry['billing-detail']=lambda:v5_pages.BillingAuditDetailDialog(list_audit_rows(1)[0],parent)
    for name,factory in registry.items():
        if not args.only or name in args.only.split(','):
            guarded(name,lambda name=name,factory=factory:show_dialog(name,factory))
    parent.close()

def main_wizard():
    wizard=v5_pages.SetupWizardV5(edit_mode=True,legacy_source_paths=[],runtime_config_path=str(Path(temp.name)/'runtime.toml'))
    wizard.resize(args.width,args.height)
    wizard.show()
    capture('wizard-company',wizard)
    wizard._show_secondary_manual_options()
    capture('wizard-secondary-manual',wizard)
    wizard._secondary_discovery_finished([], 'Synthetic discovery: no response')
    capture('wizard-secondary-not-found',wizard)
    wizard._enter_device_step()
    capture('wizard-devices',wizard)
    scroll_bottoms('wizard-devices',wizard,wizard)
    for name,action in (
        ('wizard-credentials',lambda:wizard._open_credentials('192.0.2.10')),
        ('wizard-advanced-scan',wizard._advanced_scan),
        ('wizard-manual-setup',wizard._manual_setup),
        ('wizard-printer-names',wizard._name_selected_devices),
        ('wizard-privacy',wizard._show_privacy_notice),
    ):
        action()
        settle()
        dialogs=[w for w in app.topLevelWidgets() if w.isVisible() and w is not wizard]
        for d in dialogs:
            capture(name,d)
            d.reject()
    wizard._enter_price_step()
    capture('wizard-prices',wizard)
    scroll_bottoms('wizard-prices',wizard,wizard)
    wizard._show_review_step()
    capture('wizard-review',wizard)
    scroll_bottoms('wizard-review',wizard,wizard)
    wizard.close()


def main_controls():
    """Measure rendered state differences; never clicks a business operation."""
    from PyQt6.QtWidgets import QVBoxLayout
    from widgets import btn
    from ui.common_dialogs import PinnedCountersDialog
    from i18n import translate_text
    parent=QWidget()
    parent.setStyleSheet(build_qss())
    layout=QVBoxLayout(parent)
    focus_sink=QLineEdit('Focus target')
    layout.addWidget(focus_sink)
    controls={}
    for role in ('plain','primary','outline','danger','success','warning','nav'):
        button=QPushButton('ตัวอย่าง Confirm') if role in ('plain','nav') else btn('ตัวอย่าง Confirm',role)
        if role=='nav':button.setObjectName('nav')
        layout.addWidget(button)
        controls[role]=button
    parent.show()
    settle(250)
    measurements={}
    for role,button in controls.items():
        focus_sink.setFocus()
        settle(250)
        normal=button.grab().toImage()
        button.setEnabled(False)
        settle(250)
        disabled=button.grab().toImage()
        button.setEnabled(True)
        button.setFocus(Qt.FocusReason.TabFocusReason)
        settle(250)
        focused=button.grab().toImage()
        measurements[role]={'enabled_disabled_identical':normal==disabled,
            'normal_focused_identical':normal==focused,'has_focus':button.hasFocus(),
            'font_pt':button.font().pointSizeF(),'font_px':button.font().pixelSize()}
    capture('control-roles',parent)
    # Reproduce empty-list save strictly inside the synthetic database.
    database.set_cfg('pinned_counters_json',json.dumps(['counter.total.total']))
    pinned=PinnedCountersDialog(DeviceConfigRepository(),parent)
    before=database.get_cfg('pinned_counters_json')
    rows=pinned.table.rowCount()
    pinned._save()
    measurements['pinned_empty_save']={'rows':rows,'before':before,'after':database.get_cfg('pinned_counters_json')}
    set_language('en')
    measurements['translation_examples']={s:translate_text(s) for s in ('ช่วงที่แสดงอยู่','ช่วงที่เลือก 31 วัน','เปอร์เซ็นต์แสดงความคืบหน้าตามขั้นตอน')}
    from PyQt6.QtWidgets import QTableWidgetItem
    table=QTableWidget(1,1,parent)
    name='บริษัท แสดงผล จำกัด'
    table.setItem(0,0,QTableWidgetItem(name))
    apply_language(table)
    measurements['table_data_translation']={'before':name,'after':table.item(0,0).text()}
    (out/'measurements.json').write_text(json.dumps(measurements,ensure_ascii=False,indent=2),encoding='utf-8')
    parent.close()


def main_evidence():
    from test_billing_web_amendment import setup
    from test_web_usage_projection import events_for, BANGKOK
    from ui.billing_web_amendment import BillingWebAmendmentDialog
    from ui.web_evidence_report import WebEvidenceDialog
    parent=QWidget()
    parent.setStyleSheet(build_qss())
    parent.show()
    def wait_for(predicate):
        deadline=monotonic()+15
        while not predicate() and monotonic()<deadline:settle(20)
        if not predicate():raise RuntimeError('Synthetic preview not ready')
    database.set_db_path(Path(temp.name)/'amendment.db')
    database.init_db()
    service,scope,_=setup()
    dialog=BillingWebAmendmentDialog(scope,parent,service=service)
    dialog.show()
    dialog.load()
    wait_for(lambda:dialog.future is None and dialog.preview is not None)
    capture('web-amendment-populated',dialog)
    dialog.resize(args.width,args.height)
    capture('web-amendment-populated-compact',dialog)
    dialog.reject()
    dialog.pool.shutdown(wait=True)
    database.set_db_path(Path(temp.name)/'gap.db')
    database.init_db()
    events_for(('2026-09-18T17:00',1000),('2026-09-21T08:00',1301))
    graph=WebEvidenceDialog(DeviceConfigRepository().list(enabled_only=False),parent,
        today=date(2026,9,21),calendar_timezone=BANGKOK)
    graph.show()
    graph.load()
    wait_for(lambda:graph.future is None and graph.projection is not None)
    graph.resize(args.width,args.height)
    for i in range(graph.tabs.count()):
        graph.tabs.setCurrentIndex(i)
        capture(f'web-evidence-populated-{i}',graph)
    graph.reject()
    graph.pool.shutdown(wait=True)
    parent.close()

try:
    if args.mode=='pages':main_pages()
    elif args.mode=='dialogs':main_dialogs()
    elif args.mode=='controls':main_controls()
    elif args.mode=='evidence':main_evidence()
    else:main_wizard()
finally:
    # Dispose native windows while QApplication and its event dispatcher still
    # exist. Leaving a large capture tree for Python's interpreter shutdown is
    # unsafe for Qt charts/effects, even when every screenshot was saved.
    from PyQt6.QtCore import QTimer
    app.setQuitOnLastWindowClosed(False)
    for audit_window in list(app.topLevelWidgets()):
        audit_window.deleteLater()
    QTimer.singleShot(50, app.quit)
    app.exec()
    save()
    print(f'{len(results)} captures; errors={errors}; network attempts={network_attempts}',flush=True)
if errors or network_attempts:
    raise SystemExit(1)
