"""Pop-up window that shows another charting platform for a symbol.

TradingView's free embeddable Advanced Chart widget (with TradingView's own
branding), or the Yahoo Finance / Finviz pages, in an embedded Chromium
(QtWebEngine). If the web engine is missing, the page opens in the default
browser instead.
"""

import json
import urllib.parse

from PySide6 import QtCore, QtGui, QtWidgets

from . import theme

try:
    from PySide6 import QtWebEngineWidgets  # noqa: F401
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAVE_WEB = True
except Exception:  # an install or bundle without QtWebEngine
    HAVE_WEB = False

PLATFORMS = {
    "tradingview": "TradingView (grafik)",
    "tradingview_page": "TradingView (tam sayfa)",
    "yahoo": "Yahoo Finance",
    "finviz": "Finviz (yalnız ABD)",
}
SUFFIX = {"IS": "BIST", "L": "LSE", "DE": "XETR", "TO": "TSX", "PA": "EURONEXT", "AS": "EURONEXT",
          "HK": "HKEX", "T": "TSE", "SW": "SIX", "MI": "MIL", "AX": "ASX"}
INDEXES = {"^GSPC": "SP:SPX", "^NDX": "NASDAQ:NDX", "^DJI": "DJ:DJI", "^IXIC": "NASDAQ:IXIC",
           "^VIX": "CBOE:VIX", "^XU100": "BIST:XU100", "^RUT": "TVC:RUT"}
EXCHANGES = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ", "NYQ": "NYSE",
             "NYS": "NYSE", "PCX": "AMEX", "ASE": "AMEX", "BTS": "AMEX", "ARCA": "AMEX"}
TV_INTERVALS = {"1m": "1", "2m": "1", "5m": "5", "15m": "15", "30m": "30", "60m": "60",
                "1h": "60", "90m": "60", "1d": "D", "1wk": "W", "1mo": "M"}


def tradingview_symbol(symbol, exchange=None):
    """Yahoo symbol -> TradingView symbol (THYAO.IS -> BIST:THYAO)."""
    s = (symbol or "").upper().strip()
    if s in INDEXES:
        return INDEXES[s]
    if s.endswith("=X"):
        return "FX:" + s[:-2]
    if "-" in s and s.split("-")[-1] in ("USD", "USDT", "EUR", "TRY"):
        base, quote = s.split("-", 1)
        return ("BINANCE:%s%s" if quote in ("USDT", "TRY") else "BITSTAMP:%s%s") % (base, quote)
    if "." in s:
        base, suf = s.rsplit(".", 1)
        if suf in SUFFIX:
            return "%s:%s" % (SUFFIX[suf], base)
        return s.replace(".", "_")
    ex = EXCHANGES.get((exchange or "").upper())
    return "%s:%s" % (ex, s) if ex else s


def widget_html(symbol, interval="1d", exchange=None):
    cfg = {"autosize": True, "symbol": tradingview_symbol(symbol, exchange),
           "interval": TV_INTERVALS.get(interval, "D"), "timezone": "Europe/Istanbul",
           "theme": "dark", "style": "1", "locale": "tr", "allow_symbol_change": True,
           "hide_side_toolbar": False, "withdateranges": True, "details": True,
           "studies": ["STD;RSI", "STD;MACD"], "support_host": "https://www.tradingview.com"}
    return """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>html,body{margin:0;height:100%%;background:%s}
.tradingview-widget-container,.tradingview-widget-container__widget{height:100%%;width:100%%}</style>
</head><body><div class="tradingview-widget-container">
<div class="tradingview-widget-container__widget"></div>
<script type="text/javascript"
 src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>
%s
</script></div></body></html>""" % (theme.BG, json.dumps(cfg))


def page_url(platform, symbol, exchange=None):
    s = (symbol or "").upper()
    q = urllib.parse.quote
    if platform == "yahoo":
        return "https://finance.yahoo.com/quote/%s/chart" % q(s)
    if platform == "finviz":
        return "https://finviz.com/quote.ashx?t=%s" % q(s.split(".")[0])
    return "https://www.tradingview.com/chart/?symbol=%s" % q(tradingview_symbol(s, exchange))


class PlatformWindow(QtWidgets.QDialog):
    def __init__(self, symbol, interval="1d", platform="tradingview", exchange=None, parent=None):
        super().__init__(parent)
        self.symbol, self.interval, self.exchange = symbol, interval, exchange
        self.setWindowTitle("%s · %s" % (symbol, PLATFORMS.get(platform, platform)))
        self.setWindowFlag(QtCore.Qt.WindowMaximizeButtonHint, True)
        self.resize(1200, 760)
        self.combo = QtWidgets.QComboBox()
        for key, name in PLATFORMS.items():
            self.combo.addItem(name, key)
        self.combo.setCurrentIndex(max(0, self.combo.findData(platform)))
        self.combo.currentIndexChanged.connect(self._load)
        browser = theme.button("Tarayıcıda aç", tip="Varsayılan tarayıcıda aç")
        browser.clicked.connect(self._open_browser)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(theme.label("<b>%s</b>" % symbol))
        top.addWidget(self.combo)
        top.addStretch(1)
        top.addWidget(browser)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(top)
        if HAVE_WEB:
            self.view = QWebEngineView(self)
            lay.addWidget(self.view, 1)
        else:
            self.view = None
            lay.addWidget(theme.label("Bu kurulumda gömülü tarayıcı (QtWebEngine) yok; sayfa "
                                      "varsayılan tarayıcıda açıldı.", "warn", wrap=True))
        self._load()

    def current(self):
        return self.combo.currentData()

    def _load(self, *_):
        p = self.current()
        self.setWindowTitle("%s · %s" % (self.symbol, PLATFORMS.get(p, p)))
        if self.view is None:
            self._open_browser()
            return
        if p == "tradingview":
            self.view.setHtml(widget_html(self.symbol, self.interval, self.exchange),
                              QtCore.QUrl("https://traderbot.local/"))
        else:
            self.view.setUrl(QtCore.QUrl(page_url(p, self.symbol, self.exchange)))

    def _open_browser(self):
        p = self.current()
        url = page_url("tradingview_page" if p == "tradingview" else p, self.symbol, self.exchange)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
