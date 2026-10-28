"""Cached market data for the charts, the watchlist and the bot.

One YahooClient behind a small time-based cache, so a chart refreshing every
few seconds and a bot cycle asking for the same quote do not hit Yahoo twice.
"""

import threading
import time

from .yahoo import DataError, YahooClient

QUOTE_TTL = 5.0
BARS_TTL = {"1m": 5, "2m": 10, "5m": 15, "15m": 30, "30m": 60, "60m": 120, "1h": 120,
            "90m": 120, "1d": 300, "5d": 900, "1wk": 900, "1mo": 3600, "3mo": 3600}


class MarketData(object):
    def __init__(self, client=None, clock=time.monotonic):
        self.client = client or YahooClient()
        self.clock = clock
        self._lock = threading.Lock()
        self._bars = {}
        self._quotes = {}

    def bars(self, symbol, interval="1d", range_=None, fresh=False):
        """(Bars, meta) for a symbol, from cache when recent enough."""
        key = (symbol.upper(), interval, range_)
        now = self.clock()
        with self._lock:
            hit = self._bars.get(key)
        if hit and not fresh and now - hit[0] < BARS_TTL.get(interval, 60):
            return hit[1], hit[2]
        bars, meta = self.client.chart(symbol, interval, range_=range_)
        with self._lock:
            self._bars[key] = (now, bars, meta)
        return bars, meta

    def daily(self, symbols, range_="3y"):
        """{symbol: daily Bars} for the bot; raises DataError naming every
        symbol that failed."""
        out, bad = {}, []
        for s in symbols:
            try:
                out[s] = self.bars(s, "1d", range_)[0]
            except DataError as exc:
                bad.append("%s (%s)" % (s, exc))
        if bad:
            raise DataError("Günlük veri alınamadı: " + "; ".join(bad))
        return out

    def quote(self, symbol, fresh=False):
        sym = symbol.upper()
        now = self.clock()
        with self._lock:
            hit = self._quotes.get(sym)
        if hit and not fresh and now - hit[0] < QUOTE_TTL:
            return hit[1]
        q = self.client.quote(sym)
        with self._lock:
            self._quotes[sym] = (now, q)
        return q

    def prices(self, symbols, fresh=False):
        """{symbol: last price}; symbols without a price are left out."""
        out = {}
        for s in symbols:
            try:
                q = self.quote(s, fresh)
            except DataError:
                continue
            if q.price:
                out[s.upper()] = float(q.price)
        return out

    def search(self, text):
        return self.client.search(text)
