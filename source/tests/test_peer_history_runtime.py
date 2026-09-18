from threading import Event, Timer
from time import monotonic
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtNetwork import QNetworkInformation

from services.peer_history_runtime import PeerHistoryRuntime
from services.peer_history_session import CatchupResult
from services.web_observations import WebObservationStore
from test_peer_history_session import peers, session
from test_web_observations import store, record


def until(predicate):
    app = QApplication.instance() or QApplication([])
    deadline = monotonic() + 5
    while not predicate() and monotonic() < deadline:
        QTest.qWait(5)
    assert predicate()
    return app


def test_start_once_then_explicit_reconnect_fetches_missing_data(peers):
    paths, nodes = peers
    first = record(store(), 1)
    worker, remote = session(paths, nodes)
    runtime = PeerHistoryRuntime()
    received = []
    runtime.history_received.connect(lambda member, result: received.append(result.observations))
    try:
        runtime.attach(worker)
        assert runtime._pool is None
        runtime.start()
        until(lambda: not runtime.busy)
        assert received == [1]
        assert runtime.snapshot()[0]["last_success"]
        second = record(store(), 2)
        runtime.start()
        runtime.attach(worker)
        QTest.qWait(25)
        assert WebObservationStore(paths["B"]).page()["events"] == [first]
        runtime.network_recovered()
        until(lambda: not runtime.busy)
        assert received == [1, 1]
        assert WebObservationStore(paths["B"]).page()["events"] == [first, second]
    finally:
        runtime.stop(wait=True)


def test_small_quanta_drain_fairly_across_known_members(peers):
    paths, nodes = peers
    for minute in range(4):
        record(store(), minute)
    first, _ = session(paths, nodes)
    second, _ = session(paths, nodes, sender="C")
    original = first.run
    calls = []
    def small(**kwargs):
        calls.append("A")
        return original(max_pages=1, page_size=1, **kwargs)
    first.run = small
    other = second.run
    def empty(**kwargs):
        calls.append("C")
        return other(**kwargs)
    second.run = empty
    runtime = PeerHistoryRuntime()
    try:
        runtime.attach(first)
        runtime.attach(second)
        runtime.start()
        until(lambda: not runtime.busy)
        assert calls == ["A", "C", "A", "A", "A"]
        assert nodes["B"].progress("A")["complete"]
        assert all(row["status"] == "complete" for row in runtime.snapshot())
    finally:
        runtime.stop(wait=True)


def test_failure_waits_for_recovery_event_and_keeps_durable_cursor(peers):
    paths, nodes = peers
    record(store(), 1)
    worker, remote = session(paths, nodes)
    page = remote.page
    def offline(*args, **kwargs):
        raise TimeoutError("synthetic offline")
    remote.page = offline
    runtime = PeerHistoryRuntime()
    try:
        runtime.start()
        runtime.attach(worker)  # Membership ready after Agent startup.
        until(lambda: not runtime.busy)
        assert runtime.snapshot()[0]["error"] == "timeout"
        assert nodes["B"].progress("A")["after"] == 0
        remote.page = page
        QTest.qWait(30)
        assert nodes["B"].progress("A")["after"] == 0
        runtime.network_recovered()
        until(lambda: not runtime.busy)
        assert nodes["B"].progress("A")["after"] == 1
    finally:
        runtime.stop(wait=True)


def test_shutdown_drains_transport_then_prevents_page_commit(peers):
    paths, nodes = peers
    record(store(), 1)
    worker, remote = session(paths, nodes)
    page = remote.page
    started, release = Event(), Event()
    def blocked(*args, **kwargs):
        result = page(*args, **kwargs)
        started.set()
        assert release.wait(5)
        return result
    remote.page = blocked
    runtime = PeerHistoryRuntime()
    try:
        runtime.attach(worker)
        runtime.start()
        assert started.wait(3)
        assert runtime.stop() == 1
        timer = Timer(0.1, release.set)
        timer.start()
        before = monotonic()
        runtime.stop(wait=True)
        assert monotonic() - before >= 0.08
        timer.join()
        runtime.network_recovered()
        assert nodes["B"].progress("A")["after"] == 0
        assert WebObservationStore(paths["B"]).page()["events"] == []
    finally:
        release.set()
        runtime.stop(wait=True)


