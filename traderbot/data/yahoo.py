"""Yahoo Finance chart API client: free, unofficial, no key.

Endpoints (the same ones trader-skill's alerts.py reads):
  chart   https://query1.finance.yahoo.com/v8/finance/chart/<SYMBOL>
  search  https://query1.finance.yahoo.com/v1/finance/search?q=<text>

Yahoo can change or rate-limit these at any time, so every call has a
timeout, a retry with backoff, and a second host to fall back to.
"""

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .bars import Bars

HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

# How far back Yahoo serves each interval.
MAX_RANGE = {
    "1m": "7d", "2m": "60d", "5m": "60d", "15m": "60d", "30m": "60d", "90m": "60d",
    "60m": "730d", "1h": "730d",
    "1d": "max", "5d": "max", "1wk": "max", "1mo": "max", "3mo": "max",
}
INTRADAY = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}


class DataError(Exception):
    """A symbol, interval or network problem, with a message fit for the UI."""


class Quote(object):
    __slots__ = ("symbol", "name", "price", "prev_close", "currency", "exchange",
                 "time", "gmtoffset", "instrument")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    @property
    def change(self):
        if self.price is None or not self.prev_close:
            return None
        return self.price - self.prev_close

    @property
    def change_pct(self):
        if self.price is None or not self.prev_close:
            return None
        return (self.price / self.prev_close - 1.0) * 100.0

    def __repr__(self):
        return "<Quote %s %s %s>" % (self.symbol, self.price, self.currency)


def _default_open(req, timeout):
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data


