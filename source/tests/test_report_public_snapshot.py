from threading import Event
from types import SimpleNamespace

from excel_export_fixture import report_for

from services import report_snapshot


def test_existing_printer_totals_become_public_rows_without_new_auth_observations(monkeypatch):
    report = report_for(users=2, days=3, printers=3)
    subjects = tuple(subject for subject in report.subjects if subject.device_slot == 2)
    counters = tuple(counter for counter in report.raw_counter_records if counter.device_slot == 2)
    monkeypatch.setattr(report_snapshot, 'report_slots', lambda: (0, 1, 2))
    monkeypatch.setattr(report_snapshot, 'load_usage_history', lambda *args, **kwargs: report.selected_daily_records)
    monkeypatch.setattr(report_snapshot, 'load_subject_history', lambda *args, **kwargs: subjects)
    monkeypatch.setattr(report_snapshot, 'load_user_counter_history', lambda *args, **kwargs: counters)
    snapshot = report_snapshot.load_report_snapshot(
        1, report.period, cache=None, subject_cache=None,
        repository=SimpleNamespace(list=lambda **kwargs: report.devices), cancelled=Event(),
    )
    models = snapshot.data['prepared_models']
    assert [row['name'] for row in models['users']] == ['User 000', 'User 001']
    public, = models['public_users']
    assert public['name'] == 'Public User' and public['key'] == 'public:all'
    assert public['usage'] == 96
    assert set(public['by_slot']) == {0, 1}
    for values in public['by_slot'].values():
        assert values['total'] == 48
        assert values['print_a3_color'] == 6
        assert values['print_a4_color'] == 6
        assert values['cost'] == 96
    # The two real users and one public aggregate cover each printer exactly once.
    assert sum(row['usage'] for row in (*models['users'], *models['public_users'])) == 144
