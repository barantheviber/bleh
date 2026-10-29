"""Piyasa tab: today's market regime on indicators with research behind them,
what followed each state in the past, and the coming market calendar."""

import time

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from .. import events, market_clock, regime
from . import theme
from .tab_bot import _set_row, _table
from .workers import run_async

DAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
KIND_COLORS = {"fomc": theme.ACCENT, "holiday": theme.DOWN, "early": theme.WARN,
               "tom": theme.UP}
STALE_SECONDS = 15 * 60
PERCENT_KEYS = {"trend", "momentum", "volatility", "credit", "breadth"}


def format_value(key, v):
    if v is None or not np.isfinite(v):
        return "—"
    if key in ("volatility", "breadth"):
        return "%.0f%%" % (100 * v) if key == "breadth" else "%.1f%%" % (100 * v)
    if key in PERCENT_KEYS:
        return ("%+.1f%%" % (100 * v)).replace("+-", "-")
    if key == "curve":
        return ("%+.2f puan" % v).replace("+-", "-")
    if key == "vix_term":
        return "%.2f" % v
    return "%.1f" % v


def state_color(row):
    if row["risk_on"]:
        return theme.UP
    if row["risk_off"]:
        return theme.DOWN
    return theme.WARN if row["state"] >= 0 else theme.MUTED


class IndicatorCard(QtWidgets.QFrame):
    def __init__(self, it):
        super().__init__()
        self.key = it.key
        self.setObjectName("card")
        self.setStyleSheet("QFrame#card { background: %s; border: 1px solid %s; border-radius: 6px; }"
                           "QLabel { background: transparent; }" % (theme.PANEL, theme.BORDER))
        title = theme.label(it.name, wrap=True)
        title.setStyleSheet("font-weight: 600;")
        self.value = theme.label("—", "big")
        self.state = theme.label("yükleniyor…", "muted")
        self.extra = theme.label("", wrap=True)
        about = theme.label(it.about, "muted", wrap=True)
        source = theme.label("Kaynak: %s" % it.source, "muted", wrap=True)
        source.setStyleSheet("font-size: 8pt;")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.value)
        top.addStretch(1)
        top.addWidget(self.state)
        lay.addWidget(title)
        lay.addLayout(top)
        lay.addWidget(self.extra)
        lay.addWidget(about)
        lay.addWidget(source)
        self.extra.hide()

    def set_row(self, row):
        self.value.setText(format_value(row["key"], row["value"]))
        self.state.setText(row["label"])
        self.state.setStyleSheet("color: %s; font-weight: 600;" % state_color(row))
        p = row.get("recession_probability")
        if p is not None:
            self.extra.setText("NY Fed modeli: 12 ay içinde ABD'de resesyon olasılığı %%%.0f "
                               "(günlük veriyle yaklaşık)." % (100 * p))
            self.extra.show()
        self.setToolTip("Son veri: %s" % (row["date"] or "yok"))