class YahooClient(object):
    """Thread-safe: holds no per-call state. `opener(req, timeout) -> bytes`
    can be swapped out in tests."""

    def __init__(self, timeout=15, retries=2, backoff=1.5, opener=None, sleep=time.sleep):
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.opener = opener or _default_open
        self.sleep = sleep

    # ------------------------------------------------------------ transport

    def _get_json(self, path, params):
        query = urllib.parse.urlencode(params)
        last = None
        for attempt in range(self.retries + 1):
            host = HOSTS[attempt % len(HOSTS)]
            url = "https://%s%s?%s" % (host, path, query)
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Accept": "application/json"})
            try:
                return json.loads(self.opener(req, self.timeout).decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = _read_error_body(exc)
                if exc.code in (400, 404, 422):
                    raise DataError(_chart_error(body) or "Yahoo: veri bulunamadı (%s)" % exc.code)
                last = "Yahoo HTTP %s" % exc.code
            except urllib.error.URLError as exc:
                last = "Yahoo'ya ulaşılamadı: %s" % (exc.reason,)
            except (OSError, ValueError) as exc:
                last = "Yahoo yanıtı okunamadı: %s" % (exc,)
            if attempt < self.retries:
                self.sleep(self.backoff * (2 ** attempt))
        raise DataError(last or "Yahoo: bilinmeyen hata")

    # ------------------------------------------------------------ chart

    def chart(self, symbol, interval="1d", range_=None, start=None, end=None, prepost=False):
        """Bars and meta for one symbol. Give `range_` ("5d", "1y", "max") or
        `start`/`end` as unix seconds. Rows with a missing price are dropped."""
        symbol = (symbol or "").strip().upper()
        if not symbol:
            raise DataError("Sembol boş")
        if interval not in MAX_RANGE:
            raise DataError("Desteklenmeyen aralık: %s" % interval)
        params = {"interval": interval, "includePrePost": "true" if prepost else "false",
                  "events": "div,splits"}
        if start is not None:
            params["period1"] = int(start)
            params["period2"] = int(end if end is not None else time.time())
        else:
            params["range"] = range_ or default_range(interval)
        data = self._get_json("/v8/finance/chart/" + urllib.parse.quote(symbol), params)
        return parse_chart(data, symbol, interval)

    def quote(self, symbol):
        """Latest price from the chart meta (no crumb needed, unlike v7 quote)."""
        bars, meta = self.chart(symbol, "1d", range_="5d")
        return quote_from_meta(symbol, meta, bars)

    def search(self, text, limit=8):
        """Symbols matching free text: [{symbol, name, exchange, type}]."""
        text = (text or "").strip()
        if not text:
            return []
        data = self._get_json("/v1/finance/search", {"q": text, "quotesCount": limit,
                                                     "newsCount": 0, "listsCount": 0})
        out = []
        for q in data.get("quotes") or []:
            if not q.get("symbol"):
                continue
            out.append({"symbol": q["symbol"],
                        "name": q.get("longname") or q.get("shortname") or "",
                        "exchange": q.get("exchDisp") or q.get("exchange") or "",
                        "type": q.get("typeDisp") or q.get("quoteType") or ""})
        return out


def default_range(interval):
    return {"1m": "1d", "2m": "5d", "5m": "5d", "15m": "1mo", "30m": "1mo", "90m": "1mo",
            "60m": "6mo", "1h": "6mo", "1d": "2y", "5d": "5y", "1wk": "10y",
            "1mo": "max", "3mo": "max"}.get(interval, "1y")


def parse_chart(data, symbol, interval):
    chart = (data or {}).get("chart") or {}
    if chart.get("error"):
        err = chart["error"]
        raise DataError("Yahoo: %s" % (err.get("description") or err.get("code") or err))
    results = chart.get("result") or []
    if not results:
        raise DataError("Yahoo: %s için veri yok" % symbol)
    res = results[0]
    meta = res.get("meta") or {}
    ts = res.get("timestamp") or []
    ind = res.get("indicators") or {}
    q = (ind.get("quote") or [{}])[0] or {}
    adj_list = None
    if ind.get("adjclose"):
        adj_list = (ind["adjclose"][0] or {}).get("adjclose")
    cols = [q.get(k) or [None] * len(ts) for k in ("open", "high", "low", "close", "volume")]
    t, o, h, l, c, v, adj = [], [], [], [], [], [], []
    for i, stamp in enumerate(ts):
        oi, hi, li, ci = (cols[0][i], cols[1][i], cols[2][i], cols[3][i])
        if None in (oi, hi, li, ci) or stamp is None:
            continue
        t.append(stamp)
        o.append(oi)
        h.append(hi)
        l.append(li)
        c.append(ci)
        v.append(cols[4][i] or 0)
        if adj_list is not None:
            a = adj_list[i] if i < len(adj_list) else None
            adj.append(a if a is not None else ci)
    bars = Bars(meta.get("symbol") or symbol, interval, t, o, h, l, c, v,
                adj if adj_list is not None else None, meta.get("gmtoffset") or 0)
    return bars, meta


def quote_from_meta(symbol, meta, daily=None):
    """Quote from chart meta. The previous close is the last daily close dated
    before the latest trade: meta's chartPreviousClose is the close before the
    whole requested range, which is not yesterday unless the range is 1d."""
    prev = meta.get("previousClose") or meta.get("chartPreviousClose")
    when = meta.get("regularMarketTime")
    if daily is not None and len(daily) and when:
        today = (int(when) + daily.gmtoffset) // 86400
        days = (daily.t + daily.gmtoffset) // 86400
        before = [i for i in range(len(daily)) if days[i] < today]
        if before:
            prev = float(daily.c[before[-1]])
    return Quote(symbol=meta.get("symbol") or symbol,
                 name=meta.get("longName") or meta.get("shortName") or "",
                 price=meta.get("regularMarketPrice"), prev_close=prev,
                 currency=meta.get("currency") or "", exchange=meta.get("fullExchangeName")
                 or meta.get("exchangeName") or "", time=meta.get("regularMarketTime"),
                 gmtoffset=meta.get("gmtoffset") or 0,
                 instrument=meta.get("instrumentType") or "")


def _read_error_body(exc):
    try:
        return json.loads(exc.read().decode("utf-8"))
    except Exception:
        return None


def _chart_error(body):
    try:
        err = body["chart"]["error"]
        return "Yahoo: %s" % (err.get("description") or err.get("code"))
    except (TypeError, KeyError, AttributeError):
        return None
