"""Chart tab: watchlist on the left, live chart on the right."""

import datetime as dt
import logging
import re

from PySide6 import QtCore, QtGui, QtWidgets

from ..data.yahoo import DataError
from . import theme
from .chart import INTERVAL_NAMES, OVERLAYS, PANES, ChartWidget
from .platform_window import PlatformWindow
from .workers import run_async

log = logging.getLogger("traderbot.ui")

INTERVALS = [("1m", "1dk"), ("5m", "5dk"), ("15m", "15dk"), ("60m", "1sa"), ("1d", "Gün"),
             ("1wk", "Hafta")]
LOAD_RANGE = {"1m": "5d", "5m": "1mo", "15m": "1mo", "60m": "6mo", "1d": "5y", "1wk": "10y"}
LIVE_RANGE = {"1m": "1d", "5m": "1d", "15m": "5d", "60m": "5d", "1d": "5d", "1wk": "1mo"}


class Watchlist(QtWidgets.QWidget):
    picked = QtCore.Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Sembol", "Son", "Değ. %"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.cellClicked.connect(lambda r, c: self.picked.emit(self.table.item(r, 0).text()))
        self.add_box = QtWidgets.QLineEdit()
        self.add_box.setPlaceholderText("Sembol ekle (AAPL, THYAO.IS, BTC-USD)")
        self.add_box.returnPressed.connect(self._add)
        add = theme.button("+", tip="İzleme listesine ekle")
        add.clicked.connect(self._add)
        rm = theme.button("−", tip="Seçili sembolü çıkar")
        rm.clicked.connect(self._remove)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.add_box, 1)
        row.addWidget(add)
        row.addWidget(rm)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(theme.label("İzleme listesi", "title"))
        lay.addWidget(self.table, 1)
        lay.addLayout(row)
        self.symbols = []
        self.set_symbols(ctx.settings.get("watchlist") or [])
        self._busy = False

    def set_symbols(self, symbols):
        self.symbols = list(dict.fromkeys(s.upper() for s in symbols if s.strip()))
        self.table.setRowCount(len(self.symbols))
        for r, s in enumerate(self.symbols):
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(s))
            for c in (1, 2):
                it = QtWidgets.QTableWidgetItem("…")
                it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                self.table.setItem(r, c, it)

    def _save(self):
        self.ctx.settings.set("watchlist", self.symbols)

    def _add(self):
        s = self.add_box.text().strip().upper()
        if s and s not in self.symbols:
            self.set_symbols(self.symbols + [s])
            self._save()
            self.refresh()
        self.add_box.clear()

    def _remove(self):
        r = self.table.currentRow()
        if r >= 0:
            self.set_symbols(self.symbols[:r] + self.symbols[r + 1:])
            self._save()

    def refresh(self):
        if self._busy or not self.symbols:
            return
        self._busy = True
        syms = list(self.symbols)

        def fetch():
            out = {}
            for s in syms:
                try:
                    out[s] = self.ctx.data.quote(s)
                except DataError as exc:
                    out[s] = exc
            return out

        run_async(fetch, done=self._show, failed=self._failed)

    def _failed(self, msg):
        self._busy = False

    def _show(self, quotes):
        self._busy = False
        for r, s in enumerate(self.symbols):
            q = quotes.get(s)
            if q is None:
                continue
            if isinstance(q, Exception):
                self.table.item(r, 1).setText("—")
                self.table.item(r, 1).setToolTip(str(q))
                continue
            price = q.price
            self.table.item(r, 1).setText("" if price is None else "%.2f" % price)
            pct = q.change_pct
            it = self.table.item(r, 2)
            it.setText("" if pct is None else "%+.2f%%" % pct)
            it.setForeground(QtGui.QColor(theme.color_for(pct)))


