"""Run slow work (network, backtests) off the UI thread.

run_async(fn, ..., done=cb, failed=cb) runs fn in Qt's thread pool and calls
the callbacks back on the UI thread through queued signals.
"""

import logging
import traceback

from PySide6 import QtCore

log = logging.getLogger("traderbot.ui")
_alive = set()


class _Signals(QtCore.QObject):
    done = QtCore.Signal(object)
    failed = QtCore.Signal(str)


class _Task(QtCore.QRunnable):
    def __init__(self, fn, args, kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()
        self.setAutoDelete(True)

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # reported to the UI, never lost
            log.warning("background task failed: %s\n%s", exc, traceback.format_exc(limit=6))
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.signals.done.emit(result)


def run_async(fn, *args, done=None, failed=None, **kwargs):
    task = _Task(fn, args, kwargs)
    sig = task.signals
    _alive.add(sig)

    def _finish(*_):
        _alive.discard(sig)

    if done:
        sig.done.connect(done)
    if failed:
        sig.failed.connect(failed)
    sig.done.connect(_finish)
    sig.failed.connect(_finish)
    QtCore.QThreadPool.globalInstance().start(task)
    return task


def wait_all(msecs=30000):
    """Block until background tasks finish (self-test and shutdown)."""
    return QtCore.QThreadPool.globalInstance().waitForDone(msecs)
