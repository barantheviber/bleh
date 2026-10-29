"""Main window: tabs, status bar, tray icon."""

from PySide6 import QtCore, QtGui, QtWidgets

from .. import APP_NAME, __version__, market_clock
from . import theme, workers
from .sizing_dialog import SizingDialog
from .tab_alerts import AlertsTab
from .tab_backtest import BacktestTab
from .tab_bot import BotTab
from .tab_chart import ChartTab
from .tab_copycat import CopycatTab
from .tab_guide import GuideTab
from .tab_log import LogTab
from .tab_market import MarketTab
from .tab_news import CongressTab, NewsTab
from .tab_screener import ScreenerTab
from .tab_settings import SettingsTab

DISCLAIMER = (
    "<b>TraderBot yatırım tavsiyesi değildir.</b><br><br>"
    "Bot, geçmiş verilerle test edilmiş kurallara göre kendi kendine alım satım yapar. Geçmiş "
    "sonuçlar geleceği garanti etmez ve para kaybedebilirsiniz.<br><br>"
    "Varsayılan hesap <b>simülasyondur</b>: gerçek para kullanılmaz. Gerçek parayla işlem için "
    "Ayarlar'dan Alpaca hesabı bağlayıp canlı işlemi ayrıca onaylamanız gerekir.<br><br>"
    "Seçilen strateji (Volatilite Hedefli Trend) büyük düşüşlerde zararı sınırlamak için "
    "tasarlandı; yükselen piyasada genelde S&P 500'ü al-tut yapmaktan <b>daha az</b> kazandırdı. "
    "Ayrıntılar ve stratejilerin dayandığı araştırmalar: Rehber sekmesi.")


