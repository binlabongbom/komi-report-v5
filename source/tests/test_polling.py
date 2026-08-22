from __future__ import annotations

from datetime import datetime, time, timedelta

from services.polling import DevicePollState, PollingPolicy, PollingStateMachine, ScheduleWindow


def test_snmp_unchanged_skips_web_after_initial_sample():
    machine = PollingStateMachine()
    state = DevicePollState(last_snmp_total=100, last_web_at=datetime(2026, 7, 16, 8, 0))

    decision = machine.snmp_success(state, 100, datetime(2026, 7, 16, 9, 0))

    assert decision.request_web is False
    assert "ไม่เปลี่ยน" in decision.reason


def test_normal_and_peak_throttle():
    machine = PollingStateMachine()
    normal = DevicePollState(last_snmp_total=100, last_web_at=datetime(2026, 7, 16, 10, 0))
    peak = DevicePollState(last_snmp_total=100, last_web_at=datetime(2026, 7, 16, 16, 30))

    normal_decision = machine.snmp_success(normal, 101, datetime(2026, 7, 16, 10, 14))
    peak_decision = machine.snmp_success(peak, 101, datetime(2026, 7, 16, 16, 35))

    assert normal_decision.request_web is False
    assert peak_decision.request_web is True


def test_user_schedule_window_overrides_web_throttle_without_changing_snmp_rules():
    policy = PollingPolicy(
        web_interval=timedelta(minutes=15),
        schedule_windows=(
            ScheduleWindow(
                start=time(9, 0),
                end=time(10, 0),
                web_interval=timedelta(minutes=3),
                label="ช่วงเปิดงาน",
            ),
        ),
    )
    machine = PollingStateMachine(policy)
    state = DevicePollState(last_snmp_total=100, last_web_at=datetime(2026, 8, 5, 9, 0))

    decision = machine.snmp_success(state, 101, datetime(2026, 8, 5, 9, 3))

    assert decision.request_web is True
    assert policy.web_interval_at(datetime(2026, 8, 5, 10, 3)) == timedelta(minutes=15)


def test_collection_policy_controls_snmp_cadence_and_periodic_web_ram_reads():
    policy = PollingPolicy(
        schedule_windows=(
            ScheduleWindow(
                start=time(8, 0),
                end=time(9, 0),
                web_interval=timedelta(minutes=10),
                label="Active",
                snmp_interval=timedelta(minutes=5),
                weekdays=frozenset(range(5)),
            ),
        ),
    )
    machine = PollingStateMachine(policy)
    state = DevicePollState(last_snmp_total=100, last_web_at=datetime(2026, 8, 3, 8, 0))

    decision = machine.snmp_success(state, 100, datetime(2026, 8, 3, 8, 10))

    assert policy.snmp_interval_at(datetime(2026, 8, 3, 8, 10), timedelta(minutes=15)) == timedelta(minutes=5)
    assert policy.snmp_interval_at(datetime(2026, 8, 8, 8, 10), timedelta(minutes=15)) is None
    assert decision.request_web is True
    assert decision.reason == "ถึงรอบ Web/RAM ตาม Schedule"


def test_five_web_failures_mark_offline_and_backoff_hour():
    machine = PollingStateMachine()
    state = DevicePollState()
    now = datetime(2026, 7, 16, 17, 0)

    for index in range(5):
        decision = machine.web_failure(state, now + timedelta(minutes=5 * index))

    assert decision.status == "offline"
    assert state.offline is True
    assert state.next_web_retry_at == now + timedelta(minutes=20, hours=1)
