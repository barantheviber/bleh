"""Shared state for the window: settings, market data, broker and bot engine.

Engine events come from worker threads; they reach widgets through the
`event` signal, which Qt delivers on the UI thread.
"""

import logging

from PySide6 import QtCore

from .. import brokers, config, market_clock
from ..data.service import MarketData
from ..engine import BotEngine

log = logging.getLogger("traderbot")


class AppContext(QtCore.QObject):
    event = QtCore.Signal(str, dict)        # engine journal events
    broker_changed = QtCore.Signal()
    settings_changed = QtCore.Signal()
    log_line = QtCore.Signal(str)

    def __init__(self, settings=None, data=None, parent=None):
        super().__init__(parent)
        self.settings = settings or config.Settings()
        self.data = data or MarketData()
        self.broker = None
        self.broker_error = ""
        self.engine = None
        self.rebuild_broker()

    def price_source(self, symbols):
        return self.data.prices(symbols)

    def rebuild_broker(self):
        """Broker per the settings; on failure fall back to the simulator and
        remember why, so the UI can say it."""
        try:
            self.broker = brokers.create(self.settings, self.price_source)
            self.broker_error = ""
        except brokers.BrokerError as exc:
            self.broker_error = str(exc)
            log.warning("broker: %s; using the simulator", exc)
            self.broker = brokers.create_sim(self.settings, self.price_source)
        running = self.engine.snapshot()["running"] if self.engine else False
        self.engine = BotEngine(self.settings, self.broker, self.data,
                                on_event=lambda kind, rec: self.event.emit(kind, rec))
        if running and not self.engine.snapshot()["running"]:
            self.engine.start()
        self.broker_changed.emit()

    def market(self):
        return market_clock.status()

    def is_live(self):
        return self.settings.is_live() and not self.broker_error
