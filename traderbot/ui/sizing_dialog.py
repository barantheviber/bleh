"""Position calculator: shares from the risk accepted per trade, the Kelly
fraction, and the bot's own volatility-target rule."""

import numpy as np
from PySide6 import QtCore, QtWidgets

from .. import indicators as ind
from .. import sizing
from . import theme
from .workers import run_async


def _spin(lo, hi, val, dec=2, step=1.0, prefix="", suffix=""):
    w = QtWidgets.QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(dec)
    w.setSingleStep(step)
    w.setValue(val)
    w.setPrefix(prefix)
    w.setSuffix(suffix)
    return w


def money(x):
    return "${:,.2f}".format(x)


class SizingDialog(QtWidgets.QDialog):
    def __init__(self, ctx, symbol, parent=None, kelly_hint=None):
        super().__init__(parent)
        self.ctx = ctx
        self.symbol = symbol.upper()
        self.atr = None
        self.vol = None
        self.setWindowTitle("Pozisyon hesaplayıcı — %s" % self.symbol)
        self.resize(760, 640)

        self.info = theme.label("%s verisi yükleniyor…" % self.symbol, "muted", wrap=True)
        self.equity = _spin(1, 1e10, 10000, 2, 1000, "$ ")
        self.risk = _spin(0.1, 10, 1.0, 2, 0.25, suffix=" %")
        self.entry = _spin(0.0001, 1e7, 100, 4, 0.5, "$ ")
        self.stop_mode = QtWidgets.QComboBox()
        for key, name in (("atr", "ATR katı (oynaklığa göre)"), ("pct", "Girişin % altı"),
                          ("price", "Sabit fiyat")):
            self.stop_mode.addItem(name, key)
        self.stop_value = _spin(0.0001, 1e7, 2.0, 4, 0.5)
        risk_cfg = ctx.settings.get("risk") or {}
        self.max_pos = _spin(1, 100, float(risk_cfg.get("max_position_pct") or 100), 1, 5,
                             suffix=" %")
        self.fractional = QtWidgets.QCheckBox("Kesirli hisse (simülasyon ve Alpaca destekler)")
        self.fractional.setChecked(True)
        form = QtWidgets.QFormLayout()
        form.addRow("Hesap değeri", self.equity)
        form.addRow("İşlem başına risk", self.risk)
        form.addRow("Giriş fiyatı", self.entry)
        form.addRow("Stop yöntemi", self.stop_mode)
        form.addRow("Stop değeri", self.stop_value)
        form.addRow("En büyük pozisyon", self.max_pos)
        form.addRow(self.fractional)
        self.result = theme.label("", wrap=True)
        self.result.setTextFormat(QtCore.Qt.RichText)
        self.result.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        risk_box = QtWidgets.QGroupBox("Sabit oranlı risk (stop'a göre adet)")
        rl = QtWidgets.QHBoxLayout(risk_box)
        rl.addLayout(form, 1)
        rl.addWidget(self.result, 1)

        win, payoff = (kelly_hint or (0.55, 1.2))
        self.win = _spin(1, 99, 100 * win, 1, 1, suffix=" %")
        self.payoff = _spin(0.05, 20, payoff, 2, 0.1)
        self.kelly_out = theme.label("", wrap=True)
        self.kelly_out.setTextFormat(QtCore.Qt.RichText)
        kf = QtWidgets.QFormLayout()
        kf.addRow("Kazanma oranı", self.win)
        kf.addRow("Ort. kazanç / ort. kayıp", self.payoff)
        kelly_box = QtWidgets.QGroupBox("Kelly kriteri")
        kl = QtWidgets.QHBoxLayout(kelly_box)
        kl.addLayout(kf, 1)
        kl.addWidget(self.kelly_out, 1)

        self.target = _spin(1, 100, 15, 1, 1, suffix=" %")
        self.vol_out = theme.label("", wrap=True)
        self.vol_out.setTextFormat(QtCore.Qt.RichText)
        vf = QtWidgets.QFormLayout()
        vf.addRow("Hedef yıllık oynaklık", self.target)
        vol_box = QtWidgets.QGroupBox("Oynaklık hedefi (botun kuralı)")
        vl = QtWidgets.QHBoxLayout(vol_box)
        vl.addLayout(vf, 1)
        vl.addWidget(self.vol_out, 1)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.info)
        lay.addWidget(risk_box)
        lay.addWidget(kelly_box)
        lay.addWidget(vol_box)
        lay.addWidget(theme.label(
            "Kaynaklar: sabit oranlı risk, uygulayıcıların 1R kuralıdır. Kelly (1956) büyümeyi en "
            "üst düzeye çıkaran oranı verir; kazanma oranı ve kazanç/kayıp tahminleri belirsiz "
            "olduğu için araştırmalar Kelly'nin bir kesrini önerir (MacLean, Thorp ve Ziemba "
            "2010). Oynaklık hedefi Moreira ve Muir'in (2017) kuralıdır.", "muted", wrap=True))
        close = theme.button("Kapat")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, QtCore.Qt.AlignRight)

        for w in (self.equity, self.risk, self.entry, self.stop_value, self.max_pos, self.win,
                  self.payoff, self.target):
            w.valueChanged.connect(self.recalc)
        self.stop_mode.currentIndexChanged.connect(self._mode_changed)
        self.fractional.toggled.connect(self.recalc)
        self.recalc()
        run_async(self._load, done=self._loaded, failed=self._load_failed)

    # ------------------------------------------------------------ data

    def _load(self):
        bars = self.ctx.data.bars(self.symbol, "1d", "1y")[0]
        try:
            equity = float(self.ctx.broker.account().equity)
        except Exception:  # the calculator works without a broker
            equity = None
        return bars, equity

    def _load_failed(self, msg):
        self.info.setText("%s verisi alınamadı (%s). Değerleri elle girebilirsiniz." % (
            self.symbol, msg))

    def _loaded(self, res):
        bars, equity = res
        c = np.asarray(bars.c, dtype=np.float64)
        atr = ind.atr(bars.h, bars.l, bars.c, 14)[-1]
        vol = ind.realized_vol(c, 20)[-1]
        self.atr = float(atr) if np.isfinite(atr) else None
        self.vol = float(vol) if np.isfinite(vol) else None
        if equity:
            self.equity.setValue(equity)
        self.entry.setValue(float(c[-1]))
        self.info.setText("%s · son fiyat %.2f · ATR(14) %s · 20 günlük oynaklık %s · tarih %s" % (
            self.symbol, c[-1], "%.2f" % self.atr if self.atr else "—",
            "%%%.1f" % (100 * self.vol) if self.vol else "—", bars.date_str(-1)))
        self._mode_changed()

    def _mode_changed(self, *_):
        mode = self.stop_mode.currentData()
        self.stop_value.blockSignals(True)
        if mode == "atr":
            self.stop_value.setSuffix(" × ATR")
            self.stop_value.setValue(2.0)
        elif mode == "pct":
            self.stop_value.setSuffix(" %")
            self.stop_value.setValue(8.0)
        else:
            self.stop_value.setSuffix(" $")
            self.stop_value.setValue(round(self.entry.value() * 0.92, 2))
        self.stop_value.blockSignals(False)
        self.recalc()

    # ------------------------------------------------------------ results

    def stop_price(self):
        mode, v, entry = self.stop_mode.currentData(), self.stop_value.value(), self.entry.value()
        if mode == "atr":
            return sizing.atr_stop(entry, self.atr, v) if self.atr else None
        if mode == "pct":
            return entry * (1 - v / 100.0)
        return v

    def recalc(self, *_):
        self._risk_result()
        self._kelly_result()
        self._vol_result()

    def _risk_result(self):
        stop = self.stop_price()
        if stop is None:
            self.result.setText("ATR verisi bekleniyor; stop için yüzde ya da fiyat seçin.")
            return
        try:
            r = sizing.fixed_fractional(self.equity.value(), self.risk.value(), self.entry.value(),
                                        stop, self.max_pos.value(), self.fractional.isChecked())
        except sizing.SizingError as exc:
            self.result.setText("<span style='color:%s'>%s</span>" % (theme.DOWN, exc))
            return
        streak = sizing.losing_streak(r["risk_pct"], 10)
        warn = ""
        if r["capped"]:
            warn = ("<br><span style='color:%s'>Pozisyon üst sınırına takıldı; gerçek risk "
                    "seçtiğinizden az.</span>" % theme.WARN)
        t = r["targets"]
        self.result.setText(
            "<b>Adet: %s</b><br>Tutar: %s · hesap payı %%%.1f<br>Stop: %.2f · girişten %%%.1f "
            "aşağıda<br>Stopta zarar: %s · hesap payı %%%.2f<br>Hedefler: 1R %.2f · 2R %.2f · "
            "3R %.2f<br><span style='color:%s'>Bu riskle art arda 10 zararda hesap %%%.1f "
            "küçülür.</span>%s"
            % ("%.4f" % r["shares"] if self.fractional.isChecked() else "%d" % r["shares"],
               money(r["value"]), 100 * r["weight"], r["stop"], 100 * r["stop_pct"],
               money(r["risk_usd"]), r["risk_pct"], t[1], t[2], t[3], theme.MUTED,
               -100 * streak, warn))

    def _kelly_result(self):
        try:
            k = sizing.kelly(self.win.value() / 100.0, self.payoff.value())
        except sizing.SizingError as exc:
            self.kelly_out.setText(str(exc))
            return
        if k <= 0:
            self.kelly_out.setText("<span style='color:%s'><b>Kelly %%%.1f: bu kazanma oranı ve "
                                   "kazanç/kayıp oranıyla sistem ortalamada para kaybeder. İşlem "
                                   "yapmayın.</b></span>" % (theme.DOWN, 100 * k))
            return
        self.kelly_out.setText(
            "Tam Kelly: hesap payı <b>%%%.1f</b><br>Yarım Kelly: %%%.1f · Çeyrek Kelly: %%%.1f<br>"
            "<span style='color:%s'>Tahmin hatası ve ardışık kayıplar yüzünden tam Kelly çok "
            "risklidir; çoğu uygulayıcı yarısını ya da çeyreğini kullanır.</span>" % (
                100 * k, 50 * k, 25 * k, theme.MUTED))

    def _vol_result(self):
        if not self.vol:
            self.vol_out.setText("Oynaklık verisi bekleniyor…")
            return
        w = sizing.vol_target_weight(self.vol, self.target.value() / 100.0)
        value = w * self.equity.value()
        shares = value / self.entry.value() if self.entry.value() > 0 else 0
        self.vol_out.setText(
            "Varlığın oynaklığı %%%.1f → hesap payı <b>%%%.0f</b><br>Tutar %s ≈ %.2f adet<br>"
            "<span style='color:%s'>Bot, trend yukarıyken SPY'ı bu kuralla tutar.</span>" % (
                100 * self.vol, 100 * w, money(value), shares, theme.MUTED))
