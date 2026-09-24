"""Keep resource cleanup callbacks alive throughout Python/Qt destruction."""
from weakref import finalize


def _shutdown_executor(executor, cancelled):
    if cancelled is not None:
        cancelled.set()
    executor.shutdown(wait=False, cancel_futures=True)


def close_executor_with(owner, executor, cancelled=None):
    # A lambda stored only on QObject.destroyed can itself be cleared during
    # cyclic GC before Qt emits the signal. finalize retains this callback
    # independently and runs it once, whether Qt or Python destroys first.
    # Its arguments must not retain the owning QObject.
    cleanup = finalize(owner, _shutdown_executor, executor, cancelled)
    owner.destroyed.connect(cleanup)