def test_replacement_session_cancels_old_and_reconnect_during_call_is_not_lost(peers):
    paths, nodes = peers
    record(store(), 1)
    old, remote = session(paths, nodes)
    fresh, _ = session(paths, nodes)
    page = remote.page
    entered, release = Event(), Event()
    def blocked(*args, **kwargs):
        result = page(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return result
    remote.page = blocked
    runtime = PeerHistoryRuntime()
    try:
        runtime.attach(old)
        runtime.start()
        assert entered.wait(3)
        runtime.attach(fresh)
        runtime.network_recovered()
        release.set()
        until(lambda: not runtime.busy)
        assert nodes["B"].progress("A")["after"] == 1
        assert runtime.snapshot()[0]["status"] == "complete"
        runtime.detach("A")
        assert runtime.snapshot() == []
    finally:
        release.set()
        runtime.stop(wait=True)


def test_no_progress_budget_never_busy_loops_and_idle_allocates_no_workers(peers):
    paths, nodes = peers
    worker, _ = session(paths, nodes)
    calls = []
    def pending(**kwargs):
        calls.append(1)
        return CatchupResult("pending", 0, 0, 0, 0, 2)
    worker.run = pending
    runtime = PeerHistoryRuntime()
    try:
        runtime.start()
        runtime.network_recovered()
        assert runtime._pool is None
        runtime.attach(worker)
        until(lambda: not runtime.busy)
        QTest.qWait(30)
        assert calls == [1]
        assert runtime.snapshot()[0]["status"] == "pending"
    finally:
        runtime.stop(wait=True)


def test_reconnect_arriving_during_page_fetch_drains_the_new_tail(peers):
    paths, nodes = peers
    record(store(), 1)
    worker, remote = session(paths, nodes)
    page = remote.page
    entered, release = Event(), Event()
    def blocked(*args, **kwargs):
        result = page(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return result
    remote.page = blocked
    runtime = PeerHistoryRuntime()
    try:
        runtime.attach(worker)
        runtime.start()
        assert entered.wait(3)
        record(store(), 2)
        runtime.network_recovered()
        release.set()
        until(lambda: not runtime.busy)
        assert nodes["B"].progress("A")["after"] == 2
    finally:
        release.set()
        runtime.stop(wait=True)


def test_polling_owns_peer_lifetime_even_when_printer_collection_paused(peers):
    from services.background_polling import BackgroundPollingCoordinator
    paths, nodes = peers
    event = record(store(), 1)
    worker, _ = session(paths, nodes)
    runtime = PeerHistoryRuntime()
    runtime.attach(worker)
    polling = BackgroundPollingCoordinator(peer_history=runtime)
    try:
        polling.pause("fixture")
        polling.start()
        until(lambda: not runtime.busy)
        assert WebObservationStore(paths["B"]).page()["events"] == [event]
        assert not polling.timer.isActive()
    finally:
        polling.stop(wait=True)
    assert runtime._stopped


def test_agent_recovery_transition_wakes_both_services_without_periodic_polling():
    from services.background_agent import BackgroundAgent
    values = QNetworkInformation.Reachability
    calls = []
    owner = SimpleNamespace(_stopping=False, _last_network_reachability=values.Disconnected,
        registration=SimpleNamespace(network_recovered=lambda: calls.append("host")),
        polling=SimpleNamespace(peer_history=SimpleNamespace(network_recovered=lambda: calls.append("peer"))))
    for value in (values.Local, values.Site, values.Online):
        BackgroundAgent._network_reachability_changed(owner, value)
    assert calls == ["host", "peer"]
    owner._stopping = True
    owner._last_network_reachability = values.Disconnected
    BackgroundAgent._network_reachability_changed(owner, values.Online)
    assert calls == ["host", "peer"]