def app_icon():
    pm = QtGui.QPixmap(64, 64)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setBrush(QtGui.QColor(theme.ACCENT))
    p.setPen(QtCore.Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 12, 12)
    pen = QtGui.QPen(QtGui.QColor("white"), 5)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([QtCore.QPointF(12, 46), QtCore.QPointF(25, 30), QtCore.QPointF(35, 38),
                    QtCore.QPointF(52, 16)])
    p.end()
    return QtGui.QIcon(pm)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._quitting = False
        self.setWindowIcon(app_icon())
        self.resize(1440, 900)
        self.tabs = QtWidgets.QTabWidget()
        self.chart = ChartTab(ctx)
        self.market = MarketTab(ctx)
        self.screener = ScreenerTab(ctx)
        self.bot = BotTab(ctx)
        self.backtest = BacktestTab(ctx)
        self.alerts = AlertsTab(ctx)
        self.copycat = CopycatTab(ctx)
        self.news = NewsTab(ctx)
        self.congress = CongressTab(ctx)
        self.guide = GuideTab(ctx)
        self.settings_tab = SettingsTab(ctx)
        self.log = LogTab(ctx)
        for w, name in ((self.chart, "Grafik"), (self.market, "Piyasa"),
                        (self.screener, "Tarayıcı"), (self.bot, "Bot"),
                        (self.backtest, "Backtest"), (self.alerts, "Alarmlar"),
                        (self.copycat, "13F Kopya"), (self.news, "Haberler"),
                        (self.congress, "Kongre"), (self.guide, "Rehber"),
                        (self.settings_tab, "Ayarlar"),
                        (self.log, "Günlük")):
            self.tabs.addTab(w, name)
            if hasattr(w, "status"):
                w.status.connect(self.show_message)
        self.setCentralWidget(self.tabs)
        self._dialogs = []
        for src in (self.chart, self.screener):
            src.size_symbol.connect(self.open_sizing)
            src.alert_symbol.connect(self.new_alert)
        self.screener.open_symbol.connect(self.open_symbol)
        self.screener.watch_symbol.connect(self.add_to_watchlist)
        self.alerts.fired.connect(lambda title, msg: self.notify("alerts", title, msg))
        ctx.event.connect(self._bot_event)

        self.market_label = QtWidgets.QLabel()
        self.broker_label = QtWidgets.QLabel()
        self.bot_label = QtWidgets.QLabel()
        sb = self.statusBar()
        for lb in (self.bot_label, self.broker_label, self.market_label):
            lb.setStyleSheet("padding: 0 8px;")
            sb.addPermanentWidget(lb)
        self.clock = QtCore.QTimer(self)
        self.clock.timeout.connect(self._tick_labels)
        self.clock.start(1000)
        ctx.settings_changed.connect(self._settings_changed)
        ctx.broker_changed.connect(self._tick_labels)
        ctx.event.connect(lambda *_: self._tick_labels())
        self._tray()
        self._settings_changed()
        self._tick_labels()

    # ------------------------------------------------------------ chrome

    def _tray(self):
        self.tray = None
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QtWidgets.QSystemTrayIcon(app_icon(), self)
        menu = QtWidgets.QMenu()
        menu.addAction("Göster", self.show_normal)
        menu.addSeparator()
        menu.addAction("Çıkış", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_normal()
                                    if reason == QtWidgets.QSystemTrayIcon.Trigger else None)
        self.tray.setToolTip(APP_NAME)
        self.tray.show()

    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_message(self, msg):
        self.statusBar().showMessage(msg, 10000)

    # ------------------------------------------------------------ tools

    def open_symbol(self, symbol):
        self.chart.load_symbol(symbol)
        self.tabs.setCurrentWidget(self.chart)

    def open_sizing(self, symbol):
        dlg = SizingDialog(self.ctx, symbol, self, kelly_hint=self.backtest.kelly_hint())
        dlg.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda *_: self._dialogs.remove(dlg) if dlg in self._dialogs else None)
        self._dialogs.append(dlg)
        dlg.show()

    def new_alert(self, symbol):
        self.alerts.prefill(symbol)
        self.tabs.setCurrentWidget(self.alerts)

    def add_to_watchlist(self, symbol):
        w = self.chart.watch
        if symbol not in w.symbols:
            w.set_symbols(w.symbols + [symbol])
            w._save()
            w.refresh()
        self.show_message("%s izleme listesine eklendi" % symbol)

    def notify(self, kind, title, message):
        """A Windows notification from the tray, if the user wants this kind."""
        self.show_message("%s: %s" % (title, message))
        if self.tray and (self.ctx.settings.get("notify") or {}).get(kind, True):
            self.tray.showMessage(title, message, QtWidgets.QSystemTrayIcon.Information, 8000)

    def _bot_event(self, kind, rec):
        if kind in ("order", "approval"):
            self.notify("orders", "TraderBot: emir" if kind == "order" else "TraderBot: onay bekliyor",
                        rec.get("message", ""))
        elif kind == "halted":
            self.notify("halts", "TraderBot: ACİL DURUM", rec.get("message", ""))

    def _settings_changed(self):
        live = self.ctx.is_live()
        broker = self.ctx.broker.label
        self.setWindowTitle("%s %s — %s%s" % (APP_NAME, __version__, broker,
                                              "  ⚠ GERÇEK PARA" if live else ""))
        secs = max(3, int(self.ctx.settings.get("refresh_seconds") or 10))
        self.chart.live_timer.setInterval(secs * 1000)

    def _tick_labels(self):
        st = market_clock.status()
        color = theme.UP if st["open"] else theme.MUTED
        self.market_label.setText("<span style='color:%s'>%s</span>" % (color, market_clock.describe(st)))
        live = self.ctx.is_live()
        self.broker_label.setText("<span style='color:%s'>%s</span>" % (
            theme.LIVE if live else theme.MUTED, self.ctx.broker.label))
        snap = self.ctx.engine.snapshot()
        if snap["halted"]:
            txt, col = "Bot: ACİL DURDU", theme.DOWN
        elif snap["running"]:
            txt, col = "Bot: çalışıyor", theme.UP
        else:
            txt, col = "Bot: durdu", theme.MUTED
        self.bot_label.setText("<span style='color:%s'>%s</span>" % (col, txt))

    # ------------------------------------------------------------ lifecycle

    def start(self, minimized=False):
        if minimized and self.tray:
            self.hide()
        else:
            self.show()
        self.chart.start()
        self.bot.refresh()
        if not self.ctx.settings.get("accepted_disclaimer"):
            QtCore.QTimer.singleShot(300, self._disclaimer)

    def _disclaimer(self):
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Önemli")
        box.setTextFormat(QtCore.Qt.RichText)
        box.setText(DISCLAIMER)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.exec()
        self.ctx.settings.set("accepted_disclaimer", True)

    def quit(self):
        self._quitting = True
        self.close()

    def closeEvent(self, event):
        running = self.ctx.engine.snapshot()["running"]
        if running and self.tray and not self._quitting:
            event.ignore()
            self.hide()
            self.tray.showMessage(APP_NAME, "Bot arka planda çalışmaya devam ediyor. Kapatmak için "
                                  "tepsideki simgeden Çıkış'ı seçin.",
                                  QtWidgets.QSystemTrayIcon.Information, 5000)
            return
        if running and not self._quitting:
            ans = QtWidgets.QMessageBox.question(
                self, "Çıkış", "Bot çalışıyor; uygulama kapanırsa bot da durur. Çıkılsın mı?")
            if ans != QtWidgets.QMessageBox.Yes:
                event.ignore()
                return
        self.log.detach()
        if self.tray:
            self.tray.hide()
        workers.wait_all(5000)  # let running fetches land before Qt objects go away
        event.accept()
        QtWidgets.QApplication.instance().quit()
