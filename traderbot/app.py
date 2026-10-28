"""TraderBot entry point.

    TraderBot.exe                  normal start
    TraderBot.exe --minimized      start in the tray (Windows autostart uses this)
    TraderBot.exe --selftest out.json
                                   build every part offline, write a report, exit 0/1
"""

import argparse
import datetime as dt
import json
import logging
import os
import sys
import tempfile
import time
import traceback

from . import APP_NAME, __version__

log = logging.getLogger("traderbot")


def _qt_app(argv):
    from PySide6 import QtCore, QtWidgets
    # QtWebEngine must be imported, and GL contexts shared, before the app exists
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
    try:
        from PySide6 import QtWebEngineWidgets  # noqa: F401
    except Exception:
        pass
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    from .ui import theme
    theme.apply(app)
    return app


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    ap = argparse.ArgumentParser(prog=APP_NAME)
    ap.add_argument("--minimized", action="store_true")
    ap.add_argument("--selftest", metavar="REPORT.json")
    args, _ = ap.parse_known_args(argv[1:])
    if args.selftest:
        return selftest(args.selftest)

    from . import log as applog
    applog.setup()
    log.info("%s %s starting", APP_NAME, __version__)
    app = _qt_app(argv)
    from PySide6 import QtWidgets
    from .ui.context import AppContext
    from .ui.main_window import MainWindow

    def excepthook(kind, value, tb):
        text = "".join(traceback.format_exception(kind, value, tb))
        log.error("unhandled error:\n%s", text)
        try:
            QtWidgets.QMessageBox.critical(None, APP_NAME, "Beklenmeyen hata:\n%s\n\nAyrıntı: "
                                           "Günlük sekmesi" % value)
        except Exception:
            pass

    sys.excepthook = excepthook
    ctx = AppContext()
    win = MainWindow(ctx)
    win.start(minimized=args.minimized)
    return app.exec()


# ---------------------------------------------------------------- self-test

class OfflineData(object):
    """MarketData stand-in that serves the bundled sample bars, no network."""

    def __init__(self):
        from . import paths
        from .data.bars import Bars
        folder = paths.resource("traderbot", "resources", "sample")
        self.daily_bars = {}
        for name in ("SPY", "BIL"):
            self.daily_bars[name] = Bars.load_csv(os.path.join(folder, "%s.csv.gz" % name), name,
                                                  gmtoffset=-14400)

    def _get(self, symbol):
        b = self.daily_bars.get(symbol.upper()) or self.daily_bars["SPY"]
        b = b.copy()
        b.symbol = symbol.upper()
        return b

    def bars(self, symbol, interval="1d", range_=None, fresh=False):
        b = self._get(symbol)
        return b, {"symbol": symbol, "longName": "Örnek veri", "currency": "USD",
                   "exchangeName": "PCX", "regularMarketPrice": float(b.c[-1])}

    def daily(self, symbols, range_="3y"):
        return {s: self._get(s) for s in symbols}

    def prices(self, symbols, fresh=False):
        return {s.upper(): float(self._get(s).adjusted().c[-1]) for s in symbols}

    def quote(self, symbol, fresh=False):
        from .data.yahoo import Quote
        b = self._get(symbol)
        return Quote(symbol=symbol, price=float(b.c[-1]), prev_close=float(b.c[-2]),
                     currency="USD", name="Örnek")

    def search(self, text):
        return []


def selftest(report_path):
    """Exercise the build offline: strategies, backtest, engine, keystore, UI."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    home = tempfile.mkdtemp(prefix="traderbot-selftest-")
    os.environ["TRADERBOT_HOME"] = home
    results, ok = [], True
    started = time.time()

    def step(name, fn, required=True):
        nonlocal ok
        t0 = time.time()
        try:
            detail = fn()
            results.append({"step": name, "ok": True, "detail": detail,
                            "seconds": round(time.time() - t0, 2)})
        except Exception as exc:
            results.append({"step": name, "ok": False, "required": required,
                            "error": "%s: %s" % (exc.__class__.__name__, exc),
                            "trace": traceback.format_exc(limit=8)})
            if required:
                ok = False

    import numpy as np
    from . import config, keystore, market_clock, strategies
    from .backtest import backtest_strategy, build_panel

    data = OfflineData()

    def strategy_and_backtest():
        panel = build_panel(data.daily(["SPY", "BIL"]), calendar_symbol="SPY")
        strat = strategies.create(config.DEFAULT_STRATEGY["key"], **config.DEFAULT_STRATEGY["params"])
        res = backtest_strategy(strat, panel)
        m = res.metrics()
        assert np.isfinite(res.equity[-1]) and len(res.trades) > 0
        return {"bars": len(panel), "cagr": round(m["cagr"], 4), "max_dd": round(m["max_dd"], 4),
                "trades": m["trades"]}

    def engine_dry_run():
        from .brokers.sim import SimBroker
        from .engine import BotEngine
        settings = config.Settings(os.path.join(home, "settings.json"))
        last = data.daily_bars["SPY"].local_datetime(-1)
        # a Wednesday-like moment one trading day after the sample's last bar, market open
        nxt = market_clock.next_trading_day(last.date())
        now = market_clock.ny_to_utc(dt.datetime.combine(nxt, dt.time(11, 0)))
        broker = SimBroker(os.path.join(home, "sim.json"), data.prices, 10000, 0,
                           clock=lambda n=None: {"open": True}, now=lambda: now)
        eng = BotEngine(settings, broker, data, now=lambda: now)
        cyc = eng.run_cycle(dry_run=True)
        assert cyc["ok"], cyc
        real = eng.run_cycle()
        assert real["ok"] and broker.positions(), real
        return {"targets": cyc["targets"]["weights"], "orders": len(cyc["orders"]),
                "equity": round(broker.account().equity, 2)}

    def keys():
        secret = "PKTEST1234567890"
        enc = keystore.protect(secret)
        assert keystore.unprotect(enc) == secret
        return {"scheme": enc.split(":", 1)[0]}

    def clock():
        st = market_clock.status()
        return {"open": st["open"], "text": market_clock.describe(st)}

    step("strategy_and_backtest", strategy_and_backtest)
    step("engine_dry_run", engine_dry_run)
    step("keystore", keys)
    step("market_clock", clock)

    def ui():
        app = _qt_app([sys.argv[0]])
        from .ui import context, workers
        from .ui.main_window import MainWindow
        from .ui.platform_window import HAVE_WEB, widget_html
        ctx = context.AppContext(settings=config.Settings(os.path.join(home, "ui_settings.json")),
                                 data=data)
        ctx.settings.set("accepted_disclaimer", True)
        win = MainWindow(ctx)
        win.start()
        for _ in range(20):
            app.processEvents()
            workers.wait_all(200)
            app.processEvents()
        shot = os.path.join(os.path.dirname(os.path.abspath(report_path)), "selftest_chart.png")
        assert win.chart.chart.bars is not None and len(win.chart.chart.bars) > 100
        win.grab().save(shot)
        tabs = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        html = widget_html("THYAO.IS", "1d")
        assert "BIST:THYAO" in html
        win.quit()
        app.processEvents()
        return {"tabs": tabs, "webengine": HAVE_WEB, "screenshot": shot,
                "size": os.path.getsize(shot)}

    step("ui", ui)
    report = {"app": APP_NAME, "version": __version__, "python": sys.version.split()[0],
              "frozen": bool(getattr(sys, "frozen", False)), "platform": sys.platform,
              "ok": ok, "seconds": round(time.time() - started, 1), "steps": results}
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str, ensure_ascii=False)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
