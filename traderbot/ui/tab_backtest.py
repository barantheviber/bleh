"""Backtest tab: run any strategy on fresh Yahoo history against SPY, check how
far the result can be trusted (risk, reliability, Monte Carlo, walk-forward),
read the research report, and hand a strategy to the bot."""

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .. import analysis, paths, strategies
from ..backtest import backtest_strategy, build_panel, run_backtest
from . import theme
from .tab_bot import _set_row, _table
from .workers import run_async

METRICS = [("cagr", "Yıllık getiri (CAGR)", "pct"), ("total_return", "Toplam getiri", "pct"),
           ("vol", "Oynaklık (yıllık)", "pct"), ("sharpe_excess", "Sharpe (BIL üstü)", "num"),
           ("sortino", "Sortino", "num"), ("max_dd", "En büyük düşüş", "pct"),
           ("calmar", "Calmar", "num"), ("exposure", "Piyasada kalma", "pct"),
           ("trades", "İşlem sayısı", "int"), ("round_trips", "Tam tur", "int"),
           ("win_rate", "Kazanan tur oranı", "pct"), ("payoff", "Ort. kazanç / ort. kayıp", "num"),
           ("profit_factor", "Kâr faktörü", "num"), ("turnover", "Yıllık devir", "num")]
RISK_ROWS = [("var95", "Günlük VaR (%95)", "pct"), ("var99", "Günlük VaR (%99)", "pct"),
             ("es975", "Beklenen kayıp (ES %97.5)", "pct"), ("worst_day", "En kötü gün", "pct"),
             ("worst_week", "En kötü hafta", "pct"), ("worst_month", "En kötü ay", "pct"),
             ("worst_year", "En kötü 12 ay", "pct"), ("skew", "Çarpıklık", "num"),
             ("excess_kurtosis", "Fazla basıklık (kalın kuyruk)", "num"),
             ("ulcer", "Ülser endeksi", "num"), ("underwater", "Zirvenin altında geçen süre", "share"),
             ("longest_dd_days", "En uzun toparlanma (gün)", "int"),
             ("up_days", "Yükselen gün oranı", "share"), ("up_months", "Yükselen ay oranı", "share"),
             ("beta", "Beta (SPY'a göre)", "num"), ("correlation", "Korelasyon (SPY)", "num"),
             ("downside_capture", "SPY'ın kötü günlerinden alınan pay", "share")]
MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
SYMBOL_PARAMS = {"symbol", "off", "safe", "cash", "trend_symbol"}
MC_MAX_CELLS = 10_000_000          # paths x days, keeps memory around 200 MB


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
                if k == "parts":
                    w.setToolTip("strateji_anahtarı=pay, virgülle: vol_target=50, gtaa=50\n"
                                 "Anahtarlar: %s" % ", ".join(
                                     s for s in strategies.REGISTRY
                                     if s not in ("ensemble", "fixed_weights")))
                else:
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


def _spin(lo, hi, val):
    w = QtWidgets.QSpinBox()
    w.setRange(lo, hi)
    w.setValue(val)
    return w


