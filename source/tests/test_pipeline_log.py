from services.pipeline_log import PipelineLogStore


def test_pipeline_log_is_thread_safe_shape_and_bounded():
    store = PipelineLogStore(max_events=100)
    for index in range(125):
        store.append(
            stage="snmp",
            action="OID response",
            device_slot=0,
            device_name="Office",
            host="192.0.2.10",
            target=f"1.3.6.1.{index}",
            value=index,
            status="ok",
        )

    events = store.snapshot()

    assert len(events) == 100
    assert events[0].value == "124"
    assert events[-1].value == "25"
    assert events[0].stage == "SNMP"


def test_pipeline_log_clear_keeps_sequence_monotonic():
    store = PipelineLogStore()
    first = store.append(stage="RAM", action="cache", value=1)
    store.clear()
    second = store.append(stage="DB", action="rollup", value=2)

    assert store.snapshot() == [second]
    assert second.sequence > first.sequence
