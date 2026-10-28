"""Log tab: the application log as it happens."""

import logging

from PySide6 import QtCore, QtGui, QtWidgets

from .. import log as applog
from .. import paths
from . import theme


class _Bridge(QtCore.QObject):
    line = QtCore.Signal(str)


class QtLogHandler(logging.Handler):
    """Thread-safe: records from any thread reach the widget through a signal."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.bridge = _Bridge()
        self.setFormatter(logging.Formatter(applog.FORMAT, "%H:%M:%S"))

    def emit(self, record):
        try:
            self.bridge.line.emit(self.format(record))
        except Exception:
            pass


class LogTab(QtWidgets.QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.view = QtWidgets.QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        self.view.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        folder = theme.button("Günlük klasörünü aç")
        folder.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(paths.path("logs", "x")[:-2])))
        clear = theme.button("Temizle")
        clear.clicked.connect(self.view.clear)
        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(theme.label("Uygulama günlüğü", "title"))
        bar.addStretch(1)
        bar.addWidget(clear)
        bar.addWidget(folder)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(bar)
        lay.addWidget(self.view, 1)
        self.handler = QtLogHandler()
        self.handler.bridge.line.connect(self.view.appendPlainText)
        logging.getLogger().addHandler(self.handler)
        ctx.event.connect(lambda kind, rec: logging.getLogger("traderbot.bot").info(
            "%s: %s", kind, rec.get("message", "")))

    def detach(self):
        logging.getLogger().removeHandler(self.handler)
