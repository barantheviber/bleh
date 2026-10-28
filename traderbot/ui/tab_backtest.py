"""Backtest tab: run any strategy on fresh Yahoo history against SPY, read the
research report, and hand a strategy to the bot."""

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from .. import paths, strategies
from ..backtest import backtest_strategy, build_panel, run_backtest
from . import theme
from .tab_bot import _set_row, _table
from .workers import run_async

METRICS = [("cagr", "Yıllık getiri (CAGR)", "pct"), ("total_return", "Toplam getiri", "pct"),
           ("vol", "Oynaklık (yıllık)", "pct"), ("sharpe_excess", "Sharpe (BIL üstü)", "num"),
           ("sortino", "Sortino", "num"), ("max_dd", "En büyük düşüş", "pct"),
           ("calmar", "Calmar", "num"), ("exposure", "Piyasada kalma", "pct"),
           ("trades", "İşlem sayısı", "int"), ("round_trips", "Tam tur", "int"),
           ("win_rate", "Kazanan tur oranı", "pct"), ("turnover", "Yıllık devir", "num")]


SYMBOL_PARAMS = {"symbol", "off", "safe", "cash", "trend_symbol"}


class ParamForm(QtWidgets.QWidget):
    """Edits a strategy's params dict; values come back typed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.form = QtWidgets.QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.fields = {}
        self.defaults = {}

    def set_params(self, params):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields, self.defaults = {}, dict(params)
        for k, v in params.items():
            if isinstance(v, bool):
                w = QtWidgets.QCheckBox()
                w.setChecked(v)
            elif isinstance(v, int):
                w = QtWidgets.QSpinBox()
                w.setRange(1, 5000)
                w.setValue(v)
            elif isinstance(v, float):
                w = QtWidgets.QDoubleSpinBox()
                w.setRange(0.0, 1000.0)
                w.setDecimals(3)
                w.setSingleStep(0.01)
                w.setValue(v)
            elif isinstance(v, dict):
                w = QtWidgets.QLineEdit(", ".join("%s=%g" % (s, x * (100 if sum(v.values()) <= 1.0001 else 1))
                                                  for s, x in v.items()))
                w.setToolTip("SEMBOL=ağırlık, virgülle: SPY=60, AGG=40")
            elif isinstance(v, (list, tuple)):
                w = QtWidgets.QLineEdit(", ".join(str(x) for x in v))
            else:
                w = QtWidgets.QLineEdit(str(v))
            self.fields[k] = w
            self.form.addRow(k, w)

    def values(self):
        out = {}
        for k, w in self.fields.items():
            d = self.defaults[k]
            if isinstance(d, bool):
                out[k] = w.isChecked()
            elif isinstance(d, int):
                out[k] = int(w.value())
            elif isinstance(d, float):
                out[k] = float(w.value())
            elif isinstance(d, dict):
                weights = {}
                for part in w.text().split(","):
                    if "=" in part:
                        s, x = part.split("=", 1)
                        weights[s.strip().upper()] = float(x)
                tot = sum(weights.values()) or 1.0
                out[k] = {s: x / tot for s, x in weights.items()}
            elif isinstance(d, (list, tuple)):
                out[k] = [x.strip().upper() for x in w.text().split(",") if x.strip()]
            elif k in SYMBOL_PARAMS:
                out[k] = w.text().strip().upper()
            else:
                out[k] = w.text().strip()
        return out


class BacktestTab(QtWidgets.QWidget):
    status = QtCore.Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.result = None

        self.combo = QtWidgets.QComboBox()
        for key, cls in strategies.REGISTRY.items():
            self.combo.addItem(cls.name, key)
        self.summary = theme.label("", "muted", wrap=True)
        self.params = ParamForm()
        self.start = QtWidgets.QDateEdit(QtCore.QDate(2005, 1, 3))
        self.end = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        for d in (self.start, self.end):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd.MM.yyyy")
        self.capital = QtWidgets.QDoubleSpinBox()
        self.capital.setRange(100, 1e9)
        self.capital.setDecimals(0)
        self.capital.setValue(10000)
        self.capital.setPrefix("$ ")
        self.cost = QtWidgets.QDoubleSpinBox()
        self.cost.setRange(0, 100)
        self.cost.setValue(5)
        self.cost.setSuffix(" bp")
        self.band = QtWidgets.QDoubleSpinBox()
        self.band.setRange(0, 50)
        self.band.setValue(5)
        self.band.setSuffix(" puan")
        self.log_scale = QtWidgets.QCheckBox("Logaritmik eksen")
        self.log_scale.toggled.connect(lambda on: self.eq_plot.setLogMode(y=on))
        run = theme.button("Backtest çalıştır", "primary")
        run.clicked.connect(self.run)
        self.apply_btn = theme.button("Bu stratejiyi bota uygula", "good")
        self.apply_btn.clicked.connect(self.apply_to_bot)
        report = theme.button("Araştırma raporu")
        report.clicked.connect(self.show_report)

        form = QtWidgets.QFormLayout()
        form.addRow("Strateji", self.combo)
        form.addRow(self.summary)
        form.addRow(theme.label("Parametreler", "muted"))
        form.addRow(self.params)
        form.addRow("Başlangıç", self.start)
        form.addRow("Bitiş", self.end)
        form.addRow("Sermaye", self.capital)
        form.addRow("İşlem maliyeti", self.cost)
        form.addRow("Dengeleme bandı", self.band)
        form.addRow(self.log_scale)
        side = QtWidgets.QWidget()
        sl = QtWidgets.QVBoxLayout(side)
        sl.addLayout(form)
        sl.addWidget(run)
        sl.addWidget(self.apply_btn)
        sl.addWidget(report)
        sl.addStretch(1)
        sl.addWidget(theme.label("Geçmiş getiri geleceği garanti etmez. Emirler ertesi günün "
                                 "açılışında dolar; temettüler dahil, vergiler hariç.", "muted",
                                 wrap=True))
        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(330)

        self.eq_plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self.eq_plot.addLegend(offset=(10, 10))
        self.eq_plot.showGrid(x=True, y=True, alpha=0.15)
        self.eq_strat = self.eq_plot.plot(pen=pg.mkPen(theme.ACCENT, width=2), name="Strateji")
        self.eq_bench = self.eq_plot.plot(pen=pg.mkPen(theme.MUTED, width=1.5), name="SPY al-tut")
        self.dd_plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self.dd_plot.showGrid(x=True, y=True, alpha=0.15)
        self.dd_plot.setXLink(self.eq_plot)
        self.dd_strat = self.dd_plot.plot(pen=pg.mkPen(theme.DOWN, width=1.5), fillLevel=0,
                                          brush=pg.mkBrush(239, 83, 80, 50))
        self.dd_bench = self.dd_plot.plot(pen=pg.mkPen(theme.MUTED, width=1))
        self.metrics = _table(["Ölçü", "Strateji", "SPY al-tut"], stretch=0)
        self.metrics.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.yearly = _table(["Yıl", "Strateji", "SPY"])
        self.yearly.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.trades = _table(["Tarih", "Sembol", "Yön", "Adet", "Fiyat", "Tutar"])
        self.trades.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self.metrics, "Ölçüler")
        tabs.addTab(self.yearly, "Yıllık")
        tabs.addTab(self.trades, "İşlemler")
        charts = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        charts.addWidget(self.eq_plot)
        charts.addWidget(self.dd_plot)
        charts.addWidget(tabs)
        charts.setSizes([380, 150, 260])
        split = QtWidgets.QSplitter()
        split.addWidget(scroll)
        split.addWidget(charts)
        split.setSizes([340, 1000])
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(split)
        self.combo.currentIndexChanged.connect(self._strategy_changed)
        spec = ctx.settings.get("strategy") or {}
        self.combo.setCurrentIndex(max(0, self.combo.findData(spec.get("key"))))
        self._strategy_changed()
        if spec.get("params"):
            p = dict(strategies.REGISTRY[spec["key"]].params)
            p.update(spec["params"])
            self.params.set_params(p)

    def _strategy_changed(self, *_):
        cls = strategies.REGISTRY[self.combo.currentData()]
        self.summary.setText(cls.summary)
        self.params.set_params(cls.params)

    def strategy(self):
        return strategies.create(self.combo.currentData(), **self.params.values())

    def run(self):
        try:
            strat = self.strategy()
        except (ValueError, TypeError) as exc:
            QtWidgets.QMessageBox.warning(self, "Parametre", str(exc))
            return
        start = self.start.date().toString("yyyy-MM-dd")
        end = self.end.date().toString("yyyy-MM-dd")
        kw = dict(capital=self.capital.value(), cost_bps=self.cost.value(),
                  band=self.band.value() / 100.0)
        self.status.emit("Backtest: %s verisi indiriliyor…" % ", ".join(strat.inputs()))
        run_async(self._compute, strat, start, end, kw, done=self._done,
                  failed=lambda m: (self.status.emit("Backtest başarısız: %s" % m),
                                    QtWidgets.QMessageBox.warning(self, "Backtest", m)))

    def _compute(self, strat, start, end, kw):
        syms = list(dict.fromkeys(list(strat.inputs()) + ["SPY", "BIL"]))
        bars = self.ctx.data.daily(syms, range_="max")
        cal = "SPY"
        panel = build_panel(bars, calendar_symbol=cal)
        res = backtest_strategy(strat, panel, start, end, **kw)
        ones = np.ones((len(panel), 1))
        bench = run_backtest(panel, np.where(np.isfinite(panel.close("SPY"))[:, None], ones, np.nan),
                             ["SPY"], start, end, **kw)
        bil = panel.close("BIL")
        rf = np.concatenate([[np.nan], bil[1:] / bil[:-1] - 1.0])
        return strat, res, bench, res.metrics(rf), bench.metrics(rf)

    def _done(self, out):
        strat, res, bench, m, mb = out
        self.result = out
        d, eq = res.window()
        _, eqb = bench.window()
        xs = np.array([np.datetime64(x, "s").astype("int64") for x in d], dtype=float)
        ok = np.isfinite(eq)
        self.eq_strat.setData(xs[ok], eq[ok])
        self.eq_bench.setData(xs[ok], eqb[ok])
        self.eq_plot.getPlotItem().legend.items[0][1].setText(strat.name)
        for curve, series in ((self.dd_strat, eq), (self.dd_bench, eqb)):
            s = series[ok]
            curve.setData(xs[ok], 100 * (s / np.maximum.accumulate(s) - 1))
        self.eq_plot.autoRange()
        self.metrics.setRowCount(len(METRICS) + 2)
        _set_row(self.metrics, 0, ["Dönem", "%s – %s" % (m["start"], m["end"]), ""])
        _set_row(self.metrics, 1, ["Bitiş varlığı", "${:,.0f}".format(eq[ok][-1]),
                                   "${:,.0f}".format(eqb[ok][-1])])
        for r, (key, name, kind) in enumerate(METRICS, start=2):
            a, b = m.get(key), mb.get(key)
            colors = {}
            if kind == "pct" and key in ("cagr", "total_return"):
                colors = {1: theme.color_for(a), 2: theme.color_for(b)}
            _set_row(self.metrics, r, [name, _f(a, kind), _f(b, kind)], colors)
        years = sorted(set(m.get("yearly", {})) | set(mb.get("yearly", {})))
        self.yearly.setRowCount(len(years))
        for r, y in enumerate(years):
            a, b = m["yearly"].get(y), mb["yearly"].get(y)
            _set_row(self.yearly, r, [y, _f(a, "pct"), _f(b, "pct")],
                     {1: theme.color_for(a), 2: theme.color_for(b)})
        trades = res.trades[-1000:][::-1]
        self.trades.setRowCount(len(trades))
        for r, t in enumerate(trades):
            _set_row(self.trades, r, [t.date, t.symbol, "AL" if t.side == "buy" else "SAT",
                                      "%.4f" % t.qty, "%.2f" % t.price, "${:,.2f}".format(t.value)],
                     {2: theme.UP if t.side == "buy" else theme.DOWN})
        self.status.emit("Backtest bitti: %s, yıllık %s, en büyük düşüş %s" % (
            strat.name, _f(m["cagr"], "pct"), _f(m["max_dd"], "pct")))

    def apply_to_bot(self):
        try:
            strat = self.strategy()
        except (ValueError, TypeError) as exc:
            QtWidgets.QMessageBox.warning(self, "Parametre", str(exc))
            return
        if QtWidgets.QMessageBox.question(
                self, "Bota uygula", "Bot bundan sonra '%s' stratejisini kullanacak. Mevcut "
                "pozisyonlar bir sonraki kararda yeni hedeflere göre dengelenir. Devam?" % strat.name) \
                != QtWidgets.QMessageBox.Yes:
            return
        self.ctx.settings.set("strategy", {"key": strat.key, "params": strat.p})
        self.ctx.settings_changed.emit()
        self.status.emit("Bot stratejisi: %s" % strat.label())

    def show_report(self):
        path = paths.resource("research", "REPORT.md")
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            text = "Rapor bulunamadı: %s" % path
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Strateji araştırması")
        dlg.resize(980, 760)
        view = QtWidgets.QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setMarkdown(text)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addWidget(view)
        dlg.show()


def _f(v, kind):
    if v is None:
        return "—"
    if kind == "pct":
        return "%+.2f%%" % (100 * v)
    if kind == "int":
        return "%d" % v
    return "%.2f" % v
