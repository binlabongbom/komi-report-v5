from types import SimpleNamespace as NS

from i18n import set_language
from services.sidebar_reader_role import reader_role_text


def runtime(owners):
    election = NS(member_id='LOCAL', owner=lambda slot: owners.get(slot))
    # Neither probe nor election is allowed while painting a status label.
    def forbidden(*args, **kwargs):
        raise AssertionError('Display started network work')
    election.select = election.probe = forbidden
    return NS(repository=NS(list=lambda **kwargs: [NS(slot=s) for s in sorted(owners)]),
        shared_reads=NS(router=NS(election=election), current_scope=lambda slot: slot),
        peer_network_runtime=NS(state='connected', _future=None))


def test_role_tracks_owner_change_and_invalidated_decision_without_network_calls():
    owners = {0: 'REMOTE', 1: 'REMOTE'}
    polling = runtime(owners)
    assert reader_role_text(polling)[0] == 'กำลังเป็นผู้รับข้อมูล'
    owners.update({0: 'LOCAL', 1: 'LOCAL'})
    assert reader_role_text(polling)[0] == 'กำลังเป็นผู้อ่านหลัก'
    owners[0] = None
    assert reader_role_text(polling)[0] == 'กำลังตรวจสอบบทบาท'


def test_split_roles_and_connection_failure_are_not_reported_as_all_primary():
    polling = runtime({0: 'LOCAL', 1: 'REMOTE'})
    text, tooltip = reader_role_text(polling)
    assert text == 'กำลังเป็นผู้อ่านหลัก / ผู้รับข้อมูล'
    assert 'Slot 1: กำลังเป็นผู้อ่านหลัก' in tooltip
    assert 'Slot 2: กำลังเป็นผู้รับข้อมูล' in tooltip
    polling.peer_network_runtime.state = 'unavailable'
    assert reader_role_text(polling)[0] == 'กำลังตรวจสอบบทบาท'


def test_standalone_and_initial_join_and_english():
    polling = runtime({0: None})
    polling.shared_reads = None
    assert reader_role_text(polling)[0] == 'กำลังตรวจสอบบทบาท'
    polling.peer_network_runtime.state = 'not_enrolled'
    assert reader_role_text(polling)[0] == 'กำลังเป็นผู้อ่านหลัก'
    polling.peer_network_runtime._future = object()
    assert reader_role_text(polling)[0] == 'กำลังตรวจสอบบทบาท'
    set_language('en')
    assert reader_role_text(runtime({0: 'REMOTE'}))[0] == 'Receiving shared data'


def test_sidebar_retains_role_between_rounds_and_registration_pause_wins():
    from app import MainWindow
    from PyQt6.QtWidgets import QApplication, QLabel
    app = QApplication.instance() or QApplication([])
    label = QLabel()
    window = NS(_background_started=True, polling=runtime({0: 'REMOTE'}), status_lbl=label,
        _registration_usage_eligibility=lambda: (True, 'registered'))
    MainWindow._refresh_sidebar_role(window)
    assert label.text() == 'สถานะ\nกำลังเป็นผู้รับข้อมูล'
    MainWindow._refresh_sidebar_role(window)
    assert label.text() == 'สถานะ\nกำลังเป็นผู้รับข้อมูล'
    window._registration_usage_eligibility = lambda: (False, 'deactivated')
    MainWindow._refresh_sidebar_role(window)
    assert 'หยุดอ่านข้อมูล' in label.text()
    assert 'กำลังเป็น' not in label.text()
    label.close()