class MarketTab(QtWidgets.QWidget):
    status = QtCore.Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.out = None
        self.loaded_at = None
        self.busy = False

        self.verdict = theme.label("Piyasa durumu: yükleniyor…", "title")
        self.sub = theme.label("Sekme açılınca göstergeler Yahoo Finance'ten indirilir.", "muted",
                               wrap=True)
        refresh = theme.button("Yenile", tip="Göstergeleri yeniden indir")
        refresh.clicked.connect(lambda: self.refresh(force=True))
        head = QtWidgets.QHBoxLayout()
        txt = QtWidgets.QVBoxLayout()
        txt.addWidget(self.verdict)
        txt.addWidget(self.sub)
        head.addLayout(txt, 1)
        head.addWidget(refresh, 0, QtCore.Qt.AlignTop)

        self.cards = {it.key: IndicatorCard(it) for it in regime.INDICATORS}
        grid_w = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(grid_w)
        grid.setContentsMargins(0, 0, 4, 0)
        for i, it in enumerate(regime.INDICATORS):
            grid.addWidget(self.cards[it.key], i // 2, i % 2)
        cards = QtWidgets.QScrollArea()
        cards.setWidget(grid_w)
        cards.setWidgetResizable(True)

        self.events = _table(["Tarih", "Olay"], stretch=1)
        self.events.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.combo = QtWidgets.QComboBox()
        for it in regime.INDICATORS:
            self.combo.addItem(it.name, it.key)
        self.combo.currentIndexChanged.connect(self._plot)
        self.plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.curve = self.plot.plot(pen=pg.mkPen(theme.ACCENT, width=1.5))
        self.lines = []
        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(4, 0, 0, 0)
        rl.addWidget(theme.label("Yaklaşan olaylar (60 gün)", "muted"))
        rl.addWidget(self.events, 3)
        rl.addWidget(theme.label("Gösterge geçmişi (5 yıl, kesikli çizgiler: durum sınırları)",
                                 "muted"))
        rl.addWidget(self.combo)
        rl.addWidget(self.plot, 4)

        top = QtWidgets.QSplitter()
        top.addWidget(cards)
        top.addWidget(right)
        top.setSizes([820, 520])

        self.history = _table(["Gösterge", "Şu anki durum", "Bu durumdaki günler",
                               "Sonraki 1 ay ort.", "Yükselen ay", "Kötü ay (%5)",
                               "Sonraki oynaklık"], stretch=0)
        self.history.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        all_btn = theme.button("Tüm durumların tablosu")
        all_btn.clicked.connect(self.show_history)
        bottom = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(bottom)
        bl.setContentsMargins(0, 4, 0, 0)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(theme.label("Geçmişte bu durumlardan sonraki 21 işlem günü (SPY)", "muted"))
        row.addStretch(1)
        row.addWidget(all_btn)
        bl.addLayout(row)
        bl.addWidget(self.history)
        bl.addWidget(theme.label(
            "Araştırma ve bu tablo aynı şeyi söyler: rejimler sonraki ayın oynaklığını getirisinden "
            "çok daha iyi öngörür. Kötü rejimlerde ortalama getiri düşmez ama kötü aylar derinleşir. "
            "Bu yüzden bot piyasayı zamanlamaya değil, oynaklığa göre pozisyon küçültmeye dayanır. "
            "Bu sayfa bir alım-satım sinyali değildir.", "muted", wrap=True))

        split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        split.addWidget(top)
        split.addWidget(bottom)
        split.setSizes([560, 260])
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addLayout(head)
        lay.addWidget(split, 1)

    # ------------------------------------------------------------ loading

    def showEvent(self, event):
        super().showEvent(event)
        if self.loaded_at is None or time.monotonic() - self.loaded_at > STALE_SECONDS:
            self.refresh()

    def refresh(self, force=False):
        if self.busy:
            return
        self.busy = True
        self.status.emit("Piyasa göstergeleri indiriliyor…")
        run_async(self._compute, done=self._done, failed=self._failed)

    def _compute(self):
        panel, missing = regime.load_panel(self.ctx.data)
        res = regime.evaluate(panel)
        today = market_clock.status()["ny"].date()
        return {"panel": panel, "results": res, "snapshot": regime.snapshot(panel, res),
                "history": regime.conditional_stats(panel, res, horizon=21),
                "events": events.upcoming(today, 60), "missing": missing}

    def _failed(self, msg):
        self.busy = False
        self.verdict.setText("Piyasa durumu alınamadı")
        self.sub.setText(msg)
        self.status.emit("Piyasa verisi alınamadı: %s" % msg)

    def _done(self, out):
        self.busy = False
        self.out = out
        self.loaded_at = time.monotonic()
        snap = out["snapshot"]
        for row in snap["rows"]:
            self.cards[row["key"]].set_row(row)
        color = {"Risk iştahı yüksek": theme.UP, "Karışık": theme.WARN,
                 "Temkinli": theme.DOWN}.get(snap["verdict"], theme.MUTED)
        self.verdict.setText("Piyasa durumu: <span style='color:%s'>%s</span>" % (
            color, snap["verdict"]))
        last = str(out["panel"].dates[-1])
        bits = ["%d/%d gösterge risk iştahı tarafında" % (snap["risk_on"], snap["available"]),
                "son bar %s" % last]
        if out["missing"]:
            bits.append("alınamayan: %s" % ", ".join(out["missing"]))
        self.sub.setText(" · ".join(bits) + ". Özet, kanıtı olan göstergelerin durumunu sayar; "
                         "tek başına al ya da sat demek değildir.")
        self._fill_events(out["events"])
        self._fill_history(out)
        self._plot()
        self.status.emit("Piyasa durumu güncellendi: %s" % snap["verdict"])

    # ------------------------------------------------------------ views

    def _fill_events(self, evs):
        self.events.setRowCount(len(evs))
        for r, e in enumerate(evs):
            d = e["date"]
            _set_row(self.events, r, ["%s %s" % (d.strftime("%d.%m.%Y"), DAYS[d.weekday()]),
                                      e["title"]], {1: KIND_COLORS.get(e["kind"])})
            for c in range(2):
                self.events.item(r, c).setToolTip(e["note"])
            self.events.item(r, 1).setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

    def _fill_history(self, out):
        now = {row["key"]: row for row in out["snapshot"]["rows"]}
        inds = out["history"]["indicators"]
        self.history.setRowCount(len(inds))
        for r, it in enumerate(inds):
            row = now.get(it["key"])
            st = row["state"] if row else -1
            stats = next((x["stats"] for x in it["rows"] if x["state"] == st), None)
            if stats is None:
                _set_row(self.history, r, [it["short"], row["label"] if row else "—", "—", "—",
                                           "—", "—", "—"])
                continue
            _set_row(self.history, r, [
                it["short"], row["label"], "%.0f%%" % (100 * stats["share"]),
                regime._pct(stats["mean"], 2), "%.0f%%" % (100 * stats["up"]),
                regime._pct(stats["p5"]), "%.1f%%" % (100 * stats["vol"])],
                {1: state_color(row), 3: theme.color_for(stats["mean"]), 5: theme.DOWN})

    def _plot(self, *_):
        for ln in self.lines:
            self.plot.removeItem(ln)
        self.lines = []
        if not self.out:
            return
        key = self.combo.currentData()
        res = self.out["results"].get(key)
        if res is None:
            self.curve.setData([], [])
            return
        it = next(i for i in regime.INDICATORS if i.key == key)
        dates = self.out["panel"].dates
        keep = dates >= dates[-1] - np.timedelta64(5 * 365, "D")
        scale = 100.0 if key in PERCENT_KEYS else 1.0
        xs = dates[keep].astype("datetime64[s]").astype("int64").astype(float)
        ys = res["values"][keep] * scale
        ok = np.isfinite(ys)
        self.curve.setData(xs[ok], ys[ok])
        for e in it.edges:
            ln = pg.InfiniteLine(pos=e * scale, angle=0,
                                 pen=pg.mkPen(theme.MUTED, width=1, style=QtCore.Qt.DashLine))
            self.plot.addItem(ln)
            self.lines.append(ln)
        self.plot.autoRange()

    def show_history(self):
        if not self.out:
            return
        text = ("# Piyasa rejimleri: sonraki 21 işlem gününde SPY\n\n"
                "Pencereler çakıştığı için gün sayıları bağımsız gözlem sayısını abartır; küçük "
                "farklar tesadüf olabilir. Araştırma raporundaki aynı tablo 2005'ten başlar; "
                "buradaki, Yahoo'nun verdiği en eski veriden.\n\n" +
                regime.history_markdown(self.out["history"]))
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Piyasa rejimleri: geçmiş")
        dlg.resize(900, 720)
        view = QtWidgets.QTextBrowser()
        view.setMarkdown(text)
        QtWidgets.QVBoxLayout(dlg).addWidget(view)
        dlg.show()