class BacktestTab(QtWidgets.QWidget):
    status = QtCore.Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.result = None
        self.trials = {}               # strategy label -> daily excess Sharpe, this session

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
        self.risk = _table(["Ölçü", "Strateji", "SPY al-tut"], stretch=0)
        self.risk.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.monthly = _table(["Yıl"] + MONTHS + ["Yıllık"], stretch=0)
        self.monthly.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self.metrics, "Ölçüler")
        self.tabs.addTab(self.yearly, "Yıllık")
        self.tabs.addTab(self.monthly, "Aylık")
        self.tabs.addTab(self._risk_page(), "Risk")
        self.tabs.addTab(self._reliability_page(), "Güvenilirlik")
        self.tabs.addTab(self._mc_page(), "Monte Carlo")
        self.tabs.addTab(self._wf_page(), "İleri yürüyüş")
        self.tabs.addTab(self.trades, "İşlemler")
        charts = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        charts.addWidget(self.eq_plot)
        charts.addWidget(self.dd_plot)
        charts.addWidget(self.tabs)
        charts.setSizes([330, 120, 400])
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

    # ------------------------------------------------------------ pages

    def _risk_page(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.risk, 1)
        lay.addWidget(theme.label(
            "VaR: 100 günün 95'inde (99'unda) günlük kayıp bundan küçük kaldı. Beklenen kayıp (ES): "
            "en kötü %2.5'lik günlerin ortalaması; Basel kuralları VaR yerine bunu kullanır. Ülser "
            "endeksi düşüşlerin hem derinliğini hem süresini ölçer (Martin 1987).", "muted",
            wrap=True))
        return w

    def _reliability_page(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.reliability = QtWidgets.QTextBrowser()
        self.reliability.setOpenExternalLinks(False)
        self.reliability.setHtml("<p style='color:%s'>Önce bir backtest çalıştırın.</p>" % theme.MUTED)
        reset = theme.button("Denemeleri sıfırla", tip="Bu oturumda denenen ayar sayısını sıfırla")
        reset.clicked.connect(self._reset_trials)
        row = QtWidgets.QHBoxLayout()
        self.trial_label = theme.label("Bu oturumda denenen farklı ayar: 0", "muted")
        row.addWidget(self.trial_label)
        row.addStretch(1)
        row.addWidget(reset)
        lay.addWidget(self.reliability, 1)
        lay.addLayout(row)
        return w

    def _mc_page(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.mc_years = _spin(1, 20, 5)
        self.mc_years.setSuffix(" yıl")
        self.mc_paths = QtWidgets.QComboBox()
        for n in (1000, 2000, 5000):
            self.mc_paths.addItem("%d yol" % n, n)
        self.mc_paths.setCurrentIndex(1)
        self.mc_block = _spin(1, 252, 21)
        self.mc_block.setSuffix(" gün blok")
        self.mc_btn = theme.button("Monte Carlo çalıştır", "primary")
        self.mc_btn.setEnabled(False)
        self.mc_btn.clicked.connect(self.run_monte_carlo)
        bar = QtWidgets.QHBoxLayout()
        for x in (theme.label("Ufuk"), self.mc_years, self.mc_paths, self.mc_block, self.mc_btn):
            bar.addWidget(x)
        bar.addStretch(1)
        self.mc_plot = pg.PlotWidget()
        self.mc_plot.showGrid(x=True, y=True, alpha=0.15)
        self.mc_plot.setLabel("bottom", "yıl")
        self.mc_items = []
        self.mc_table = _table(["", "Yıllık getiri: kötü (%5)", "orta", "iyi (%95)",
                                "En büyük düşüş: orta", "kötü (%5)", "Zararla bitirme",
                                "%20+ düşüş"], stretch=0)
        self.mc_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.mc_table.setMaximumHeight(100)
        lay.addLayout(bar)
        lay.addWidget(self.mc_plot, 1)
        lay.addWidget(self.mc_table)
        lay.addWidget(theme.label(
            "Geçmiş günlük getiriler, ortalama blok uzunluğunda parçalar halinde rastgele yeniden "
            "dizilir (durağan blok bootstrap, Politis ve Romano 1994). Koyu bant yolların ortadaki "
            "%50'si, açık bant %90'ı; kesikli çizgi SPY'ın ortası. Geçmişte görülmemiş bir kriz bu "
            "aralığın dışına çıkabilir.", "muted", wrap=True))
        return w

    def _wf_page(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.wf_train = _spin(2, 15, 5)
        self.wf_train.setSuffix(" yıl eğitim")
        self.wf_test = _spin(1, 5, 1)
        self.wf_test.setSuffix(" yıl test")
        self.wf_anchored = QtWidgets.QCheckBox("Genişleyen pencere")
        self.wf_anchored.setToolTip("İşaretliyse eğitim hep başlangıçtan başlar; değilse sabit "
                                    "uzunlukta kayan bir penceredir")
        self.wf_btn = theme.button("İleri yürüyüş testi", "primary")
        self.wf_btn.setEnabled(False)
        self.wf_btn.clicked.connect(self.run_walk_forward)
        bar = QtWidgets.QHBoxLayout()
        for x in (self.wf_train, self.wf_test, self.wf_anchored, self.wf_btn):
            bar.addWidget(x)
        bar.addStretch(1)
        self.wf_info = theme.label("", "muted", wrap=True)
        self.wf_table = _table(["Test dönemi", "Seçilen parametre", "Eğitim Sharpe",
                                "Test getirisi", "Test Sharpe", "Test en büyük düşüş"], stretch=1)
        self.wf_plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self.wf_plot.addLegend(offset=(10, 10))
        self.wf_plot.showGrid(x=True, y=True, alpha=0.15)
        self.wf_curve = self.wf_plot.plot(pen=pg.mkPen(theme.ACCENT, width=2), name="İleri yürüyüş")
        self.wf_spy = self.wf_plot.plot(pen=pg.mkPen(theme.MUTED, width=1.5), name="SPY al-tut")
        inner = QtWidgets.QSplitter()
        hdr = self.wf_table.horizontalHeader()
        hdr.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        inner.addWidget(self.wf_table)
        inner.addWidget(self.wf_plot)
        inner.setSizes([640, 380])
        lay.addLayout(bar)
        lay.addWidget(self.wf_info)
        lay.addWidget(inner, 1)
        return w

    # ------------------------------------------------------------ running

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
        trials = [v for k, v in self.trials.items() if k != strat.label()]
        self.status.emit("Backtest: %s verisi indiriliyor…" % ", ".join(strat.inputs()))
        run_async(self._compute, strat, start, end, kw, trials, done=self._done,
                  failed=lambda m: (self.status.emit("Backtest başarısız: %s" % m),
                                    QtWidgets.QMessageBox.warning(self, "Backtest", m)))

    def _compute(self, strat, start, end, kw, trials):
        syms = list(dict.fromkeys(list(strat.inputs()) + ["SPY", "BIL"]))
        bars = self.ctx.data.daily(syms, range_="max")
        panel = build_panel(bars, calendar_symbol="SPY")
        res = backtest_strategy(strat, panel, start, end, **kw)
        ones = np.ones((len(panel), 1))
        bench = run_backtest(panel, np.where(np.isfinite(panel.close("SPY"))[:, None], ones, np.nan),
                             ["SPY"], start, end, **kw)
        bil = panel.close("BIL")
        rf = np.concatenate([[np.nan], bil[1:] / bil[:-1] - 1.0])
        d, eq = res.window()
        _, eqb = bench.window()
        rfw = rf[res.start:res.end + 1]
        ex = analysis.excess_returns(eq, rfw)
        exb = analysis.excess_returns(eqb, rfw)
        sr = analysis.moments(ex)[0]
        dsr, sr0 = analysis.deflated_sharpe(ex, list(trials) + [sr])
        rel = {"sr": sr, "psr": analysis.probabilistic_sharpe(ex), "dsr": dsr, "sr0": sr0,
               "n": len(trials) + 1, "years": len(ex) / 252.0,
               "min_trl": analysis.min_track_record(ex) / 252.0,
               "sr_bench": analysis.moments(exb)[0], "psr_bench": analysis.probabilistic_sharpe(exb)}
        return {"strategy": strat, "res": res, "bench": bench, "m": res.metrics(rf),
                "mb": bench.metrics(rf), "panel": panel, "rf": rf, "kw": kw,
                "start": start, "end": end, "reliability": rel,
                "risk": analysis.risk_report(eq, d, bench_equity=eqb),
                "risk_bench": analysis.risk_report(eqb, d),
                "monthly": analysis.monthly_returns(eq, d)}

    def _done(self, out):
        self.result = out
        strat, res, bench, m, mb = out["strategy"], out["res"], out["bench"], out["m"], out["mb"]
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
        self.trials[strat.label()] = out["reliability"]["sr"]
        self._show_risk(out)
        self._show_monthly(out["monthly"])
        self._show_reliability(out)
        self.mc_btn.setEnabled(True)
        grid = strategies.RESEARCH_GRID.get(strat.key)
        self.wf_btn.setEnabled(bool(grid))
        self.wf_info.setText(
            "Her test döneminin başında parametre, önceki eğitim döneminde en iyi Sharpe'ı veren "
            "ayardan seçilir; araştırma ızgarası: %d ayar. Ekrandaki diğer parametreler "
            "varsayılanlarına döner." % len(grid) if grid else
            "Bu strateji için parametre ızgarası yok; ileri yürüyüş yapılamaz.")
        for item in self.mc_items:
            self.mc_plot.removeItem(item)
        self.mc_items = []
        self.mc_table.setRowCount(0)
        self.status.emit("Backtest bitti: %s, yıllık %s, en büyük düşüş %s" % (
            strat.name, _f(m["cagr"], "pct"), _f(m["max_dd"], "pct")))

    # ------------------------------------------------------------ analytics views

    def _show_risk(self, out):
        a, b = out["risk"], out["risk_bench"]
        self.risk.setRowCount(len(RISK_ROWS))
        for r, (key, name, kind) in enumerate(RISK_ROWS):
            x, y = a.get(key), b.get(key)
            if key in ("beta", "correlation", "downside_capture"):
                y = None
            if key == "longest_dd_days" and x is not None:
                xs = "%d (%s → %s)" % (x, a.get("longest_dd_peak"),
                                       a.get("longest_dd_recovery") or "toparlanmadı")
                ys = "%d (%s → %s)" % (y, b.get("longest_dd_peak"),
                                       b.get("longest_dd_recovery") or "toparlanmadı") \
                    if y is not None else "—"
                _set_row(self.risk, r, [name, xs, ys])
                continue
            _set_row(self.risk, r, [name, _f(x, kind), _f(y, kind)])

    def _show_monthly(self, table):
        years = sorted(table)
        self.monthly.setRowCount(len(years))
        for r, y in enumerate(years):
            row = table[y]
            vals = row["months"] + [row["year"]]
            _set_row(self.monthly, r, [str(y)] + [_f(v, "pct1") for v in vals])
            for c, v in enumerate(vals, start=1):
                if v is None:
                    continue
                strength = min(1.0, abs(v) / (0.25 if c == 13 else 0.08))
                color = QtGui.QColor(theme.UP if v > 0 else theme.DOWN)
                color.setAlpha(int(25 + 110 * strength))
                self.monthly.item(r, c).setBackground(color)

    def _show_reliability(self, out):
        rel = out["reliability"]
        sr, sr0 = analysis.annual(rel["sr"]), analysis.annual(rel["sr0"])
        psr, dsr = rel["psr"], rel["dsr"]
        n = rel["n"]
        enough = rel["years"] >= rel["min_trl"]
        if dsr >= 0.95:
            verdict = ("<b style='color:%s'>Güçlü.</b> Sonuç, denenen ayar sayısı hesaba katılınca da "
                       "şansla açıklanamayacak kadar iyi. Yine de yayımlanan stratejilerin getirisi "
                       "yayından sonra ortalama %%58 düştü (McLean ve Pontiff 2016); beklentiyi "
                       "düşük tutun." % theme.UP)
        elif psr >= 0.95:
            verdict = ("<b style='color:%s'>Dikkat.</b> Tek başına anlamlı görünüyor ama %d farklı "
                       "ayar denediğiniz için en iyisinin şans olma ihtimali yüksek. Yeni ayar "
                       "denemeyi bırakın ve İleri yürüyüş sekmesine bakın." % (theme.WARN, n))
        elif psr >= 0.8:
            verdict = ("<b style='color:%s'>Zayıf.</b> Sharpe muhtemelen pozitif ama kanıt güçlü "
                       "değil; daha uzun bir dönem gerekir." % theme.WARN)
        else:
            verdict = ("<b style='color:%s'>Kanıt yok.</b> Bu sonuç şansla rahatça açıklanabilir."
                       % theme.DOWN)
        trl = ("%.1f yıl" % rel["min_trl"]) if np.isfinite(rel["min_trl"]) else "sonsuz (Sharpe ≤ 0)"
        rows = [
            ("Sharpe (BIL üstü, yıllık)", "%.2f" % sr, "SPY: %.2f" % analysis.annual(rel["sr_bench"])),
            ("Olasılıksal Sharpe (PSR)", _prob(psr),
             "gerçek Sharpe'ın sıfırdan büyük olma olasılığı · SPY: %s" % _prob(rel["psr_bench"])),
            ("Deflated Sharpe (DSR)", _prob(dsr),
             "bu oturumda denenen %d ayarın en şanslısının şans eseri alacağı Sharpe'a (%.2f) göre"
             % (n, sr0)),
            ("%95 güven için gereken geçmiş", trl,
             "bu testte %.1f yıl var%s" % (rel["years"], "" if enough else " · yetersiz")),
        ]
        cells = "".join("<tr><td style='padding:4px 12px 4px 0'><b>%s</b></td><td style='padding:4px "
                        "12px'>%s</td><td style='color:%s'>%s</td></tr>" % (a, b, theme.MUTED, c)
                        for a, b, c in rows)
        self.reliability.setHtml(
            "<h3>Bu sonuca ne kadar güvenebilirsiniz?</h3><table>%s</table><p>%s</p>"
            "<p style='color:%s'>Bir backtest'in Sharpe oranı iki nedenle gerçeğinden iyi görünür: "
            "geçmiş kısadır ve en iyi ayar çok sayıda deneme arasından seçilmiştir. PSR ilkini, DSR "
            "ikisini birden düzeltir (Bailey ve López de Prado 2012, 2014). Finans araştırmasında "
            "yeni bir bulgu için olağan t > 2 eşiği yerine t > 3 önerilir (Harvey, Liu ve Zhu 2016). "
            "Uygulamanın kendi stratejisi 65 ayar arasından seçildi; ayrıntı Araştırma raporunda.</p>"
            % (cells, verdict, theme.MUTED))
        self.trial_label.setText("Bu oturumda denenen farklı ayar: %d" % len(self.trials))

    def _reset_trials(self):
        self.trials = {}
        self.trial_label.setText("Bu oturumda denenen farklı ayar: 0")
        self.status.emit("Deneme sayacı sıfırlandı; sonraki backtest tek deneme sayılır")

    # ------------------------------------------------------------ Monte Carlo

    def run_monte_carlo(self):
        if not self.result:
            return
        years = self.mc_years.value()
        H = years * 252
        paths = min(int(self.mc_paths.currentData()), MC_MAX_CELLS // H)
        _, eq = self.result["res"].window()
        _, eqb = self.result["bench"].window()
        self.mc_btn.setEnabled(False)
        self.status.emit("Monte Carlo: %d yol × %d yıl…" % (paths, years))
        run_async(_monte_carlo, eq, eqb, H, paths, self.mc_block.value(), done=self._mc_done,
                  failed=lambda m: (self.mc_btn.setEnabled(True),
                                    self.status.emit("Monte Carlo başarısız: %s" % m)))

    def _mc_done(self, out):
        self.mc_btn.setEnabled(True)
        a, b = out
        for item in self.mc_items:
            self.mc_plot.removeItem(item)
        cap = float(self.result["kw"]["capital"])
        x = (np.arange(a["horizon"]) + 1) / 252.0
        fan = {p: a["fan"][p] * cap for p in a["percentiles"]}
        # band edges need real curves (a PlotDataItem without a pen hides its path)
        edge = pg.mkPen(0, 0, 0, 0)
        lo, hi = pg.PlotCurveItem(x, fan[5], pen=edge), pg.PlotCurveItem(x, fan[95], pen=edge)
        q1, q3 = pg.PlotCurveItem(x, fan[25], pen=edge), pg.PlotCurveItem(x, fan[75], pen=edge)
        wide = pg.FillBetweenItem(lo, hi, brush=pg.mkBrush(47, 129, 247, 40))
        mid = pg.FillBetweenItem(q1, q3, brush=pg.mkBrush(47, 129, 247, 80))
        med = pg.PlotDataItem(x, fan[50], pen=pg.mkPen(theme.ACCENT, width=2))
        spy = pg.PlotDataItem(x, b["fan"][50] * cap,
                              pen=pg.mkPen(theme.MUTED, width=1.5, style=QtCore.Qt.DashLine))
        self.mc_items = [lo, hi, q1, q3, wide, mid, med, spy]
        for item in self.mc_items:
            self.mc_plot.addItem(item)
        self.mc_plot.autoRange()
        self.mc_table.setRowCount(2)
        for r, (name, res) in enumerate(((self.result["strategy"].name, a), ("SPY al-tut", b))):
            c, d = res["cagr"], res["max_dd"]
            _set_row(self.mc_table, r, [name, _f(c[5], "pct"), _f(c[50], "pct"), _f(c[95], "pct"),
                                        _f(d[50], "pct"), _f(d[5], "pct"),
                                        "%.0f%%" % (100 * res["p_loss"]),
                                        "%.0f%%" % (100 * res["p_dd"][0.2])])
        self.status.emit("Monte Carlo bitti: %d yol" % a["paths"])

    # ------------------------------------------------------------ walk-forward

    def run_walk_forward(self):
        if not self.result:
            return
        strat = self.result["strategy"]
        grid = strategies.RESEARCH_GRID.get(strat.key)
        if not grid:
            return
        self.wf_btn.setEnabled(False)
        self.status.emit("İleri yürüyüş: %s, %d ayar…" % (strat.name, len(grid)))
        run_async(_walk_forward, strat.key, grid, self.result, self.wf_train.value(),
                  self.wf_test.value(), self.wf_anchored.isChecked(), done=self._wf_done,
                  failed=lambda m: (self.wf_btn.setEnabled(True),
                                    self.wf_info.setText("İleri yürüyüş yapılamadı: %s" % m)))

    def _wf_done(self, out):
        self.wf_btn.setEnabled(True)
        wf, spy_eq, spy_m = out
        folds = wf["folds"]
        self.wf_table.setRowCount(len(folds))
        for r, f in enumerate(folds):
            params = ", ".join("%s=%s" % (k, strategies._short(v)) for k, v in f["params"].items())
            period = "%s – %s" % (f["test"][0][:7], f["test"][1][:7])
            _set_row(self.wf_table, r, [period, params, "%.2f" % f["train_sharpe"],
                                        _f(f["test_return"], "pct"), "%.2f" % f["test_sharpe"],
                                        _f(f["test_max_dd"], "pct")],
                     {3: theme.color_for(f["test_return"])})
            self.wf_table.item(r, 1).setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            self.wf_table.item(r, 1).setToolTip(params)
        xs = wf["dates"].astype("datetime64[s]").astype("int64").astype(float)
        self.wf_curve.setData(xs, wf["equity"])
        n = min(len(xs), len(spy_eq))
        self.wf_spy.setData(xs[:n], spy_eq[:n])
        self.wf_plot.autoRange()
        m = wf["metrics"]
        eff = wf["efficiency"]
        self.wf_info.setText(
            "Örnek dışı (%s – %s): yıllık %s, Sharpe %.2f, en büyük düşüş %s · aynı dönemde SPY: "
            "yıllık %s, Sharpe %.2f, düşüş %s · verim (örnek dışı / eğitim Sharpe) %s. Verim 0.5'in "
            "altındaysa geçmişte seçilen ayarlar geleceğe pek taşınmamış demektir." % (
                m["start"], m["end"], _f(m["cagr"], "pct"), m["sharpe_excess"],
                _f(m["max_dd"], "pct"), _f(spy_m["cagr"], "pct"), spy_m["sharpe_excess"],
                _f(spy_m["max_dd"], "pct"), "%.2f" % eff if np.isfinite(eff) else "—"))
        self.status.emit("İleri yürüyüş bitti: %d test dönemi" % len(folds))

    # ------------------------------------------------------------ other actions

    def kelly_hint(self):
        """(win rate, payoff) of the last backtest's round trips, for the
        position calculator's Kelly section; None before any run."""
        if not self.result:
            return None
        m = self.result["m"]
        if m.get("win_rate") is None or not m.get("payoff"):
            return None
        return float(m["win_rate"]), float(m["payoff"])

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


def _monte_carlo(eq, eqb, horizon, paths, block):
    """Worker: bootstrap the strategy and SPY with the same seed."""
    a = analysis.bootstrap(analysis.returns(eq), horizon, paths, block, seed=7)
    b = analysis.bootstrap(analysis.returns(eqb), horizon, paths, block, seed=7)
    return a, b


def _walk_forward(key, grid, result, train, test, anchored):
    """Worker: walk-forward over the backtest's window, and SPY over the
    same out-of-sample span starting with the same cash."""
    kw = result["kw"]
    panel = result["panel"]
    wf = analysis.walk_forward(key, grid, panel, result["start"], result["end"], train, test,
                               anchored, result["rf"], kw["capital"], kw["cost_bps"], kw["band"])
    d = wf["dates"]
    ones = np.where(np.isfinite(panel.close("SPY"))[:, None], 1.0, np.nan)
    spy = run_backtest(panel, ones, ["SPY"], str(d[0]), str(d[-1]), capital=float(wf["equity"][0]),
                       cost_bps=kw["cost_bps"], band=kw["band"])
    _, eqs = spy.window()
    return wf, eqs, spy.metrics(result["rf"])


def _prob(p):
    """A probability as Turkish percent; one decimal near certainty."""
    return "%%%.1f" % (100 * p) if 0.99 < p < 1 else "%%%.0f" % (100 * p)


def _f(v, kind):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    if kind in ("pct", "pct1", "share", "num") and abs(v) < 5e-5:
        v = 0.0                          # no "-0.00"
    if kind == "pct1" and abs(v) < 5e-4:
        v = 0.0
    if kind == "pct":
        return "%+.2f%%" % (100 * v)
    if kind == "pct1":
        return "%+.1f%%" % (100 * v)
    if kind == "share":
        return "%.1f%%" % (100 * v)
    if kind == "int":
        return "%d" % v
    return "%.2f" % v
