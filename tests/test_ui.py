"""The window driven offscreen with the bundled sample data (no network)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Chromium refuses to run as root with its sandbox (CI containers)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

from PySide6 import QtWidgets  # noqa: E402

from traderbot import app as appmod  # noqa: E402
from traderbot import config  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return appmod._qt_app(["test"])


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("TRADERBOT_HOME", str(tmp_path))
    from traderbot.ui import context, workers
    from traderbot.ui.main_window import MainWindow
    data = appmod.OfflineData()
    ctx = context.AppContext(settings=config.Settings(str(tmp_path / "s.json")), data=data)
    ctx.settings.set("accepted_disclaimer", True)
    ctx.broker.clock = lambda now=None: {"open": True}
    win = MainWindow(ctx)
    win.start()

    def pump(n=10):
        for _ in range(n):
            qapp.processEvents()
            workers.wait_all(200)
            qapp.processEvents()

    pump()
    yield win, ctx, pump
    win.quit()
    pump(2)


def test_tabs_and_chart_load(window):
    win, ctx, pump = window
    names = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert names == ["Grafik", "Piyasa", "Tarayıcı", "Bot", "Backtest", "Alarmlar", "13F Kopya",
                     "Haberler", "Kongre", "Rehber", "Ayarlar", "Günlük"]
    bars = win.chart.chart.bars
    assert bars is not None and len(bars) > 100
    assert "SPY" in win.chart.chart.info.text()


def test_chart_symbol_interval_indicators_and_live_merge(window):
    win, ctx, pump = window
    tab = win.chart
    tab.load_symbol("aapl")
    pump()
    assert tab.symbol == "AAPL" and tab.chart.bars.symbol == "AAPL"
    tab.set_interval("1d")
    pump()
    assert ctx.settings.get("chart")["interval"] == "1d"
    tab.ind_actions["rsi"].setChecked(False)
    tab.ind_actions["sma200"].setChecked(True)
    assert "rsi" not in tab.chart.panes and "sma200" in tab.chart.overlays
    n = len(tab.chart.bars)
    tab.refresh_live()
    pump()
    assert len(tab.chart.bars) == n  # same data merged over itself: nothing duplicated


def test_bot_cycle_shows_position(window):
    win, ctx, pump = window
    ctx.engine.start()
    res = ctx.engine.run_cycle()
    assert res["ok"]
    win.bot.refresh()
    pump()
    assert win.bot.positions.rowCount() == 1
    assert win.bot.positions.item(0, 0).text() == "SPY"
    assert win.bot.state_label.text() == "Bot: ÇALIŞIYOR"
    ctx.engine.halt("test")
    win.bot.refresh()
    assert win.bot.state_label.text() == "Bot: ACİL DURDURULDU"


def test_backtest_tab_runs(window):
    win, ctx, pump = window
    from PySide6 import QtCore
    win.backtest.start.setDate(QtCore.QDate(2024, 1, 2))
    win.backtest.run()
    pump(20)
    assert win.backtest.result is not None
    assert win.backtest.metrics.rowCount() > 10
    assert win.backtest.yearly.rowCount() >= 2


def test_settings_save_round_trip(window):
    win, ctx, pump = window
    tab = win.settings_tab
    tab.risk_fields["max_daily_loss_pct"].setValue(3)
    tab.auto.setChecked(False)
    tab.save()
    again = config.Settings(ctx.settings.path)
    assert again.get("risk")["max_daily_loss_pct"] == 3
    assert again.get("auto_trade") is False


def test_platform_window_and_symbols(window):
    win, ctx, pump = window
    from traderbot.ui import platform_window as pw
    assert pw.tradingview_symbol("THYAO.IS") == "BIST:THYAO"
    assert pw.tradingview_symbol("BTC-USD") == "BITSTAMP:BTCUSD"
    assert pw.tradingview_symbol("AAPL", "NMS") == "NASDAQ:AAPL"
    assert pw.tradingview_symbol("^GSPC") == "SP:SPX"
    assert pw.tradingview_symbol("EURUSD=X") == "FX:EURUSD"
    assert "finance.yahoo.com/quote/THYAO.IS" in pw.page_url("yahoo", "THYAO.IS")
    w = pw.PlatformWindow("SPY", "1d", "tradingview", "PCX", win)
    pump(3)
    assert w.windowTitle().startswith("SPY")
    w.close()


def test_market_tab_loads_offline(window):
    win, ctx, pump = window
    win.tabs.setCurrentWidget(win.market)
    pump(30)
    assert win.market.out is not None
    assert win.market.verdict.text().startswith("Piyasa durumu:")
    assert win.market.events.rowCount() > 0 and win.market.history.rowCount() >= 3
    win.market.combo.setCurrentIndex(2)
    assert len(win.market.curve.getData()[0]) > 100


def test_screener_ranks_the_watchlist(window):
    win, ctx, pump = window
    tab = win.screener
    tab.universe.setCurrentIndex(tab.universe.findText("İzleme listem"))
    tab.run()
    pump(30)
    assert tab.table.rowCount() == len(ctx.settings.get("watchlist"))
    assert ctx.settings.get("screener")["universe"] == "İzleme listem"
    opened = []
    tab.open_symbol.connect(opened.append)
    tab.table.cellDoubleClicked.emit(0, 0)
    assert opened == [tab.table.item(0, 0).text()]


def test_alerts_add_check_and_notify(window):
    win, ctx, pump = window
    tab = win.alerts
    tab.prefill("SPY", "price_above", 1.0)
    tab.add()
    pump(20)
    saved = ctx.settings.get("alerts")
    assert len(saved) == 1 and saved[0]["last_state"] is True     # learned, did not fire
    fired = []
    tab.fired.connect(lambda t, m: fired.append(t))
    items = ctx.settings.get("alerts")
    items[0]["last_state"] = False                                   # pretend it was below
    ctx.settings.set("alerts", items)
    tab.check()
    pump(20)
    assert fired == ["Alarm: SPY"] and ctx.settings.get("alerts")[0]["enabled"] is False
    assert tab.log.count() == 1


def test_sizing_dialog_computes_shares(window):
    win, ctx, pump = window
    win.open_sizing("SPY")
    pump(20)
    dlg = win._dialogs[-1]
    dlg.stop_mode.setCurrentIndex(dlg.stop_mode.findData("pct"))
    dlg.equity.setValue(10000)
    dlg.risk.setValue(1.0)
    dlg.entry.setValue(100.0)
    dlg.stop_value.setValue(5.0)
    assert "Adet: 20.0000" in dlg.result.text()                    # $100 risk / $5 per share
    dlg.close()


def test_guide_shows_the_research_documents(window):
    win, ctx, pump = window
    tab = win.guide
    assert tab.current == "ARASTIRMA.md"
    text = tab.view.toPlainText()
    assert "Trading araştırması" in text and "Kaynaklar" in text
    tab.show_doc("REPORT.md")
    assert "Strateji araştırması" in tab.view.toPlainText()