class ChartTab(QtWidgets.QWidget):
    status = QtCore.Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        cfg = ctx.settings.get("chart") or {}
        self.symbol = (cfg.get("symbol") or "SPY").upper()
        self.interval = cfg.get("interval") or "5m"
        if self.interval not in LOAD_RANGE:
            self.interval = "5m"
        self.meta = {}
        self._loading = False
        self._live_busy = False

        self.chart = ChartWidget()
        self.chart.set_indicators(cfg.get("overlays") or ["ema20", "ema50", "bb"],
                                  cfg.get("panes") or ["volume", "rsi", "macd"])
        self.watch = Watchlist(ctx)
        self.watch.picked.connect(self.load_symbol)

        self.sym_box = QtWidgets.QLineEdit(self.symbol)
        self.sym_box.setFixedWidth(130)
        self.sym_box.setPlaceholderText("Sembol")
        self.sym_box.returnPressed.connect(lambda: self.load_symbol(self.sym_box.text()))
        search = theme.button("Ara", tip="Yahoo Finance'te şirket/sembol ara")
        search.clicked.connect(self._search)
        self.interval_group = QtWidgets.QButtonGroup(self)
        self.interval_group.setExclusive(True)
        ints = QtWidgets.QHBoxLayout()
        ints.setSpacing(2)
        for key, name in INTERVALS:
            b = theme.button(name, checkable=True)
            b.setProperty("interval", key)
            b.setChecked(key == self.interval)
            self.interval_group.addButton(b)
            ints.addWidget(b)
        self.interval_group.buttonClicked.connect(
            lambda b: self.set_interval(b.property("interval")))
        ind_btn = QtWidgets.QToolButton()
        ind_btn.setText("Göstergeler ▾")
        ind_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(ind_btn)
        self.ind_actions = {}
        for key, name in list(OVERLAYS.items()) + list(PANES.items()):
            act = menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(key in self.chart.overlays or key in self.chart.panes)
            act.toggled.connect(self._indicators_changed)
            self.ind_actions[key] = act
        ind_btn.setMenu(menu)
        self.live_btn = theme.button("● Canlı", checkable=True,
                                     tip="Grafiği birkaç saniyede bir yenile")
        self.live_btn.setChecked(True)
        platform = theme.button("Platform penceresi", "primary",
                                tip="Bu sembolü TradingView / Yahoo / Finviz'de aç (açılır pencere)")
        platform.clicked.connect(self.open_platform)
        shot = theme.button("PNG", tip="Grafiği resim olarak kaydet")
        shot.clicked.connect(self._save_png)

        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(self.sym_box)
        bar.addWidget(search)
        bar.addSpacing(10)
        bar.addLayout(ints)
        bar.addSpacing(10)
        bar.addWidget(ind_btn)
        bar.addWidget(self.live_btn)
        bar.addStretch(1)
        bar.addWidget(shot)
        bar.addWidget(platform)
        self.note = theme.label("", "muted")
        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addLayout(bar)
        rl.addWidget(self.chart, 1)
        rl.addWidget(self.note)
        split = QtWidgets.QSplitter()
        split.addWidget(self.watch)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 1100])
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(split)
        self._platforms = []

        self.live_timer = QtCore.QTimer(self)
        self.live_timer.timeout.connect(self.refresh_live)
        self.live_timer.start(max(3, int(ctx.settings.get("refresh_seconds") or 10)) * 1000)
        self.watch_timer = QtCore.QTimer(self)
        self.watch_timer.timeout.connect(self.watch.refresh)
        self.watch_timer.start(15000)

    # ------------------------------------------------------------ actions

    def start(self):
        self.load()
        self.watch.refresh()

    def load_symbol(self, symbol):
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return
        self.symbol = symbol
        self.sym_box.setText(symbol)
        self._remember()
        self.load()

    def set_interval(self, interval):
        self.interval = interval
        self._remember()
        self.load()

    def _remember(self):
        self.ctx.settings.update({"chart": {"symbol": self.symbol, "interval": self.interval,
                                            "overlays": sorted(self.chart.overlays),
                                            "panes": sorted(self.chart.panes)}})

    def _indicators_changed(self, *_):
        overlays = [k for k in OVERLAYS if self.ind_actions[k].isChecked()]
        panes = [k for k in PANES if self.ind_actions[k].isChecked()]
        self.chart.set_indicators(overlays, panes)
        self._remember()

    def load(self):
        sym, interval = self.symbol, self.interval
        self._loading = True
        self.note.setText("%s yükleniyor…" % sym)

        def fetch():
            bars, meta = self.ctx.data.bars(sym, interval, LOAD_RANGE[interval], fresh=True)
            return sym, interval, bars, meta, self._trades(sym)

        run_async(fetch, done=self._loaded, failed=self._load_failed)

    def _trades(self, symbol):
        """The broker's fills in this symbol, for markers, and the average cost."""
        marks, avg = [], None
        try:
            for o in self.ctx.broker.orders(limit=200):
                if o.symbol == symbol and o.filled_at and o.filled_avg_price:
                    t = _parse_ts(o.filled_at)
                    if t:
                        marks.append({"time": t, "side": o.side, "price": o.filled_avg_price})
            for p in self.ctx.broker.positions():
                if p.symbol == symbol:
                    avg = p.avg_price
        except Exception as exc:  # markers are a nicety, never block the chart
            log.info("chart markers skipped: %s", exc)
        return marks, avg

    def _loaded(self, res):
        sym, interval, bars, meta, (marks, avg) = res
        self._loading = False
        if sym != self.symbol or interval != self.interval:
            return
        self.meta = meta
        self.chart.set_bars(bars, meta)
        self.chart.set_markers(marks)
        self.chart.set_position_price(avg)
        self._note(meta)

    def _load_failed(self, msg):
        self._loading = False
        self.note.setText("Yüklenemedi: %s" % msg)
        self.status.emit("Grafik verisi alınamadı: %s" % msg)

    def refresh_live(self):
        if not self.live_btn.isChecked() or self._loading or self._live_busy \
                or self.chart.bars is None or not self.isVisible():
            return
        sym, interval = self.symbol, self.interval
        self._live_busy = True

        def fetch():
            newer, meta = self.ctx.data.bars(sym, interval, LIVE_RANGE[interval], fresh=True)
            return sym, interval, newer, meta

        run_async(fetch, done=self._live_done, failed=self._live_failed)

    def _live_done(self, res):
        self._live_busy = False
        sym, interval, newer, meta = res
        if sym != self.symbol or interval != self.interval or self.chart.bars is None:
            return
        self.chart.update_bars(self.chart.bars.merge(newer), meta)
        self._note(meta)

    def _live_failed(self, msg):
        self._live_busy = False
        self.note.setText("Canlı güncelleme başarısız: %s" % msg)

    def _note(self, meta):
        cur = meta.get("currency") or ""
        ex = meta.get("fullExchangeName") or meta.get("exchangeName") or ""
        self.note.setText("%s · %s · %s · son güncelleme %s · kaynak: Yahoo Finance (gecikmeli "
                          "olabilir)" % (self.symbol, ex, cur, dt.datetime.now().strftime("%H:%M:%S")))

    def open_platform(self):
        w = PlatformWindow(self.symbol, self.interval, self.ctx.settings.get("platform") or
                           "tradingview", self.meta.get("exchangeName"), self)
        w.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        w.destroyed.connect(lambda *_: self._platforms.remove(w) if w in self._platforms else None)
        self._platforms.append(w)
        w.show()

    def _search(self):
        text = self.sym_box.text().strip()
        if not text:
            return
        self.note.setText("“%s” aranıyor…" % text)
        run_async(self.ctx.data.search, text, done=self._search_done,
                  failed=lambda m: self.note.setText("Arama başarısız: %s" % m))

    def _search_done(self, hits):
        if not hits:
            self.note.setText("Sonuç yok")
            return
        menu = QtWidgets.QMenu(self)
        for h in hits:
            act = menu.addAction("%s  —  %s  (%s, %s)" % (h["symbol"], h["name"][:40],
                                                         h["exchange"], h["type"]))
            act.triggered.connect(lambda _=False, s=h["symbol"]: self.load_symbol(s))
        menu.exec(self.sym_box.mapToGlobal(QtCore.QPoint(0, self.sym_box.height())))
        self.note.setText("")

    def _save_png(self):
        name = "%s_%s_%s.png" % (self.symbol.replace("^", ""), self.interval,
                                 dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Grafiği kaydet", name, "PNG (*.png)")
        if path:
            self.chart.grab_png(path)
            self.status.emit("Kaydedildi: %s" % path)


def _parse_ts(text):
    """Unix seconds from an ISO time; Alpaca's nanoseconds are cut to micro."""
    try:
        s = re.sub(r"(\.\d{6})\d+", r"\1", str(text).replace("Z", "+00:00"))
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return int(d.timestamp())
    except (ValueError, TypeError):
        return None
