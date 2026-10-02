"""Process-local wakeups after durable local edits; the database is the queue.

No background thread, network timer or cross-process singleton is created here.
Lost wakeups after a crash are recovered from the durable queue at startup.
"""
from functools import wraps
import logging
from pathlib import Path
from threading import RLock
from weakref import WeakMethod

_lock = RLock()
_subscribers = {}


def subscribe(path, callback):
    token = object()
    with _lock:
        _subscribers[token] = (Path(path).resolve(), WeakMethod(callback))
    def unsubscribe():
        with _lock:
            _subscribers.pop(token, None)
    return unsubscribe


def committed(path):
    path = Path(path).resolve()
    with _lock:
        snapshot = list(_subscribers.items())
    for token, (target, reference) in snapshot:
        callback = reference()
        if callback is None:
            with _lock:
                _subscribers.pop(token, None)
        elif target == path:
            try:
                callback()
            except Exception:
                # The transaction already committed. A failed UI wake must not
                # report that accounting/settings rolled back or undo the queue.
                logging.getLogger(__name__).exception('Unable to wake peer delivery')


def notify_local_change(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        from database import get_db_path
        path = Path(getattr(self, 'path', None) or get_db_path()).resolve()
        result = method(self, *args, **kwargs)
        committed(path)
        return result
    return invoke
