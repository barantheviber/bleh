"""User settings, kept as JSON in the app folder.

The defaults run the strategy chosen in research/REPORT.md on the built-in
simulated account, so the bot works end to end with no broker account and
no money at risk. Live trading needs Alpaca keys and an explicit opt-in.
"""

import copy
import json
import os
import threading

from . import keystore, paths

# Winner of research/study.py (see research/REPORT.md)
DEFAULT_STRATEGY = {"key": "vol_target",
                    "params": {"symbol": "SPY", "n": 200, "target": 0.15, "vol_n": 20,
                               "off": "BIL"}}

DEFAULTS = {
    "version": 1,
    "broker": "sim",                 # "sim" (built-in paper account) or "alpaca"
    "alpaca_paper": True,
    "alpaca_key_id": "",             # stored protected, see keystore.py
    "alpaca_secret": "",
    "live_confirmed": False,         # the user typed the live-trading confirmation
    "sim_cash": 10000.0,
    "sim_slippage_bps": 2.0,
    "strategy": DEFAULT_STRATEGY,
    "auto_trade": True,              # False: every order waits for the user's approval
    "trade_time": "10:00",           # New York time, once per trading day
    "sell_untracked": True,          # the bot manages the whole account
    "risk": {
        "cash_buffer_pct": 2,
        "max_position_pct": 100,
        "max_order_usd": None,       # None: the account's value
        "min_order_usd": 5,
        "max_orders_per_day": 10,
        "rebalance_band_pct": 5,
        "blocked": [],
        "allow_short": False,
        "allow_margin": False,
        "allow_options": False,
        "max_daily_loss_pct": 5,     # kill switch: halt if the day's loss passes this
        "max_drawdown_pct": 25,      # kill switch: halt if the drop from the peak passes this
    },
    "sec_user_agent": "",
    "watchlist": ["SPY", "QQQ", "BIL", "AAPL", "MSFT", "NVDA", "GOOGL", "THYAO.IS", "BTC-USD"],
    "chart": {"symbol": "SPY", "interval": "5m",
              "overlays": ["ema20", "ema50", "bb"], "panes": ["volume", "rsi", "macd"]},
    "refresh_seconds": 10,
    "platform": "tradingview",
    "copycat": {"cik": "0001067983", "top": 10},
    "news_hours": 48,
    "congress_members": ["pelosi"],
    "alerts": [],                    # see alerts.py
    "alert_check_seconds": 60,
    # Windows notifications from the tray: bot orders, kill switches, alerts
    "notify": {"orders": True, "halts": True, "alerts": True},
    "screener": {"universe": "Sektör ETF'leri (SPDR)", "custom": ""},
}

SECRET_KEYS = ("alpaca_key_id", "alpaca_secret")


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings(object):
    """Thread-safe settings with atomic saves. Secrets are decrypted on
    demand and never written back in clear text."""

    def __init__(self, path=None):
        self.path = path or paths.path("settings.json")
        self._lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self):
        with self._lock:
            if os.path.isfile(self.path):
                try:
                    with open(self.path, encoding="utf-8") as fh:
                        self.data = _merge(DEFAULTS, json.load(fh))
                except (OSError, ValueError):
                    # a broken file is kept aside, never silently overwritten
                    os.replace(self.path, self.path + ".broken")
                    self.data = copy.deepcopy(DEFAULTS)
            return self.data

    def save(self):
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            os.replace(tmp, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    def get(self, key, default=None):
        with self._lock:
            return copy.deepcopy(self.data.get(key, default))

    def set(self, key, value, save=True):
        with self._lock:
            self.data[key] = copy.deepcopy(value)
            if save:
                self.save()

    def update(self, values, save=True):
        with self._lock:
            self.data = _merge(self.data, values)
            if save:
                self.save()

    def secret(self, key):
        with self._lock:
            return keystore.unprotect(self.data.get(key, ""))

    def set_secret(self, key, value, save=True):
        if key not in SECRET_KEYS:
            raise KeyError(key)
        self.set(key, keystore.protect(value.strip()) if value else "", save)

    def risk(self):
        return self.get("risk")

    def is_live(self):
        return self.get("broker") == "alpaca" and not self.get("alpaca_paper")
