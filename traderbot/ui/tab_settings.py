"""Settings tab: broker and keys, bot mode, risk limits, data."""

import os
import sys

from PySide6 import QtCore, QtGui, QtWidgets

from .. import config, keystore, paths
from ..brokers import BrokerError
from ..brokers.alpaca import AlpacaBroker
from . import theme
from .platform_window import PLATFORMS
from .workers import run_async

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _spin(lo, hi, val, decimals=0, suffix=""):
    w = QtWidgets.QDoubleSpinBox() if decimals else QtWidgets.QSpinBox()
    w.setRange(lo, hi)
    if decimals:
        w.setDecimals(decimals)
    w.setValue(val)
    if suffix:
        w.setSuffix(suffix)
    return w


class SettingsTab(QtWidgets.QWidget):
    status = QtCore.Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        s = ctx.settings
        risk = s.get("risk") or {}

        # broker
        self.sim_radio = QtWidgets.QRadioButton("Simülasyon hesabı (gerçek para yok)")
        self.alpaca_radio = QtWidgets.QRadioButton("Alpaca")
        (self.alpaca_radio if s.get("broker") == "alpaca" else self.sim_radio).setChecked(True)
        self.sim_cash = _spin(100, 1e9, float(s.get("sim_cash") or 10000), 2, " $")
        self.sim_slip = _spin(0, 100, float(s.get("sim_slippage_bps") or 0), 1, " bp")
        reset = theme.button("Simülasyon hesabını sıfırla")
        reset.clicked.connect(self._reset_sim)
        self.key_id = QtWidgets.QLineEdit()
        self.key_id.setPlaceholderText("API Key ID  (kayıtlı: %s)" % (keystore.mask(s.secret("alpaca_key_id")) or "yok"))
        self.secret = QtWidgets.QLineEdit()
        self.secret.setEchoMode(QtWidgets.QLineEdit.Password)
        self.secret.setPlaceholderText("Secret Key  (kayıtlı: %s)" % ("evet" if s.secret("alpaca_secret") else "yok"))
        self.paper_radio = QtWidgets.QRadioButton("Kağıt (paper) hesap")
        self.live_radio = QtWidgets.QRadioButton("CANLI hesap (gerçek para)")
        (self.paper_radio if s.get("alpaca_paper", True) else self.live_radio).setChecked(True)
        self.live_radio.toggled.connect(self._live_toggled)
        test = theme.button("Bağlantıyı test et")
        test.clicked.connect(self._test_alpaca)
        self.test_result = theme.label("", "muted", wrap=True)

        broker_box = QtWidgets.QGroupBox("Aracı kurum")
        bf = QtWidgets.QFormLayout(broker_box)
        bf.addRow(self.sim_radio)
        bf.addRow("   Başlangıç nakdi", self.sim_cash)
        bf.addRow("   Kayma (slippage)", self.sim_slip)
        bf.addRow("", reset)
        bf.addRow(self.alpaca_radio)
        bf.addRow("   Key ID", self.key_id)
        bf.addRow("   Secret", self.secret)
        bf.addRow("", self.paper_radio)
        bf.addRow("", self.live_radio)
        bf.addRow("", test)
        bf.addRow(self.test_result)
        bf.addRow(theme.label(
            "Alpaca: alpaca.markets'ta ücretsiz hesap açın, Paper Trading bölümünden API anahtarı "
            "alın. Anahtarlar bu bilgisayarda %s saklanır ve yalnızca Alpaca'ya gönderilir."
            % ("Windows hesabınıza şifreli (DPAPI)" if sys.platform.startswith("win") else
               "yalnız sizin okuyabileceğiniz bir dosyada"), "muted", wrap=True))

        # bot
        self.auto = QtWidgets.QCheckBox("Tam otomatik: emirleri onay beklemeden gönder")
        self.auto.setChecked(bool(s.get("auto_trade")))
        hh, mm = (s.get("trade_time") or "10:00").split(":")
        self.trade_time = QtWidgets.QTimeEdit(QtCore.QTime(int(hh), int(mm)))
        self.trade_time.setDisplayFormat("HH:mm")
        self.sell_untracked = QtWidgets.QCheckBox("Hesabın tamamını yönet (stratejide olmayan "
                                                  "pozisyonları sat)")
        self.sell_untracked.setChecked(bool(s.get("sell_untracked")))
        self.autostart = QtWidgets.QCheckBox("Windows açılınca TraderBot'u tepside başlat")
        self.autostart.setEnabled(sys.platform.startswith("win"))
        self.autostart.setChecked(_autostart_enabled())
        bot_box = QtWidgets.QGroupBox("Bot")
        bt = QtWidgets.QFormLayout(bot_box)
        bt.addRow(self.auto)
        bt.addRow("Karar saati (New York)", self.trade_time)
        bt.addRow(self.sell_untracked)
        bt.addRow(self.autostart)
        notify = s.get("notify") or {}
        self.notify_boxes = {}
        for key, text in (("orders", "Windows bildirimi: botun emirleri ve onay bekleyenler"),
                          ("halts", "Windows bildirimi: acil durum (kill switch)"),
                          ("alerts", "Windows bildirimi: çalan alarmlar")):
            box = QtWidgets.QCheckBox(text)
            box.setChecked(bool(notify.get(key, True)))
            self.notify_boxes[key] = box
            bt.addRow(box)
        bt.addRow(theme.label("Bot, uygulama açıkken (tepside de olur) günde bir kez çalışır. "
                              "NY 10:00, Türkiye saatiyle 17:00'dir; ABD kış saatinde (Kasım başı - "
                              "Mart ortası) 18:00.", "muted", wrap=True))

        # risk
        self.risk_fields = {
            "cash_buffer_pct": _spin(0, 90, float(risk.get("cash_buffer_pct") or 0), 1, " %"),
            "max_position_pct": _spin(1, 100, float(risk.get("max_position_pct") or 100), 1, " %"),
            "max_order_usd": _spin(0, 1e9, float(risk.get("max_order_usd") or 0), 0, " $"),
            "min_order_usd": _spin(0, 1e6, float(risk.get("min_order_usd") or 0), 0, " $"),
            "max_orders_per_day": _spin(0, 1000, int(risk.get("max_orders_per_day") or 0)),
            "rebalance_band_pct": _spin(0, 50, float(risk.get("rebalance_band_pct") or 5), 1, " puan"),
            "max_daily_loss_pct": _spin(0, 100, float(risk.get("max_daily_loss_pct") or 0), 1, " %"),
            "max_drawdown_pct": _spin(0, 100, float(risk.get("max_drawdown_pct") or 0), 1, " %"),
        }
        self.blocked = QtWidgets.QLineEdit(", ".join(risk.get("blocked") or []))
        names = {"cash_buffer_pct": "Nakit tamponu", "max_position_pct": "Tek pozisyon üst sınırı",
                 "max_order_usd": "Emir başına en fazla (0 = hesap değeri)",
                 "min_order_usd": "En küçük emir", "max_orders_per_day": "Günlük emir sınırı",
                 "rebalance_band_pct": "Dengeleme bandı",
                 "max_daily_loss_pct": "Günlük zarar → acil durum",
                 "max_drawdown_pct": "Zirveden düşüş → acil durum"}
        risk_box = QtWidgets.QGroupBox("Risk kuralları (trader-risk)")
        rf = QtWidgets.QFormLayout(risk_box)
        for k, w in self.risk_fields.items():
            rf.addRow(names[k], w)
        rf.addRow("Asla alma", self.blocked)
        rf.addRow(theme.label("Açığa satış, kaldıraç ve opsiyon kapalıdır. 0 olan sınır devre dışıdır. "
                              "Acil durumda bot alım yapmaz, yalnızca riski azaltan satışları yapar; "
                              "Bot sekmesinde 'Devam et' ile normale döner.", "muted", wrap=True))

        # data
        self.sec_ua = QtWidgets.QLineEdit(s.get("sec_user_agent") or "")
        self.sec_ua.setPlaceholderText("Ad Soyad eposta@ornek.com")
        self.refresh = _spin(3, 300, int(s.get("refresh_seconds") or 10), suffix=" sn")
        self.platform = QtWidgets.QComboBox()
        for k, v in PLATFORMS.items():
            self.platform.addItem(v, k)
        self.platform.setCurrentIndex(max(0, self.platform.findData(s.get("platform"))))
        data_box = QtWidgets.QGroupBox("Veri")
        df = QtWidgets.QFormLayout(data_box)
        df.addRow("SEC kimliği", self.sec_ua)
        df.addRow(theme.label("SEC EDGAR her programdan ad ve e-posta ister (13F ve 8-K için). "
                              "Yalnızca SEC'e gönderilir.", "muted", wrap=True))
        df.addRow("Grafik yenileme", self.refresh)
        df.addRow("Platform penceresi", self.platform)
        folder = theme.button("Veri klasörünü aç")
        folder.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(paths.app_dir())))
        df.addRow("", folder)

        save = theme.button("Kaydet", "primary")
        save.clicked.connect(self.save)
        defaults = theme.button("Varsayılan risk ayarları")
        defaults.clicked.connect(self._default_risk)
        cols = QtWidgets.QHBoxLayout()
        c1, c2 = QtWidgets.QVBoxLayout(), QtWidgets.QVBoxLayout()
        c1.addWidget(broker_box)
        c1.addWidget(data_box)
        c1.addStretch(1)
        c2.addWidget(bot_box)
        c2.addWidget(risk_box)
        c2.addStretch(1)
        cols.addLayout(c1, 1)
        cols.addLayout(c2, 1)
        inner = QtWidgets.QWidget()
        il = QtWidgets.QVBoxLayout(inner)
        il.addLayout(cols)
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(defaults)
        btns.addWidget(save)
        il.addLayout(btns)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll)

    # ------------------------------------------------------------ actions

    def _live_toggled(self, on):
        if not on or self.ctx.settings.get("live_confirmed"):
            return
        text, ok = QtWidgets.QInputDialog.getText(
            self, "Canlı işlem onayı",
            "Canlı hesapta bot GERÇEK PARA ile alım satım yapar ve zarar edebilirsiniz.\n"
            "Bu yazılım yatırım tavsiyesi değildir; geçmiş test sonuçları geleceği garanti etmez.\n\n"
            "Onaylamak için büyük harflerle CANLI yazın:")
        if ok and text.strip() == "CANLI":
            self.ctx.settings.set("live_confirmed", True)
        else:
            self.paper_radio.setChecked(True)

    def _test_alpaca(self):
        key = self.key_id.text().strip() or self.ctx.settings.secret("alpaca_key_id")
        sec = self.secret.text().strip() or self.ctx.settings.secret("alpaca_secret")
        paper = self.paper_radio.isChecked()
        if not key or not sec:
            self.test_result.setText("Önce anahtarları girin.")
            return
        self.test_result.setText("Bağlanıyor…")

        def check():
            b = AlpacaBroker(key, sec, paper=paper)
            return b.account(), b.is_open()

        def done(res):
            a, is_open = res
            self.test_result.setText(
                "Bağlandı: %s hesap · varlık $%s · nakit $%s · durum %s · piyasa %s" % (
                    "kağıt" if paper else "CANLI", "{:,.2f}".format(a.equity),
                    "{:,.2f}".format(a.cash), a.status, "açık" if is_open else "kapalı"))

        run_async(check, done=done, failed=lambda m: self.test_result.setText("Hata: %s" % m))

    def _reset_sim(self):
        if QtWidgets.QMessageBox.question(
                self, "Sıfırla", "Simülasyon hesabındaki tüm pozisyonlar ve emirler silinecek, nakit "
                "%s $ olacak. Devam?" % "{:,.0f}".format(self.sim_cash.value())) \
                != QtWidgets.QMessageBox.Yes:
            return
        self.ctx.settings.set("sim_cash", float(self.sim_cash.value()))
        from ..brokers import create_sim
        create_sim(self.ctx.settings, self.ctx.price_source).reset(float(self.sim_cash.value()))
        self.ctx.engine.reset()
        self.ctx.rebuild_broker()
        self.status.emit("Simülasyon hesabı sıfırlandı")

    def _default_risk(self):
        risk = config.DEFAULTS["risk"]
        for k, w in self.risk_fields.items():
            w.setValue(risk.get(k) or 0)
        self.blocked.setText("")

    def save(self):
        s = self.ctx.settings
        old = (s.get("broker"), s.get("alpaca_paper"), s.secret("alpaca_key_id"),
               s.secret("alpaca_secret"), s.get("sim_cash"), s.get("sim_slippage_bps"))
        ua = self.sec_ua.text().strip()
        if ua and ("@" not in ua or "you@example.com" in ua):
            QtWidgets.QMessageBox.warning(self, "SEC kimliği", "Ad Soyad ve gerçek bir e-posta girin.")
            return
        if self.alpaca_radio.isChecked() and self.sell_untracked.isChecked() and not (
                s.get("broker") == "alpaca" and s.get("sell_untracked")):
            ans = QtWidgets.QMessageBox.warning(
                self, "Hesabın tamamı",
                "'Hesabın tamamını yönet' açık: bot, Alpaca hesabınızda stratejide olmayan "
                "BÜTÜN pozisyonları satar (elle aldıklarınız dahil).\n\nBöyle kalsın mı? "
                "'Hayır' derseniz bot yalnızca kendi stratejisindeki sembollere dokunur.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
            if ans != QtWidgets.QMessageBox.Yes:
                self.sell_untracked.setChecked(False)
        risk = {k: (w.value() if not isinstance(w, QtWidgets.QSpinBox) else int(w.value()))
                for k, w in self.risk_fields.items()}
        risk["max_order_usd"] = risk["max_order_usd"] or None
        risk["blocked"] = [x.strip().upper() for x in self.blocked.text().split(",") if x.strip()]
        s.update({
            "broker": "alpaca" if self.alpaca_radio.isChecked() else "sim",
            "alpaca_paper": self.paper_radio.isChecked(),
            "sim_cash": float(self.sim_cash.value()),
            "sim_slippage_bps": float(self.sim_slip.value()),
            "auto_trade": self.auto.isChecked(),
            "trade_time": self.trade_time.time().toString("HH:mm"),
            "sell_untracked": self.sell_untracked.isChecked(),
            "risk": risk,
            "sec_user_agent": ua,
            "refresh_seconds": int(self.refresh.value()),
            "platform": self.platform.currentData(),
            "notify": {k: b.isChecked() for k, b in self.notify_boxes.items()},
        }, save=False)
        if self.key_id.text().strip():
            s.set_secret("alpaca_key_id", self.key_id.text().strip(), save=False)
        if self.secret.text().strip():
            s.set_secret("alpaca_secret", self.secret.text().strip(), save=False)
        s.save()
        self.key_id.clear()
        self.secret.clear()
        _set_autostart(self.autostart.isChecked())
        new = (s.get("broker"), s.get("alpaca_paper"), s.secret("alpaca_key_id"),
               s.secret("alpaca_secret"), s.get("sim_cash"), s.get("sim_slippage_bps"))
        if new != old:
            self.ctx.rebuild_broker()
        self.ctx.settings_changed.emit()
        msg = "Ayarlar kaydedildi"
        if self.ctx.broker_error:
            msg += " · aracı kurulamadı, simülasyon kullanılıyor: %s" % self.ctx.broker_error
        self.status.emit(msg)


def _exe_command():
    if getattr(sys, "frozen", False):
        return '"%s" --minimized' % sys.executable
    return '"%s" -m traderbot --minimized' % sys.executable


def _autostart_enabled():
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "TraderBot")
            return True
    except OSError:
        return False


def _set_autostart(on):
    if not sys.platform.startswith("win"):
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, "TraderBot", 0, winreg.REG_SZ, _exe_command())
            else:
                try:
                    winreg.DeleteValue(k, "TraderBot")
                except OSError:
                    pass
    except OSError:
        pass
