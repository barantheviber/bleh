"""Alarmlar tab: price and indicator alerts, checked on a timer while the app
runs (in the tray too), with a Windows notification when one fires."""

import datetime as dt

from PySide6 import QtCore, QtWidgets

from .. import alerts
from ..data.yahoo import DataError
from . import theme
from .tab_bot import _set_row, _table
from .workers import run_async


class AlertsTab(QtWidgets.QWidget):
    status = QtCore.Signal(str)
    fired = QtCore.Signal(str, str)        # title, message

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._busy = False
        self._again = False                # a check was asked for while one ran
        self.current = {}                  # alert id -> latest detail text

        self.symbol = QtWidgets.QLineEdit()
        self.symbol.setPlaceholderText("Sembol (SPY, AAPL, THYAO.IS)")
        self.kind = QtWidgets.QComboBox()
        for key, name in alerts.KINDS.items():
            self.kind.addItem(name, key)
        self.value = QtWidgets.QDoubleSpinBox()
        self.value.setRange(0, 1e7)
        self.value.setDecimals(2)
        self.value.setValue(100)
        self.once = QtWidgets.QCheckBox("Bir kez çalsın, sonra kapansın")
        self.once.setChecked(True)
        self.note = QtWidgets.QLineEdit()
        self.note.setPlaceholderText("Not (isteğe bağlı)")
        add = theme.button("Alarm ekle", "primary")
        add.clicked.connect(self.add)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        form = QtWidgets.QFormLayout()
        form.addRow("Sembol", self.symbol)
        form.addRow("Koşul", self.kind)
        form.addRow("Değer", self.value)
        form.addRow(self.once)
        form.addRow("Not", self.note)
        form.addRow(add)
        box = QtWidgets.QGroupBox("Yeni alarm")
        bl = QtWidgets.QVBoxLayout(box)
        bl.addLayout(form)
        bl.addWidget(theme.label(
            "Alarm, koşul gerçekleştiği anda bir kez çalar (kesişme); koşul sürerken tekrar "
            "çalmaz. Uygulama açıkken ya da tepsideyken her dakika kontrol edilir. Fiyatlar "
            "Yahoo Finance'ten gelir ve gecikmeli olabilir.", "muted", wrap=True))
        bl.addStretch(1)

        self.table = _table(["Alarm", "Durum", "Şu an", "Son çalma", "Not"], stretch=0)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        for c in (1, 3):
            hdr.setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeToContents)
        toggle = theme.button("Aç / kapat")
        toggle.clicked.connect(self.toggle)
        remove = theme.button("Sil", "danger")
        remove.clicked.connect(self.remove)
        check = theme.button("Şimdi kontrol et")
        check.clicked.connect(self.check)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(theme.label("Alarmlar", "title"))
        row.addStretch(1)
        for b in (check, toggle, remove):
            row.addWidget(b)
        self.log = QtWidgets.QListWidget()
        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addLayout(row)
        rl.addWidget(self.table, 3)
        rl.addWidget(theme.label("Son çalan alarmlar", "muted"))
        rl.addWidget(self.log, 1)

        split = QtWidgets.QSplitter()
        split.addWidget(box)
        split.addWidget(right)
        split.setSizes([380, 1000])
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(split)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.check)
        self.timer.start(max(15, int(ctx.settings.get("alert_check_seconds") or 60)) * 1000)
        self._kind_changed()
        self.refresh_table()

    # ------------------------------------------------------------ model

    def alerts(self):
        return [dict(a) for a in (self.ctx.settings.get("alerts") or [])]

    def _save(self, items):
        self.ctx.settings.set("alerts", items)

    def prefill(self, symbol, kind="price_above", value=None):
        self.symbol.setText(symbol.upper())
        self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
        if value is not None:
            self.value.setValue(float(value))

    def _kind_changed(self, *_):
        kind = self.kind.currentData()
        self.value.setEnabled(kind not in alerts.NO_VALUE)
        if kind in ("sma_up", "sma_down"):
            self.value.setDecimals(0)
            self.value.setValue(200)
        elif kind in ("rsi_above", "rsi_below"):
            self.value.setDecimals(0)
            self.value.setValue(70 if kind == "rsi_above" else 30)
        elif kind in ("change_up", "change_down"):
            self.value.setDecimals(1)
            self.value.setValue(3)
        else:
            self.value.setDecimals(2)

    def add(self):
        try:
            a = alerts.new_alert(self.symbol.text(), self.kind.currentData(), self.value.value(),
                                 self.once.isChecked(), self.note.text().strip())
        except alerts.AlertError as exc:
            QtWidgets.QMessageBox.warning(self, "Alarm", str(exc))
            return
        self._save(self.alerts() + [a])
        self.note.clear()
        self.refresh_table()
        self.status.emit("Alarm eklendi: %s" % alerts.describe(a))
        self.check()                     # learn the current state right away

    def _selected_id(self):
        r = self.table.currentRow()
        if r < 0:
            return None
        return self.table.item(r, 0).data(QtCore.Qt.UserRole)

    def toggle(self):
        aid = self._selected_id()
        items = self.alerts()
        for a in items:
            if a["id"] == aid:
                a["enabled"] = not a.get("enabled")
                a["last_state"] = None   # re-learn the state before firing again
        self._save(items)
        self.refresh_table()

    def remove(self):
        aid = self._selected_id()
        if aid is None:
            return
        self._save([a for a in self.alerts() if a["id"] != aid])
        self.refresh_table()

    def refresh_table(self):
        items = self.alerts()
        self.table.setRowCount(len(items))
        for r, a in enumerate(items):
            on = a.get("enabled")
            _set_row(self.table, r, [alerts.describe(a), "Açık" if on else "Kapalı",
                                     self.current.get(a["id"], "—"),
                                     (a.get("triggered_at") or "—").replace("T", " "),
                                     a.get("note") or ""],
                     {1: theme.UP if on else theme.MUTED})
            self.table.item(r, 0).setData(QtCore.Qt.UserRole, a["id"])
            for c in range(5):
                self.table.item(r, c).setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

    # ------------------------------------------------------------ checking

    def check(self):
        items = [a for a in self.alerts() if a.get("enabled")]
        if self._busy:
            self._again = True
            return
        if not items:
            return
        self._busy = True
        run_async(self._evaluate, items, done=self._evaluated,
                  failed=lambda m: (setattr(self, "_busy", False),
                                    self.status.emit("Alarm kontrolü başarısız: %s" % m)))

    def _evaluate(self, items):
        """Worker thread: the condition of every enabled alert, one fetch per symbol."""
        cache, out = {}, {}
        for a in items:
            sym = a["symbol"]
            if sym not in cache:
                try:
                    bars = self.ctx.data.bars(sym, "1d", "2y")[0]
                    q = self.ctx.data.quote(sym)
                    cache[sym] = (bars, q.price, q.prev_close)
                except DataError as exc:
                    cache[sym] = exc
            got = cache[sym]
            if isinstance(got, Exception):
                out[a["id"]] = (None, "veri yok: %s" % got)
            else:
                out[a["id"]] = alerts.condition(a, got[0], got[1], got[2])
        return out

    def _evaluated(self, states):
        self._busy = False
        items = self.alerts()
        now = dt.datetime.now()
        for a in items:
            if a["id"] not in states or not a.get("enabled"):
                continue
            state, detail = states[a["id"]]
            self.current[a["id"]] = detail + (" · koşul sağlanıyor" if state else "")
            if alerts.update(a, state, now):
                text = "%s (%s)" % (alerts.describe(a), detail)
                self.log.insertItem(0, "%s  %s" % (now.strftime("%d.%m %H:%M"), text))
                self.fired.emit("Alarm: %s" % a["symbol"], text)
                self.status.emit("Alarm çaldı: %s" % text)
        self._save(items)
        self.refresh_table()
        if self._again:
            self._again = False
            self.check()
