import gc
import weakref
from threading import Event
from unittest.mock import Mock

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QObject

from ui.resource_cleanup import close_executor_with


@pytest.mark.parametrize("destruction", ["python", "qt", "parent"])
def test_executor_cleanup_survives_cyclic_gc_and_runs_once(destruction):
    # Parent-owned QObjects may be destroyed while their Python wrappers still
    # exist; Python cycles can also disappear before a native destroyed signal.
    for _ in range(25):
        parent = QObject() if destruction == "parent" else None
        owner = QObject(parent)
        owner.cycle = owner
        executor = Mock()
        cancelled = Event()
        close_executor_with(owner, executor, cancelled)
        reference = weakref.ref(owner)
        if destruction == "qt":
            sip.delete(owner)
        elif destruction == "parent":
            sip.delete(parent)
        if destruction != "python":
            assert cancelled.is_set()
            executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
        del owner
        gc.collect()
        assert reference() is None
        assert cancelled.is_set()
        executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
